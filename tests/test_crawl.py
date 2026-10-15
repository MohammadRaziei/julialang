"""Crawler (HTML fixtures shaped like the julialang.org tables) and mirror-list tests."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import sync  # noqa: E402

S3 = "https://julialang-s3.julialang.org/bin"
SHA = "a" * 64


def old_row(version_cell: str, url: str, sha: str) -> str:
    return f"<tr><td>{version_cell}</td><td>x</td><td>x</td><td>archive</td><td><a href='{url}'>f</a> (<a href='{url}.asc'>asc</a>)</td><td>{sha}</td></tr>"


OLD_PAGE = f"""<table>
{old_row("v1.12.7, on 2026-08-15", S3 + "/linux/x64/1.12/julia-1.12.7-linux-x86_64.tar.gz", SHA)}
{old_row("", S3 + "/mac/x64/1.12/julia-1.12.7-mac64.dmg", "b" * 64)}
{old_row("", S3 + "/mac/aarch64/1.12/julia-1.12.7-macaarch64.tar.gz", "c" * 64)}
{old_row("", S3 + "/winnt/x64/1.12/julia-1.12.7-win64.exe", "d" * 64)}
{old_row("", S3 + "/winnt/x64/1.12/julia-1.12.7-win64.zip", "e" * 64)}
{old_row("", S3 + "/winnt/x64/1.12/julia-1.12.7-win64.tar.gz", "f" * 64)}
{old_row("", S3 + "/freebsd/x64/1.12/julia-1.12.7-freebsd-x86_64.tar.gz", "1" * 64)}
{old_row("v1.13.0-rc4, on 2026-09-03", S3 + "/linux/x64/1.13/julia-1.13.0-rc4-linux-x86_64.tar.gz", "2" * 64)}
</table>"""

MANUAL_PAGE = f"""<h3>v1.13.1</h3>
<a href="{S3}/checksums/julia-1.13.1.sha256">sha</a>
<table><tr><td>Windows</td><td><a href="{S3}/winnt/x64/1.13/julia-1.13.1-win64.exe">installer</a>,
<a href="{S3}/winnt/x64/1.13/julia-1.13.1-win64.zip">portable</a></td></tr>
<tr><td>Linux</td><td><a href="{S3}/linux/x64/1.13/julia-1.13.1-linux-x86_64.tar.gz">glibc</a></td></tr></table>"""


def test_classify_only_stable_mirrored_archives():
    c = sync.classify
    assert c(S3 + "/linux/x64/1.12/julia-1.12.7-linux-x86_64.tar.gz") == {"version": "1.12.7", "key": "linux-x86_64", "ext": "tar.gz"}
    assert c(S3 + "/mac/aarch64/1.12/julia-1.12.7-macaarch64.tar.gz")["key"] == "macos-aarch64"
    assert c(S3 + "/winnt/x86/1.12/julia-1.12.7-win32.zip")["key"] == "windows-i686"
    for bad in ("julia-1.13.0-rc4-linux-x86_64.tar.gz", "julia-1.12.7-mac64.dmg", "julia-1.12.7-win64.exe",
                "julia-1.12.7-freebsd-x86_64.tar.gz", "julia-1.12.0-rc1-musl-x86_64.tar.gz", "julia-1.12.7-linux-x86_64.tar.gz.asc"):
        assert c(S3 + "/x/" + bad) is None, bad


def test_oldreleases_table_gives_sha_and_prefers_zip_on_windows():
    files = {(f["version"], f["key"], f["ext"]): f for f in sync.files_from_html("https://julialang.org/downloads/oldreleases/", OLD_PAGE)}
    assert files[("1.12.7", "linux-x86_64", "tar.gz")]["sha256"] == SHA  # asc link in the same row is not an archive
    assert files[("1.12.7", "macos-aarch64", "tar.gz")]["sha256"] == "c" * 64
    assert not any(v == "1.13.0" for v, _, _ in files)  # rc ignored
    assert not any(k == "macos-x86_64" for _, k, _ in files)  # only a .dmg there
    assert not any("freebsd" in f["url"] for f in files.values())
    assert sync.rank(files[("1.12.7", "windows-x86_64", "zip")]) < sync.rank(files[("1.12.7", "windows-x86_64", "tar.gz")])


def test_crawl_catalog_merges_pages_and_checksum_files(tmp_path, monkeypatch):
    pages = {"https://x/old": OLD_PAGE, "https://x/manual": MANUAL_PAGE}
    zip_name, tgz_name = "julia-1.13.1-win64.zip", "julia-1.13.1-linux-x86_64.tar.gz"
    sums = {
        "https://sums/julia-1.13.1.sha256": f"{'1' * 64}  {zip_name}\n{'2' * 64}  {tgz_name}\n",
        "https://sums/julia-1.13.1.md5": f"{'3' * 32}  {zip_name}\n{'4' * 32} *{tgz_name}\n",
    }
    monkeypatch.setattr(sync, "http_get", lambda url, retries=4: (pages.get(url) or sums[url]).encode())
    catalog = sync.crawl_catalog(["https://x/manual", "https://x/old"])
    assert set(catalog) == {"1.13.1", "1.12.7"}
    assert catalog["1.13.1"]["windows-x86_64"]["ext"] == "zip"  # the .exe installer was skipped
    files = catalog["1.13.1"]
    assert files["linux-x86_64"]["sha256"] is None  # manual page has no hashes ...
    sync.add_checksums("1.13.1", files, "https://sums")  # ... they come from upstream's checksum files
    assert files["linux-x86_64"]["sha256"] == "2" * 64 and files["linux-x86_64"]["md5"] == "4" * 32
    assert files["windows-x86_64"]["sha256"] == "1" * 64


def test_plan_filters_min_version_and_already_mirrored():
    catalog = {"1.9.4": {"linux-x86_64": {}}, "1.10.12": {"linux-x86_64": {}, "macos-aarch64": {}}, "1.13.1": {"linux-x86_64": {}}}
    lst = {"versions": {"1.10.12": {"files": {"linux-x86_64": {}}}}}
    todo = sync.plan(catalog, lst, "1.10.0", 0)
    assert [(v, sorted(f)) for v, f in todo] == [("1.13.1", ["linux-x86_64"]), ("1.10.12", ["macos-aarch64"])]
    assert len(sync.plan(catalog, lst, "1.10.0", 1)) == 1


# --------------------------------------------------------------------------- sync.py: list handling and sharding


def test_missing_remote_list_means_empty_but_other_errors_are_fatal(tmp_path: Path):
    assert sync.fetch_remote_list((tmp_path / "nope.json").as_uri()) is None  # 404-like: first run
    f = tmp_path / "julia-list.json"
    f.write_text(json.dumps({"versions": {"1.0.0": {"files": {}}}}))
    assert sync.load_list(tmp_path / "other.json", "me/r", f.as_uri())["versions"] == {"1.0.0": {"files": {}}}
    assert sync.load_list(tmp_path / "other.json", "me/r", (tmp_path / "nope.json").as_uri())["versions"] == {}
    import urllib.error

    import pytest

    def boom(url, retries=4):
        raise urllib.error.HTTPError(url, 503, "unavailable", None, None)

    original = sync.http_get
    sync.http_get = boom
    try:
        with pytest.raises(urllib.error.HTTPError):  # must NOT be treated as an empty list
            sync.fetch_remote_list("https://example.invalid/julia-list.json")
    finally:
        sync.http_get = original


def test_http_get_does_not_retry_client_errors(monkeypatch):
    import urllib.error

    import pytest

    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 404, "not found", None, None)

    monkeypatch.setattr(sync.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(sync.time, "sleep", lambda s: None)
    with pytest.raises(urllib.error.HTTPError):
        sync.http_get("https://example.invalid/x")
    assert len(calls) == 1


def test_files_overflow_into_the_next_mirror_release(monkeypatch):
    monkeypatch.setattr(sync, "SHARD_CAP", 2)
    base = "https://github.com/me/r/releases/download"
    lst = {"versions": {"1.0.0": {"files": {
        "linux-x86_64": {"url": f"{base}/__download__/a"}, "macos-aarch64": {"url": f"{base}/__download__/b"},
    }}}}
    assert sync.pick_tag(lst) == "__download_2__"
    lst["versions"]["1.0.1"] = {"files": {"linux-x86_64": {"url": f"{base}/__download_2__/c"}, "macos-aarch64": {"url": f"{base}/__download_2__/d"}}}
    assert sync.pick_tag(lst) == "__download_3__"
    sync.finalize(lst)
    assert lst["release_tags"] == ["__download__", "__download_2__"] and lst["latest"] == "1.0.1"
    assert sync.pick_tag({"versions": {}}) == "__download__"


def test_md5_sha_helper_agrees_with_hashlib(tmp_path: Path):
    f = tmp_path / "x"
    f.write_bytes(b"julia")
    sys.path.insert(0, str(ROOT))
    from julialang import manager as M

    assert M.hash_file(f) == (hashlib.sha256(b"julia").hexdigest(), hashlib.md5(b"julia").hexdigest())


def test_download_trusts_sha256_over_a_stale_md5(tmp_path: Path, capsys):
    src = tmp_path / "f.bin"
    src.write_bytes(b"julia")
    sha = hashlib.sha256(b"julia").hexdigest()
    sha_out, md5_out, size = sync.download(src.as_uri(), tmp_path / "out", sha, "0" * 32)
    assert (sha_out, md5_out, size) == (sha, hashlib.md5(b"julia").hexdigest(), 5)  # our own md5 is recorded
    assert "upstream md5" in capsys.readouterr().err
    import pytest

    monkey_sleep = sync.time.sleep
    sync.time.sleep = lambda s: None
    try:
        with pytest.raises(RuntimeError, match="sha256 mismatch"):
            sync.download(src.as_uri(), tmp_path / "out2", "f" * 64, None, retries=1)
    finally:
        sync.time.sleep = monkey_sleep
