from __future__ import annotations

import json
import logging
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, ValidationError

from app.agent.chunking import ClassifiedDiffFile, classify_diff_files
from app.agent.context_builder import count_tokens
from app.agent.diff_parser import FileInDiff
from app.agent.prompt_compaction import compact_diff_excerpt, extension_histogram
from app.agent.review_config import FastPathConfig
from app.llm.providers import StructuredOutputRequest, get_provider_adapter
from app.llm.types import ModelProvider

FastPathDecisionValue = Literal["skip_review", "light_review", "full_review", "high_risk_review"]
logger = logging.getLogger(__name__)

HIGH_RISK_PATH_TOKENS = (
    "auth",
    "authentication",
    "authorization",
    "billing",
    "crypto",
    "database",
    "db",
    "infra",
    "migration",
    "oauth",
    "payment",
    "permission",
    "policy",
    "rls",
    "secret",
    "security",
    "session",
    "sql",
    "token",
    "webhook",
)


class FastPathDecision(BaseModel):
    decision: FastPathDecisionValue
    risk_labels: list[str] = Field(default_factory=list)
    reason: str
    confidence: int | None = Field(default=None, ge=0, le=100)
    review_surface: list[str] = Field(default_factory=list)
    requires_full_context: bool = True


FAST_PATH_TOOL = {
    "name": "classify_fast_path",
    "description": "Classify whether a pull request needs full code review.",
    "input_schema": {},
}


def _fast_path_input_schema() -> dict[str, Any]:
    schema = cast(dict[str, Any], FastPathDecision.model_json_schema())
    required = schema.get("required")
    required_set = set(required) if isinstance(required, list) else set()
    required_set.update({"decision", "reason", "confidence"})
    schema["required"] = sorted(required_set)
    props = schema.get("properties")
    if isinstance(props, dict):
        props["confidence"] = {"type": "integer", "minimum": 0, "maximum": 100}
    return schema


FAST_PATH_TOOL["input_schema"] = _fast_path_input_schema()


def fallback_full_review(reason: str, *, risk_labels: list[str] | None = None) -> FastPathDecision:
    return FastPathDecision(
        decision="full_review",
        risk_labels=risk_labels or ["uncertain"],
        reason=reason[:500],
        confidence=None,
        review_surface=[],
        requires_full_context=True,
    )


def normalize_fast_path_decision(
    raw: object, config: FastPathConfig, classified: list[ClassifiedDiffFile]
) -> FastPathDecision:
    if not isinstance(raw, dict):
        return fallback_full_review("Fast-path model returned an invalid decision schema.")
    payload = dict(raw)
    confidence_source = "model"
    normalized_confidence = _normalize_confidence_value(payload.get("confidence"))
    if normalized_confidence is not None:
        payload["confidence"] = normalized_confidence
    else:
        recovered = _recover_confidence(payload, classified)
        if recovered is not None:
            payload["confidence"] = recovered[0]
            confidence_source = recovered[1]
            labels = payload.get("risk_labels")
            if isinstance(labels, list):
                labels = [str(item) for item in labels]
                if "confidence_recovered" not in labels:
                    labels.append("confidence_recovered")
                payload["risk_labels"] = labels
            else:
                payload["risk_labels"] = ["confidence_recovered"]
    payload["confidence_source"] = confidence_source
    if "confidence" not in payload:
        logger.warning("Fast-path decision missing confidence. Escalating to full review.")
        return fallback_full_review(
            "Fast-path model omitted confidence; escalated for safety.",
            risk_labels=["missing_confidence"],
        )
    try:
        decision = FastPathDecision.model_validate(payload)
    except ValidationError:
        return fallback_full_review("Fast-path model returned an invalid decision schema.")
    if decision.confidence is None:
        return fallback_full_review(
            "Fast-path model returned null confidence; escalated for safety.",
            risk_labels=["missing_confidence"],
        )

    high_risk_paths = [item.path for item in classified if is_high_risk_path(item.path)]
    if high_risk_paths and decision.decision in {"skip_review", "light_review"}:
        return FastPathDecision(
            decision="full_review",
            risk_labels=sorted({*decision.risk_labels, "high_risk_path"}),
            reason="Escalated because high-risk files were touched.",
            confidence=decision.confidence,
            review_surface=high_risk_paths,
            requires_full_context=True,
        )
    if decision.decision == "skip_review":
        if not config.allow_skip:
            return FastPathDecision(
                decision="full_review",
                risk_labels=sorted({*decision.risk_labels, "skip_disabled"}),
                reason="Escalated because fast-path skipping is disabled.",
                confidence=decision.confidence,
                review_surface=decision.review_surface,
                requires_full_context=True,
            )
        if int(decision.confidence) < config.skip_min_confidence:
            return FastPathDecision(
                decision="full_review",
                risk_labels=sorted({*decision.risk_labels, "low_confidence"}),
                reason="Escalated because skip confidence was below the configured threshold.",
                confidence=decision.confidence,
                review_surface=decision.review_surface,
                requires_full_context=True,
            )
    if (
        decision.decision == "light_review"
        and int(decision.confidence) < config.light_review_min_confidence
    ):
        return FastPathDecision(
            decision="full_review",
            risk_labels=sorted({*decision.risk_labels, "low_confidence"}),
            reason="Escalated because light-review confidence was below the configured threshold.",
            confidence=decision.confidence,
            review_surface=decision.review_surface,
            requires_full_context=True,
        )
    if decision.requires_full_context and decision.decision in {"skip_review", "light_review"}:
        return FastPathDecision(
            decision="full_review",
            risk_labels=sorted({*decision.risk_labels, "requires_full_context"}),
            reason="Escalated because the model requested full context.",
            confidence=decision.confidence,
            review_surface=decision.review_surface,
            requires_full_context=True,
        )
    return decision


