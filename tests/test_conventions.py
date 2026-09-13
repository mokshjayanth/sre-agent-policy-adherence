"""Repo conventions from CLAUDE.md: note names and frontmatter, run folder names, live path references."""

import re
from pathlib import Path

import pytest

from runner.run_batch import CONDITION_PATTERN

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTES = sorted(p for p in (REPO_ROOT / "notes").glob("*.md") if p.name != "_template.md")


@pytest.mark.parametrize("note", NOTES, ids=lambda p: p.name)
def test_note_name_and_frontmatter(note):
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md", note.name)
    lines = note.read_text().splitlines()
    assert lines[0] == "---"
    frontmatter = lines[1:lines.index("---", 1)]
    keys = {line.split(":", 1)[0] for line in frontmatter if re.match(r"^\w+:", line)}
    assert {"date", "type", "status", "evidence"} <= keys
    date = next(line for line in frontmatter if line.startswith("date:")).split(":", 1)[1].strip()
    assert note.name.startswith(date)


def test_run_folders_follow_the_naming_rule():
    runs = REPO_ROOT / "runs"
    if not runs.is_dir():
        pytest.skip("no runs/ folder in this checkout")
    for folder in runs.iterdir():
        if folder.name == "_legacy":
            continue
        stamp, _, condition = folder.name.partition("_")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{6}Z", stamp), folder.name
        assert CONDITION_PATTERN.fullmatch(condition), folder.name


# Repo-relative paths written in docs and code, e.g. `runner/run_batch.py`. Relative links
# such as `../agents/x.py` and paths inside third_party/ are not checked.
PATH_REFERENCE = re.compile(r"(?<![\w/.])(?:agents|runner|tests|configs|notes)/[\w.-]+(?:/[\w.-]+)*\.(?:py|md|yaml)")
DOCUMENTS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "CLAUDE.md",
    *NOTES,
    *sorted((REPO_ROOT / "agents").glob("*.py")),
    *sorted((REPO_ROOT / "runner").glob("*.py")),
    *sorted((REPO_ROOT / "configs").glob("*.yaml")),
]


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_referenced_repo_paths_exist(document):
    referenced = set(PATH_REFERENCE.findall(document.read_text()))
    missing = sorted(path for path in referenced if not (REPO_ROOT / path).exists())
    assert not missing
