"""Extension → tree-sitter language names for suggestion parse checks."""

from __future__ import annotations

EXT_TO_LANGUAGE: dict[str, str] = {
    "py": "python",
    "pyi": "python",
    "ts": "typescript",
    "tsx": "tsx",
    "js": "javascript",
    "jsx": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "go": "go",
    "rs": "rust",
    "sql": "sql",
    "java": "java",
    "kt": "kotlin",
    "kts": "kotlin",
    "c": "c",
    "h": "c",
    "cc": "cpp",
    "cpp": "cpp",
    "cxx": "cpp",
    "hpp": "cpp",
    "cs": "c_sharp",
    "rb": "ruby",
    "php": "php",
    "swift": "swift",
    "scala": "scala",
    "sh": "bash",
    "bash": "bash",
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "toml": "toml",
    "html": "html",
    "css": "css",
    "vue": "html",
    "svelte": "html",
    "md": "markdown",
}


def language_for_path(path: str) -> str | None:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return EXT_TO_LANGUAGE.get(ext)
