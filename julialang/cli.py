"""`julialang` command: see what is installed, what is new, and switch the default Julia."""
from __future__ import annotations

import argparse
import sys

from . import manager as M

NEWEST_SHOWN = 12


def _remote() -> dict:
    try:
        return M.fetch_list()
    except Exception as e:  # network, DNS, bad JSON ...
        M.die(f"cannot read the mirror list ({M.list_url()}): {e}")


def _tags(v: str, active: str | None) -> str:
    tags = []
    if v == active:
        tags.append("default")
    if v == M.bundled_version():
        tags.append("bundled")
    return f"  ({', '.join(tags)})" if tags else ""


def cmd_status(a) -> int:
    key = M.platform_key()
    active, bundled = M.active_version(), M.bundled_version()
    local = M.local_versions()
    print(f"{'platform':<18}{key}")
    print(f"{'bundled':<18}{bundled or '-'}")
    print(f"{'installed':<18}{', '.join(local) or '-'}")
    print(f"{'default':<18}{active or '-'}")
    try:
        lst = M.fetch_list()
        latest = M.match("latest", M.available_versions(lst, key))
    except Exception as e:
        print(f"{'latest':<18}unknown (could not reach the mirror: {e})")
        return 0
    print(f"{'latest':<18}{latest or '-'}")
    if latest and (active is None or M.parse(latest) > M.parse(active)):
        print(f"\nUpdate available: run `julialang upgrade` to install {latest} and make it the default.")
    return 0


def cmd_list(a) -> int:
    key = M.platform_key()
    active = M.active_version()
    print("Installed:")
    for v in sorted(M.local_versions(), key=M.parse, reverse=True):
        print(f"  {v}{_tags(v, active)}")
    if not M.local_versions():
        print("  (none)")
    print("\nOn the mirror:")
    avail = sorted(M.available_versions(_remote(), key), key=M.parse, reverse=True)
    for v in avail if a.all else avail[:NEWEST_SHOWN]:
        mark = "  [installed]" if v in M.local_versions() else ""
        print(f"  {v}{mark}")
    if not a.all and len(avail) > NEWEST_SHOWN:
        print(f"  ... {len(avail) - NEWEST_SHOWN} older versions (use --all)")
    return 0


def _remote_version(spec: str, lst: dict) -> str:
    v = M.match(spec, M.available_versions(lst, M.platform_key()))
    if not v:
        M.die(f"no Julia matching '{spec}' on the mirror for {M.platform_key()}")
    return v


def cmd_install(a) -> int:
    lst = _remote()
    v = _remote_version(a.version, lst)
    M.install(v, lst)
    if a.use:
        M.set_default(v)
        print(f"Julia {v} is now the default")
    return 0


def cmd_use(a) -> int:
    if a.version == "bundled":
        v = M.bundled_version() or M.die("this install has no bundled Julia")
    else:
        v = None if a.version in ("latest", "stable") else M.match(a.version, M.local_versions())
        if v is None:  # not available locally: fetch it
            lst = _remote()
            v = _remote_version(a.version, lst)
            if v not in M.local_versions():
                M.install(v, lst)
    M.set_default(v)
    print(f"Julia {v} is now the default")
    return 0


def cmd_upgrade(a) -> int:
    lst = _remote()
    target = _remote_version(a.version or "latest", lst)
    current = M.active_version()
    if not a.version and current and M.parse(current) >= M.parse(target):
        print(f"Already up to date (Julia {current}).")
        return 0
    if target not in M.local_versions():
        M.install(target, lst)
    M.set_default(target)
    print(f"Julia {target} is now the default" + (f" (was {current})" if current else ""))
    return 0


def cmd_downgrade(a) -> int:
    if a.version:
        return cmd_use(a)
    current = M.active_version() or M.die("no default Julia to downgrade from")
    lst = _remote()
    older = [v for v in M.available_versions(lst, M.platform_key()) if M.parse(v) < M.parse(current)]
    if not older:
        M.die(f"nothing older than {current} on the mirror")
    target = older[-1]
    if target not in M.local_versions():
        M.install(target, lst)
    M.set_default(target)
    print(f"Julia {target} is now the default (was {current})")
    return 0


def cmd_remove(a) -> int:
    M.remove(a.version)
    print(f"Removed Julia {a.version}")
    return 0


def cmd_which(a) -> int:
    print(M.exe_in(M.resolve_root()))
    return 0


def cmd_latest(a) -> int:
    v = M.match("latest", M.available_versions(_remote(), M.platform_key()))
    print(v or "-")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="julialang",
        description="Manage the Julia that the `julia` command runs. No argument: show status.",
    )
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")

    def add(name, func, help, *args, aliases=()):
        sp = sub.add_parser(name, help=help, aliases=list(aliases))
        for flags, kw in args:
            sp.add_argument(*flags, **kw)
        sp.set_defaults(func=func)

    ver = lambda **kw: (("version",), kw)  # noqa: E731
    add("status", cmd_status, "show bundled / installed / default / latest")
    add("list", cmd_list, "list installed versions and what the mirror offers",
        (("--all",), dict(action="store_true", help="show every mirrored version")), aliases=["ls"])
    add("latest", cmd_latest, "print the newest version on the mirror")
    add("install", cmd_install, "install a version (e.g. latest, 1.12, 1.12.2)",
        ver(), (("--use",), dict(action="store_true", help="also make it the default")))
    add("use", cmd_use, "make a version the default (installs it if needed; 'bundled' = the wheel's copy)", ver())
    add("upgrade", cmd_upgrade, "install the newest Julia (or a given one) and make it the default",
        (("version",), dict(nargs="?")))
    add("downgrade", cmd_downgrade, "default to the next older version (or a given one)",
        (("version",), dict(nargs="?")))
    add("remove", cmd_remove, "delete an installed version", ver(), aliases=["rm"])
    add("which", cmd_which, "print the path of the Julia executable that `julia` runs")

    args = p.parse_args(argv)
    if not args.cmd:
        return cmd_status(args)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