def _recover_confidence(
    payload: dict[str, Any], classified: list[ClassifiedDiffFile]
) -> tuple[int, str] | None:
    for key in ("confidence_score", "score", "certainty", "probability"):
        raw_value = payload.get(key)
        candidate = _normalize_confidence_value(raw_value)
        if candidate is not None:
            return candidate, f"alias:{key}"
    inferred = _heuristic_confidence(classified)
    if inferred is not None:
        return inferred, "heuristic:file_profile"
    return None


def _normalize_confidence_value(raw_value: object) -> int | None:
    if isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        if 0 <= raw_value <= 100:
            return raw_value
        return None
    if isinstance(raw_value, float):
        if 0 <= raw_value <= 1:
            return int(round(raw_value * 100))
        if 0 <= raw_value <= 100:
            return int(round(raw_value))
        return None
    if isinstance(raw_value, str):
        cleaned = raw_value.strip().replace("%", "")
        if not cleaned:
            return None
        try:
            parsed = float(cleaned)
        except ValueError:
            return None
        return _normalize_confidence_value(parsed)
    return None


def _heuristic_confidence(classified: list[ClassifiedDiffFile]) -> int | None:
    if not classified:
        return None
    changed_lines = sum(max(0, int(item.changed_lines)) for item in classified)
    classes = {item.file_class for item in classified}
    if any(is_high_risk_path(item.path) for item in classified):
        return 40
    if classes.issubset({"docs_only", "generated", "lockfile"}) and changed_lines <= 250:
        return 95
    if classes.issubset({"config_only", "test_only", "docs_only"}) and changed_lines <= 180:
        return 84
    if changed_lines <= 80 and len(classified) <= 3:
        return 78
    return 65


async def run_fast_path_prepass(
    *,
    files_in_diff: list[FileInDiff],
    diff_text: str,
    pr: dict[str, Any],
    commits: list[dict[str, Any]],
    generated_paths: list[str],
    vendor_paths: list[str],
    config: FastPathConfig,
    context: dict[str, Any],
    model_name: str,
    provider: ModelProvider,
) -> tuple[FastPathDecision, list[ClassifiedDiffFile], str, str]:
    classified = classify_diff_files(
        files_in_diff, generated_paths=generated_paths, vendor_paths=vendor_paths
    )
    system_prompt = _system_prompt()
    user_prompt = build_fast_path_prompt(
        classified,
        diff_text=diff_text,
        pr=pr,
        commits=commits,
        max_diff_excerpt_tokens=config.max_diff_excerpt_tokens,
    )
    raw_decision = await _request_fast_path_decision(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        context=context,
        model_name=model_name,
        provider=provider,
    )
    return (
        normalize_fast_path_decision(raw_decision, config, classified),
        classified,
        system_prompt,
        user_prompt,
    )


