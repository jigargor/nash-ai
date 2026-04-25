import re

from pydantic import ValidationError

from app.agent.schema import Finding

VENDOR_PATTERNS = [
    r"\b(vercel|netlify|cloudflare|fly\.io|railway|render)\b",
    r"\bx-(vercel|real|forwarded)-(for|ip)\b",
    r"\b(aws|s3|ec2|lambda|iam|dynamodb|cloudfront)\b",
    r"\b(gcp|firebase|firestore)\b",
    r"\b(supabase|auth0|clerk|nextauth)\b",
    r"\brls\b|\brow level security\b",
    r"\bnext\.js\s+(middleware|server\s+action|app\s+router|cache)\b",
    r"\bserver\s+components?\b",
    r"\b(csp|content.security.policy)\b",
    r"\bcors\s+(preflight|header)\b",
    r"\bsamesite\b|\bhttponly\b",
    r"\bjwt\s+(signing|verification|algorithm)\b",
    r"\b(drizzle|prisma|sequelize|mongoose)\s+",
]

_COMPILED = [re.compile(pattern, re.IGNORECASE) for pattern in VENDOR_PATTERNS]


def looks_like_vendor_claim(finding_message: str) -> bool:
    return any(pattern.search(finding_message) for pattern in _COMPILED)


def auto_tag_vendor_claims(
    findings: list[Finding],
) -> tuple[list[Finding], list[tuple[Finding, str]]]:
    accepted: list[Finding] = []
    rejected: list[tuple[Finding, str]] = []

    for finding in findings:
        if not finding.is_vendor_claim and looks_like_vendor_claim(finding.message):
            finding.is_vendor_claim = True
            try:
                validated = Finding.model_validate(finding.model_dump(mode="json"))
            except ValidationError as exc:
                rejected.append((finding, f"auto_tagged_vendor_claim_invalid: {exc}"))
                continue
            accepted.append(validated)
            continue
        accepted.append(finding)

    return accepted, rejected
