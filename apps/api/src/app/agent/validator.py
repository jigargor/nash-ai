from app.agent.schema import Finding

try:
    from tree_sitter_language_pack import get_parser
except Exception:  # pragma: no cover - import fallback for constrained environments
    get_parser = None


class FindingValidator:
    def __init__(self, file_contents: dict[str, str]):
        """file_contents: path -> full text at PR head"""
        self._files = file_contents
        self._parsers: dict[str, object] = {}

    def validate(self, finding: Finding) -> tuple[bool, str | None]:
        """Return (is_valid, reason_if_invalid)."""
        if finding.file_path not in self._files:
            return False, f"File {finding.file_path} not in PR context"

        content = self._files[finding.file_path]
        lines = content.split("\n")

        end_line = finding.line_end or finding.line_start
        if finding.line_start < 1 or finding.line_start > len(lines):
            return False, f"line_start {finding.line_start} out of range"
        if end_line < finding.line_start:
            return False, f"line_end {end_line} before line_start {finding.line_start}"
        if end_line > len(lines):
            return False, f"line_end {end_line} out of range"

        actual_target_line = lines[finding.line_start - 1]
        if finding.target_line_content != actual_target_line:
            return False, "target_line_content does not match file content at line_start"

        if finding.suggestion:
            new_lines = (
                lines[: finding.line_start - 1]
                + finding.suggestion.split("\n")
                + lines[end_line:]
            )
            new_content = "\n".join(new_lines)
            if not self._parses(finding.file_path, new_content):
                return False, "Suggestion produces syntactically invalid code"

            replaced = "\n".join(lines[finding.line_start - 1 : end_line])
            if not self._suggestion_is_coherent(replaced, finding.suggestion, finding.message):
                return False, "Suggestion does not coherently replace the target region"

        return True, None

    def _parses(self, path: str, content: str) -> bool:
        language = self._detect_language(path)
        if not language:
            return True
        if get_parser is None:
            return True
        if language not in self._parsers:
            try:
                self._parsers[language] = get_parser(language)
            except Exception:
                return True

        parser = self._parsers[language]
        tree = parser.parse(bytes(content, "utf-8"))
        return not self._has_error(tree.root_node)

    @staticmethod
    def _detect_language(path: str) -> str | None:
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        return {
            "py": "python",
            "ts": "typescript",
            "tsx": "tsx",
            "js": "javascript",
            "jsx": "javascript",
            "go": "go",
            "rs": "rust",
            "sql": "sql",
        }.get(ext)

    @classmethod
    def _has_error(cls, node) -> bool:
        if node.type == "ERROR" or node.is_missing:
            return True
        return any(cls._has_error(child) for child in node.children)

    @staticmethod
    def _suggestion_is_coherent(replaced: str, suggestion: str, message: str) -> bool:
        replaced_clean = replaced.strip()
        suggestion_clean = suggestion.strip()
        if not suggestion_clean:
            return False
        if suggestion_clean == replaced_clean:
            return False
        message_clean = message.strip().lower()
        if len(message_clean) < 8:
            return False
        normalized_replaced = replaced_clean.lower().replace("(", " ").replace(")", " ")
        normalized_suggestion = suggestion_clean.lower().replace("(", " ").replace(")", " ")
        replaced_tokens = {token for token in normalized_replaced.split() if len(token) > 2}
        suggestion_tokens = {token for token in normalized_suggestion.split() if len(token) > 2}
        if replaced_tokens and suggestion_tokens and not replaced_tokens.intersection(suggestion_tokens):
            return False
        return True
