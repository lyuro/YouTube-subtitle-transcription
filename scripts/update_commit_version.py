#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK_PATH = REPO_ROOT / "YouTube_Transcribe.ipynb"
VERSION_LINE_RE = re.compile(r"^\*\*版本：v\d+\*\*\n?$")


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def get_commit_count() -> int:
    result = run_git("rev-list", "--count", "HEAD", check=False)
    if result.returncode != 0:
        return 0

    output = result.stdout.strip()
    if not output.isdigit():
        raise RuntimeError(f"Unexpected git rev-list output: {output!r}")
    return int(output)


def ensure_no_unstaged_changes(path: Path) -> None:
    rel_path = path.relative_to(REPO_ROOT).as_posix()
    result = run_git("diff", "--name-only", "--", rel_path, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")

    if result.stdout.strip():
        raise RuntimeError(
            f"{rel_path} has unstaged changes. Stage or stash it before committing so the version hook can update it safely."
        )


def update_notebook_version(version: int) -> bool:
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    cells = notebook.get("cells", [])
    if not cells:
        raise RuntimeError("Notebook has no cells")

    first_cell = cells[0]
    if first_cell.get("cell_type") != "markdown":
        raise RuntimeError("Expected the first notebook cell to be markdown")

    version_line = f"**版本：v{version}**\n"
    source = first_cell.get("source", [])

    updated_source: list[str] = []
    replaced = False
    for line in source:
        if VERSION_LINE_RE.fullmatch(line):
            if not replaced:
                updated_source.append(version_line)
                replaced = True
            continue
        updated_source.append(line)

    if not replaced:
        if updated_source and updated_source[0].startswith("#"):
            rest = updated_source[1:]
            while rest and not rest[0].strip():
                rest = rest[1:]
            updated_source = [updated_source[0], "\n", version_line, "\n", *rest]
        else:
            updated_source = [version_line, "\n", *updated_source]

    if updated_source == source:
        return False

    first_cell["source"] = updated_source
    NOTEBOOK_PATH.write_text(
        json.dumps(notebook, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return True


def stage_file(path: Path) -> None:
    run_git("add", "--", path.relative_to(REPO_ROOT).as_posix())


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync notebook version banner with git commit count")
    parser.add_argument("--next", action="store_true", help="Use the next commit count instead of the current HEAD count")
    parser.add_argument("--stage", action="store_true", help="Stage the updated notebook after writing it")
    args = parser.parse_args()

    version = get_commit_count()
    if args.next:
        version += 1

    if args.stage:
        ensure_no_unstaged_changes(NOTEBOOK_PATH)

    changed = update_notebook_version(version)
    if args.stage and changed:
        stage_file(NOTEBOOK_PATH)

    print(f"Notebook version synced to v{version}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Version sync failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
