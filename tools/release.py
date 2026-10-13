#!/usr/bin/env python3
"""Release helper for .github/workflows/wheels.yml (standard library only; works in the current git repo).

    plan [--force] [--bump patch|minor]  print key=value lines: mode (prepare | release | skip), version, julia
    bump --version X --julia J         bump pyproject.toml, add a CHANGELOG.md section, refresh the README block
    notes X                            print the CHANGELOG.md section of version X (used as the release body)

How the two-step release works:

  1. A new Julia lands in julia-list.json (pushed by the sync workflow)  ->  mode=prepare: CI tests and builds
     the wheels (stored in the `__beta__` prerelease), then `bump` + a commit
     "chore(release): vX.Y.Z (Julia J)" made by github-actions[bot].
  2. That commit is recognised by its message and author  ->  mode=release: CI takes the tested wheels from
     `__beta__`, tags vX.Y.Z and publishes the release.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RELEASE_RE = re.compile(r"^chore\(release\): v(\d+\.\d+\.\d+) \(Julia (\d+\.\d+\.\d+)\)")
BOT = "github-actions[bot]"
LIST, PYPROJECT, CHANGELOG, README = (Path(p) for p in ("julia-list.json", "pyproject.toml", "CHANGELOG.md", "README.md"))
CHANGELOG_HEADER = (
    "# Changelog\n\n"
    "Written automatically by CI (`tools/release.py`) for every release.\n\n"
)
README_BLOCK = re.compile(r"(<!-- release:start -->)(.*?)(<!-- release:end -->)", re.S)


def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip() if r.returncode == 0 else ""


def vkey(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def pyproject_version() -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(), re.M)
    if not m:
        sys.exit("no version in pyproject.toml")
    return m.group(1)


def last_tag() -> str | None:
    tags = git("tag", "--list", "v[0-9]*.[0-9]*.[0-9]*", "--sort=-v:refname")
    return tags.splitlines()[0] if tags else None


def list_at(tag: str | None) -> dict:
    if not tag:
        return {}
    raw = git("show", f"{tag}:julia-list.json", check=False)
    return json.loads(raw) if raw else {}


def next_version(tag: str | None, bump: str = "patch") -> str:
    """patch: 0.0.4 -> 0.0.5 (while the pipeline is being proven); minor: 0.4.2 -> 0.5.0."""
    base = tag[1:] if tag else pyproject_version()
    major, minor, patch = (int(x) for x in (re.findall(r"\d+", base) + ["0", "0", "0"])[:3])
    return f"{major}.{minor + 1}.0" if bump == "minor" else f"{major}.{minor}.{patch + 1}"


def fmt_versions(versions: list[str], limit: int = 12) -> str:
    shown = ", ".join(versions[:limit])
    return shown + (f" (+{len(versions) - limit} more)" if len(versions) > limit else "")


# --------------------------------------------------------------------------- plan


def cmd_plan(a) -> int:
    cur = json.loads(LIST.read_text())
    julia = cur.get("latest") or ""
    tag = last_tag()
    prev = list_at(tag)
    subject, author = git("log", "-1", "--format=%s"), git("log", "-1", "--format=%an")

    mode, version = "skip", ""
    m = RELEASE_RE.match(subject)
    if m and author == BOT:
        version, julia = m.groups()
        if pyproject_version() != version:
            sys.exit(f"release commit says v{version} but pyproject.toml says {pyproject_version()}")
        if git("rev-parse", "-q", "--verify", f"refs/tags/v{version}", check=False):
            print(f"v{version} is already released", file=sys.stderr)
        else:
            mode = "release"
    elif julia and (julia != prev.get("latest") or a.force):
        mode, version = "prepare", next_version(tag, a.bump)
    else:
        print(f"nothing to release (bundled Julia stays {julia or 'unset'})", file=sys.stderr)

    print(f"mode={mode}\nversion={version}\njulia={julia}")
    print(f"plan: mode={mode} version={version or '-'} julia={julia or '-'} (last tag: {tag or 'none'})", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- bump


def cmd_bump(a) -> int:
    cur = json.loads(LIST.read_text())
    prev = list_at(last_tag())
    new = sorted(set(cur.get("versions", {})) - set(prev.get("versions", {})), key=vkey, reverse=True)
    prev_julia = prev.get("latest")
    all_versions = sorted(cur.get("versions", {}), key=vkey, reverse=True)

    PYPROJECT.write_text(re.sub(r'^version\s*=\s*".*"', f'version = "{a.version}"', PYPROJECT.read_text(), count=1, flags=re.M))

    lines = [f"- Bundled Julia: **{a.julia}**" + (f" (previously {prev_julia})" if prev_julia and prev_julia != a.julia else "")]
    if new:
        lines.append(f"- Newly mirrored: {fmt_versions(new)}")
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    section = f"## [{a.version}] - {day}\n\n" + "\n".join(lines) + "\n\n"
    text = CHANGELOG.read_text() if CHANGELOG.exists() else CHANGELOG_HEADER
    i = text.find("\n## [")
    text = text + section if i < 0 else text[: i + 1] + section + text[i + 1 :]
    CHANGELOG.write_text(text)

    repo = cur.get("repo", "")
    block = (
        f"\n**Latest release:** [v{a.version}](https://github.com/{repo}/releases/tag/v{a.version})"
        f" · bundles Julia **{a.julia}** · [changelog](CHANGELOG.md)\n\n"
        f"Mirrored Julia versions: {fmt_versions(all_versions, 10)} ({len(all_versions)} in total)\n"
    )
    if README.exists() and README_BLOCK.search(README.read_text()):
        README.write_text(README_BLOCK.sub(lambda m: m.group(1) + block + m.group(3), README.read_text()))
    else:
        print("README.md has no <!-- release:start --> block; left untouched", file=sys.stderr)
    print(f"bumped to {a.version} (Julia {a.julia})", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- notes


def cmd_notes(a) -> int:
    text = CHANGELOG.read_text() if CHANGELOG.exists() else ""
    m = re.search(rf"^## \[{re.escape(a.version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
    body = m.group(1).strip() if m else f"Release {a.version}"
    print(body + "\n\n`pip install julialang`, then run `julia`; manage versions with `julialang`.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--force", action="store_true", help="prepare a release even if Julia did not change")
    p.add_argument("--bump", choices=["patch", "minor"], default="patch", help="which part of the version to bump")
    p.set_defaults(func=cmd_plan)
    p = sub.add_parser("bump")
    p.add_argument("--version", required=True)
    p.add_argument("--julia", required=True)
    p.set_defaults(func=cmd_bump)
    p = sub.add_parser("notes")
    p.add_argument("version")
    p.set_defaults(func=cmd_notes)
    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
