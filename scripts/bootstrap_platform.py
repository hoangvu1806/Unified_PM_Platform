"""Import BA, Designer and wiki-mvp sources into platform/ verbatim.

BA and Designer are read from their committed HEAD via ``git archive`` so the
copy contains exactly the tracked files with repository line endings. wiki-mvp
has no git history, so it is copied from disk with runtime data excluded.

Usage (from platform/):
    python scripts/bootstrap_platform.py [--sources ..] [--force]

The mapping table mirrors refactor-plan/01-target-structure.md.
"""

from __future__ import annotations

import argparse
import fnmatch
import io
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]

# (source repo, path prefix inside repo, destination under platform/, excluded globs)
GIT_MAPPINGS: list[tuple[str, str, str, list[str]]] = [
    (
        "BA",
        "",
        "services/ba",
        [
            "frontend/*",
            "docker-compose.yml",
            "docker-compose.*.yml",
            ".env*",
            ".cursor/*",
            ".gitignore",
        ],
    ),
    ("BA", "frontend/", "apps/ba-web", []),
    ("BA", ".cursor/", ".cursor", []),
    ("Designer", "backend/", "services/designer", []),
    ("Designer", "frontend/", "apps/designer-web", []),
    ("Designer", "docs/", "services/designer/docs", []),
    ("Designer", "infra/", "services/designer/infra", []),
    ("Designer", "README.md", "services/designer/README.md", []),
    ("Designer", "ba-package_usecase_01.json", "services/designer/tests/fixtures/ba-package_usecase_01.json", []),
    ("Designer", "ba-package_usecase_02.json", "services/designer/tests/fixtures/ba-package_usecase_02.json", []),
]

WIKI_SOURCE = "wiki-mvp"
WIKI_DEST = "packages/wiki"
WIKI_INCLUDE = ["wiki", "tests", "config", "templates", "pyproject.toml", "Makefile", "README.md", ".env.example"]
WIKI_EXCLUDE = ["__pycache__", "*.pyc", ".DS_Store"]


def _git_archive(repo: Path) -> tarfile.TarFile:
    data = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", "HEAD"],
        check=True,
        capture_output=True,
    ).stdout
    return tarfile.open(fileobj=io.BytesIO(data))


def _excluded(rel: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, p) for p in patterns)


def import_git(sources: Path, log: list[str]) -> None:
    archives: dict[str, tarfile.TarFile] = {}
    for repo, prefix, dest, excludes in GIT_MAPPINGS:
        tar = archives.setdefault(repo, _git_archive(sources / repo))
        count = 0
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = member.name
            if prefix.endswith("/") or prefix == "":
                if not name.startswith(prefix):
                    continue
                rel = name[len(prefix):]
                if _excluded(rel, excludes):
                    continue
                target = PLATFORM / dest / rel
            else:
                if name != prefix:
                    continue
                target = PLATFORM / dest
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = tar.extractfile(member)
            assert extracted is not None
            target.write_bytes(extracted.read())
            if member.mode & 0o111:
                target.chmod(target.stat().st_mode | 0o111)
            count += 1
        log.append(f"{repo}/{prefix or '.'} -> {dest}: {count} files")


def import_wiki(sources: Path, log: list[str]) -> None:
    root = sources / WIKI_SOURCE
    dest = PLATFORM / WIKI_DEST
    count = 0
    for item in WIKI_INCLUDE:
        src = root / item
        if src.is_dir():
            for path in src.rglob("*"):
                rel = path.relative_to(root)
                if path.is_dir() or any(fnmatch.fnmatch(part, p) for part in rel.parts for p in WIKI_EXCLUDE):
                    continue
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                count += 1
        elif src.is_file():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / item)
            count += 1
    log.append(f"{WIKI_SOURCE} -> {WIKI_DEST}: {count} files")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=PLATFORM.parent)
    parser.add_argument("--force", action="store_true", help="overwrite existing destinations")
    args = parser.parse_args()

    dests = {PLATFORM / d for _, _, d, _ in GIT_MAPPINGS} | {PLATFORM / WIKI_DEST}
    existing = [d for d in dests if d.exists() and d.is_dir() and any(d.iterdir())]
    if existing and not args.force:
        print("Destinations already populated (use --force):", *sorted(map(str, existing)), sep="\n  ")
        return 1

    log: list[str] = []
    import_git(args.sources, log)
    import_wiki(args.sources, log)
    print("\n".join(log))
    return 0


if __name__ == "__main__":
    sys.exit(main())
