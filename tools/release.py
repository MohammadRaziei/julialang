#!/usr/bin/env python3
"""Release helper for .github/workflows/wheels.yml (standard library only; works in the current git repo).

    plan [--force] [--bump patch|minor]   print key=value lines: mode (prepare | release | skip), version, sha
    set-version X                         write X into pyproject.toml (the build job does this before `python -m build`)
    bump --version X                      set-version + a CHANGELOG.md section (commit subjects) + the README block
    notes X                               print the CHANGELOG.md section of version X (used as the release body)

The package is one pure-Python wheel; Julia itself is downloaded at run time from the mirror, so a release is
needed only when the package code changes, not when a new Julia appears.

How the two-step release works:

  1. Package files changed since the last tag (julialang/, pyproject.toml, LICENSE)  ->  mode=prepare: CI tests,
     builds, smoke-tests the wheel on every OS (a real `julialang install` from the mirror), parks it in the
     `__beta__` prerelease, then `bump` + a commit "chore(release): vX.Y.Z" made by github-actions[bot].
  2. That commit is recognised by its message and author  ->  mode=release: CI takes the tested wheel from
     `__beta__`, tags vX.Y.Z, publishes the release and uploads to PyPI.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RELEASE_RE = re.compile(r"^chore\(release\): v(\d+\.\d+\.\d+)\s*$")
BOT = "github-actions[bot]"
PACKAGE_PATHS = ["julialang", "pyproject.toml", "LICENSE"]  # a change here makes a new release worthwhile
PYPROJECT, CHANGELOG, README = (Path(p) for p in ("pyproject.toml", "CHANGELOG.md", "README.md"))
CHANGELOG_HEADER = "# Changelog\n\nWritten automatically by CI (`tools/release.py`) from commit subjects for every release.\n\n"
README_BLOCK = re.compile(r"(<!-- release:start -->)(.*?)(<!-- release:end -->)", re.S)
SKIP_SUBJECT = re.compile(r"^(chore\(release\):|chore: mirror|Merge )")  # CI bookkeeping, not worth a changelog line


def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip() if r.returncode == 0 else ""


def pyproject_version() -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(), re.M)
    if not m:
        sys.exit("no version in pyproject.toml")
    return m.group(1)


def last_tag() -> str | None:
    tags = git("tag", "--list", "v[0-9]*.[0-9]*.[0-9]*", "--sort=-v:refname")
    return tags.splitlines()[0] if tags else None


def next_version(tag: str | None, bump: str = "patch") -> str:
    """patch: 0.0.4 -> 0.0.5 (while the pipeline is being proven); minor: 0.4.2 -> 0.5.0."""
    base = tag[1:] if tag else pyproject_version()
    major, minor, patch = (int(x) for x in (re.findall(r"\d+", base) + ["0", "0", "0"])[:3])
    return f"{major}.{minor + 1}.0" if bump == "minor" else f"{major}.{minor}.{patch + 1}"


def repo_slug() -> str:
    """owner/name from $GITHUB_REPOSITORY or the origin remote ('' when unknown)."""
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", git("config", "--get", "remote.origin.url", check=False))
    return m.group(1) if m else ""


def commit_subjects(tag: str | None) -> list[str]:
    rng = f"{tag}..HEAD" if tag else "HEAD"
    subjects = git("log", rng, "--format=%s").splitlines()
    return [s for s in subjects if s and not SKIP_SUBJECT.match(s)]


# --------------------------------------------------------------------------- plan


def cmd_plan(a) -> int:
    tag = last_tag()
    subject, author = git("log", "-1", "--format=%s"), git("log", "-1", "--format=%an")
    sha = git("rev-parse", "HEAD")

    mode, version = "skip", ""
    m = RELEASE_RE.match(subject)
    if m and author == BOT:
        version = m.group(1)
        if pyproject_version() != version:
            sys.exit(f"release commit says v{version} but pyproject.toml says {pyproject_version()}")
        if git("rev-parse", "-q", "--verify", f"refs/tags/v{version}", check=False):
            print(f"v{version} is already released", file=sys.stderr)
        else:
            mode = "release"
    else:
        changed = git("diff", "--name-only", f"{tag}..HEAD", "--", *PACKAGE_PATHS).splitlines() if tag else PACKAGE_PATHS
        if changed or a.force:
            mode, version = "prepare", next_version(tag, a.bump)
        else:
            print(f"nothing to release: no package changes since {tag}", file=sys.stderr)

    print(f"mode={mode}\nversion={version}\nsha={sha}")
    print(f"plan: mode={mode} version={version or '-'} (last tag: {tag or 'none'})", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- set-version / bump


def set_version(version: str) -> None:
    text = PYPROJECT.read_text()
    new, n = re.subn(r'^version\s*=\s*".*"', f'version = "{version}"', text, count=1, flags=re.M)
    if not n:
        sys.exit("no version in pyproject.toml")
    PYPROJECT.write_text(new)


def cmd_set_version(a) -> int:
    set_version(a.version)
    print(f"pyproject.toml: version = {a.version}", file=sys.stderr)
    return 0


def cmd_bump(a) -> int:
    subjects = commit_subjects(last_tag())
    set_version(a.version)

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"- {s}" for s in subjects[:30]] or ["- Maintenance release"]
    if len(subjects) > 30:
        lines.append(f"- ... and {len(subjects) - 30} more commits")
    section = f"## [{a.version}] - {day}\n\n" + "\n".join(lines) + "\n\n"
    text = CHANGELOG.read_text() if CHANGELOG.exists() else CHANGELOG_HEADER
    i = text.find("\n## [")
    text = text + section if i < 0 else text[: i + 1] + section + text[i + 1 :]
    CHANGELOG.write_text(text)

    repo = a.repo or repo_slug()
    link = f"[v{a.version}](https://github.com/{repo}/releases/tag/v{a.version})" if repo else f"v{a.version}"
    block = f"\n**Latest release:** {link} · [changelog](CHANGELOG.md)\n"
    if README.exists() and README_BLOCK.search(README.read_text()):
        README.write_text(README_BLOCK.sub(lambda m: m.group(1) + block + m.group(3), README.read_text()))
    else:
        print("README.md has no <!-- release:start --> block; left untouched", file=sys.stderr)
    print(f"bumped to {a.version}", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- notes


def cmd_notes(a) -> int:
    text = CHANGELOG.read_text() if CHANGELOG.exists() else ""
    m = re.search(rf"^## \[{re.escape(a.version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
    body = m.group(1).strip() if m else f"Release {a.version}"
    print(body + "\n\n`pip install julialang`, then `julialang install` and run `julia`.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--force", action="store_true", help="prepare a release even without package changes")
    p.add_argument("--bump", choices=["patch", "minor"], default="patch", help="which part of the version to bump")
    p.set_defaults(func=cmd_plan)
    p = sub.add_parser("set-version")
    p.add_argument("version")
    p.set_defaults(func=cmd_set_version)
    p = sub.add_parser("bump")
    p.add_argument("--version", required=True)
    p.add_argument("--repo", help="owner/name for the README link (default: $GITHUB_REPOSITORY or the origin remote)")
    p.set_defaults(func=cmd_bump)
    p = sub.add_parser("notes")
    p.add_argument("version")
    p.set_defaults(func=cmd_notes)
    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
