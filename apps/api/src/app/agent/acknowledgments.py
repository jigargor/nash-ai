from dataclasses import dataclass
import re

TODO_PATTERN = re.compile(
    r"(?://|#|/\*|\*)\s*(TODO|FIXME|XXX|HACK)[\(:]?.*",
    re.IGNORECASE,
)


@dataclass
class CodeAcknowledgment:
    file_path: str
    line_number: int
    marker: str
    text: str


def extract_todo_fixme_markers(fetched_files: dict[str, str]) -> list[CodeAcknowledgment]:
    acknowledgments: list[CodeAcknowledgment] = []
    for file_path, content in fetched_files.items():
        for line_number, line in enumerate(content.splitlines(), start=1):
            match = TODO_PATTERN.search(line)
            if match is None:
                continue
            acknowledgments.append(
                CodeAcknowledgment(
                    file_path=file_path,
                    line_number=line_number,
                    marker=match.group(1).upper(),
                    text=line.strip(),
                )
            )
    return acknowledgments
