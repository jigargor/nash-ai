from app.agent.chunking import ChunkingPlannerConfig, classify_diff_files, plan_chunks
from app.agent.diff_parser import FileInDiff, NumberedLine


def _file(path: str, *, added_lines: int, is_deleted: bool = False) -> FileInDiff:
    numbered_lines = [
        NumberedLine(
            new_line_no=index + 1 if not is_deleted else None,
            old_line_no=index + 1,
            kind="add",
            content=f"line_{index}",
        )
        for index in range(added_lines)
    ]
    return FileInDiff(
        path=path,
        language="TypeScript",
        is_new=False,
        is_deleted=is_deleted,
        numbered_lines=numbered_lines,
        context_window=[],
    )


def test_plan_chunks_is_deterministic_for_same_inputs() -> None:
    files = [
        _file("apps/api/src/routes/auth.py", added_lines=30),
        _file("apps/api/src/models/user.py", added_lines=20),
        _file("apps/web/src/app/page.tsx", added_lines=15),
    ]
    config = ChunkingPlannerConfig(
        target_chunk_tokens=200, max_chunks=5, include_file_classes=("reviewable", "config_only")
    )
    first = plan_chunks(
        files,
        config,
        pr_title="Add auth flow",
        pr_body="Introduces auth route and UI updates.",
        generated_paths=[],
        vendor_paths=[],
    )
    second = plan_chunks(
        files,
        config,
        pr_title="Add auth flow",
        pr_body="Introduces auth route and UI updates.",
        generated_paths=[],
        vendor_paths=[],
    )
    assert [chunk.chunk_id for chunk in first.chunks] == [chunk.chunk_id for chunk in second.chunks]
    assert [tuple(file.path for file in chunk.files) for chunk in first.chunks] == [
        tuple(file.path for file in chunk.files) for chunk in second.chunks
    ]


def test_prepass_classifies_generated_lockfile_deleted_and_docs() -> None:
    files = [
        _file("src/generated/client.ts", added_lines=10),
        _file("pnpm-lock.yaml", added_lines=10),
        _file("docs/README.md", added_lines=10),
        _file("src/removed.py", added_lines=0, is_deleted=True),
    ]
    classified = classify_diff_files(files, generated_paths=["src/generated/**"], vendor_paths=[])
    classes = {item.path: item.file_class for item in classified}
    assert classes["src/generated/client.ts"] == "generated"
    assert classes["pnpm-lock.yaml"] == "lockfile"
    assert classes["docs/README.md"] == "docs_only"
    assert classes["src/removed.py"] == "deleted_only"


def test_plan_chunks_sets_partial_when_max_chunks_exceeded() -> None:
    files = [
        _file(f"apps/api/src/domain_{index}/service_{index}.py", added_lines=25)
        for index in range(8)
    ]
    config = ChunkingPlannerConfig(
        target_chunk_tokens=60,
        max_chunks=2,
        include_file_classes=("reviewable",),
    )
    plan = plan_chunks(
        files,
        config,
        pr_title="Large migration",
        pr_body="Touches multiple services.",
        generated_paths=[],
        vendor_paths=[],
    )
    assert plan.is_partial is True
    assert len(plan.chunks) == 2
    assert "truncated at max_chunks" in plan.coverage_note


def test_huge_single_file_stays_reviewable_and_chunked() -> None:
    files = [_file("apps/api/src/heavy/module.py", added_lines=2000)]
    config = ChunkingPlannerConfig(
        target_chunk_tokens=800, max_chunks=5, include_file_classes=("reviewable",)
    )
    plan = plan_chunks(
        files,
        config,
        pr_title="Refactor heavy module",
        pr_body="Very large single-file change.",
        generated_paths=[],
        vendor_paths=[],
    )
    assert len(plan.chunks) == 1
    assert plan.chunks[0].files[0].path == "apps/api/src/heavy/module.py"