def build_fast_path_prompt(
    classified: list[ClassifiedDiffFile],
    *,
    diff_text: str,
    pr: dict[str, Any],
    commits: list[dict[str, Any]],
    max_diff_excerpt_tokens: int,
) -> str:
    manifest = [
        {
            "path": item.path,
            "class": item.file_class,
            "changed_lines": item.changed_lines,
            "estimated_diff_tokens": item.estimated_diff_tokens,
            "high_risk_path": is_high_risk_path(item.path),
        }
        for item in classified
    ]
    commit_messages = [
        str((commit.get("commit") or {}).get("message", ""))[:240] for commit in commits[:10]
    ]
    payload = {
        "pull_request": {
            "title": str(pr.get("title", ""))[:300],
            "body": str(pr.get("body", "") or "")[:1000],
            "draft": bool(pr.get("draft", False)),
        },
        "commits": commit_messages,
        "changed_files": manifest,
        "compact_manifest": {
            "extension_histogram": extension_histogram([item.path for item in classified]),
            "total_changed_lines": sum(int(item.changed_lines) for item in classified),
        },
        "diff_excerpt": compact_diff_excerpt(diff_text, max_diff_excerpt_tokens),
    }
    return (
        "Classify this PR for review routing. Return only the classify_fast_path tool call.\n"
        "Always provide confidence as an integer from 0 to 100; never omit or null this field.\n"
        "Use skip_review only for clearly non-runtime changes such as docs, generated files, or lockfiles with no reviewable risk.\n"
        "Use light_review for simple low-risk tests/config/code changes. Use full_review when uncertain.\n"
        "Use high_risk_review when security, auth, DB, billing, infra, permissions, secrets, or webhook behavior may be affected.\n\n"
        f"{json.dumps(payload, indent=2, sort_keys=True)}"
    )


def is_high_risk_path(path: str) -> bool:
    lowered = path.lower()
    parts = {
        part
        for part in lowered.replace("\\", "/").replace("-", "_").replace(".", "_").split("/")
        if part
    }
    tokens: set[str] = set()
    for part in parts:
        tokens.update(piece for piece in part.split("_") if piece)
    return bool(tokens.intersection(HIGH_RISK_PATH_TOKENS))


def fast_path_metadata(
    decision: FastPathDecision,
    *,
    classified: list[ClassifiedDiffFile],
    diff_tokens: int,
    fallback_reason: str | None,
) -> dict[str, Any]:
    changed_line_count = sum(int(item.changed_lines) for item in classified)
    review_surface_paths = [
        str(path).strip() for path in decision.review_surface if isinstance(path, str) and path.strip()
    ]
    return {
        "decision": decision.decision,
        "risk_labels": decision.risk_labels,
        "confidence": decision.confidence,
        "confidence_source": "model"
        if "confidence_recovered" not in set(decision.risk_labels)
        else "recovered",
        "reason": decision.reason,
        "review_surface_paths": review_surface_paths,
        "review_surface_count": len(review_surface_paths),
        # Backward compatibility for existing consumers.
        "review_surface": review_surface_paths,
        "requires_full_context": decision.requires_full_context,
        "fallback_reason": fallback_reason,
        "diff_tokens": diff_tokens,
        "changed_file_count": len(classified),
        "changed_line_count": changed_line_count,
        "file_classes": dict(sorted(_file_class_counts(classified).items())),
    }


async def _request_fast_path_decision(
    *,
    system_prompt: str,
    user_prompt: str,
    context: dict[str, Any],
    model_name: str,
    provider: ModelProvider,
) -> object:
    adapter = get_provider_adapter(provider)
    result = await adapter.structured_output(
        request=StructuredOutputRequest(
            model_name=model_name,
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tool_name=str(FAST_PATH_TOOL["name"]),
            tool_description=str(FAST_PATH_TOOL["description"]),
            input_schema=cast(dict[str, Any], FAST_PATH_TOOL["input_schema"]),
            context=context,
            max_tokens=1024,
            temperature=0,
        )
    )
    return result.payload


def _system_prompt() -> str:
    return (
        "You are a conservative code-review router. Your only job is to decide how much review this PR needs. "
        "When in doubt, select full_review. Never skip security, auth, database, billing, infrastructure, "
        "permissions, secrets, or webhook changes."
    )


def _diff_excerpt(diff_text: str, max_tokens: int) -> str:
    lines: list[str] = []
    tokens = 0
    for line in diff_text.splitlines():
        line_tokens = count_tokens(line)
        if lines and tokens + line_tokens > max_tokens:
            break
        lines.append(line[:500])
        tokens += line_tokens
    return "\n".join(lines)


def _file_class_counts(classified: list[ClassifiedDiffFile]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in classified:
        counts[item.file_class] = counts.get(item.file_class, 0) + 1
    return counts
