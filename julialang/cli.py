"""`julialang` command: install, switch and remove the Julia versions that the `julia` command runs."""
from __future__ import annotations

import argparse
import sys

from . import _state as S
from . import manager as M

NEWEST_SHOWN = 12


def _spec(words: list[str] | None) -> str:
    """Words of the command line joined like pip does: `">=1.10" "<1.13"` -> '>=1.10,<1.13'. Empty = latest."""
    return ",".join(words) if words else "latest"


def _check_spec(spec: str) -> None:
    try:
        S.parse_spec(spec)
    except S.SpecError as e:
        S.die(str(e))


def _pick(spec: str, lst: dict) -> str:
    """Newest version on the mirror (for this platform) that satisfies the spec."""
    _check_spec(spec)
    v = S.resolve(spec, M.available_versions(lst))
    if not v:
        S.die(f"no Julia matching '{spec}' on the mirror for {M.platform_key()}")
    return v


def _tag(v: str, default: str | None) -> str:
    return "  (default)" if v == default else ""


def _make_default(version: str, was: str | None = None) -> None:
    S.set_default(version)
    print(f"Julia {version} is now the default" + (f" (was {was})" if was and was != version else ""))


def _replace(target: str, lst: dict, current: str | None) -> None:
    """Install `target`, make it the default and only then delete the previous default."""
    M.install(target, lst)
    _make_default(target, current)
    if current and current != target:
        try:
            M.uninstall(current)
            print(f"Removed Julia {current}")
        except SystemExit as e:  # the new Julia is already usable; do not fail the whole command
            print(f"could not remove Julia {current}: {e}", file=sys.stderr)


# --------------------------------------------------------------------------- commands


def cmd_status(a) -> int:
    key = M.platform_key()
    installed = S.sync_config()
    default = S.default_version()
    print(f"{'platform':<12}{key}")
    print(f"{'home':<12}{S.home()}")
    print(f"{'installed':<12}{', '.join(reversed(installed)) or '-'}")
    print(f"{'default':<12}{default or '-'}")
    lst = M.get_list(strict=False)
    latest = S.resolve("latest", M.available_versions(lst)) if lst else None
    print(f"{'latest':<12}{latest or 'unknown'}")
    if not installed:
        print("\nNo Julia installed yet: run `julialang install`.")
    elif latest and default and S.parse_version(latest) > S.parse_version(default):
        print(f"\nUpdate available: run `julialang upgrade` to switch from {default} to {latest}.")
    return 0


def cmd_list(a) -> int:
    default = S.default_version()
    installed = S.sync_config()
    print("Installed:")
    for v in reversed(installed):
        print(f"  {v}{_tag(v, default)}")
    if not installed:
        print("  (none)")
    if a.installed:
        return 0
    lst = M.get_list(strict=False)
    if lst is None:
        return 0
    avail = sorted(M.available_versions(lst), key=S.parse_version, reverse=True)
    print("\nOn the mirror:")
    for v in avail if a.all else avail[:NEWEST_SHOWN]:
        print(f"  {v}{'  [installed]' if v in installed else ''}")
    if not a.all and len(avail) > NEWEST_SHOWN:
        print(f"  ... {len(avail) - NEWEST_SHOWN} older versions (use --all)")
    return 0


def cmd_fetch(a) -> int:
    lst = M.get_list(fresh=True)
    avail = M.available_versions(lst)
    latest = S.resolve("latest", avail)
    print(f"Mirror list refreshed: {len(avail)} versions for {M.platform_key()}, latest {latest or '-'}"
          f" (list updated {lst.get('updated') or 'unknown'})")
    return 0


def cmd_latest(a) -> int:
    lst = M.get_list()
    print(S.resolve("latest", M.available_versions(lst)) or "-")
    return 0


def cmd_install(a) -> int:
    spec = _spec(a.spec)
    _check_spec(spec)
    lst = M.get_list(fresh=True)
    v = _pick(spec, lst)
    M.install(v, lst)
    S.sync_config()
    if a.no_default:
        print(f"Julia {v} installed")
    else:
        _make_default(v, S.default_version())
    return 0


def cmd_uninstall(a) -> int:
    spec = _spec(a.spec)
    _check_spec(spec)
    hits = S.matching(spec, S.sync_config())
    if not hits:
        S.die(f"no installed Julia matches '{spec}' (installed: {', '.join(S.installed_versions()) or 'none'})")
    if len(hits) > 1 and not a.yes:
        print("This will remove: " + ", ".join(reversed(hits)))
        if not sys.stdin.isatty():
            S.die("refusing to remove several versions without --yes")
        if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Aborted")
            return 1
    for v in hits:
        M.uninstall(v)
        print(f"Removed Julia {v}")
    return 0


def cmd_use(a) -> int:
    spec = _spec(a.spec)
    _check_spec(spec)
    have = S.sync_config()
    v = S.resolve(spec, have)
    if not v:
        S.die(f"no installed Julia matches '{spec}' (installed: {', '.join(have) or 'none'}); run `julialang install {spec}`")
    _make_default(v, S.default_version())
    return 0


def cmd_upgrade(a) -> int:
    spec = _spec(a.spec)
    _check_spec(spec)
    S.sync_config()
    lst = M.get_list(fresh=True)
    target, current = _pick(spec, lst), S.default_version()
    if current is None:
        M.install(target, lst)
        _make_default(target)
    elif target == current:
        print(f"Already up to date (Julia {current}).")
    elif S.parse_version(target) < S.parse_version(current):
        S.die(f"Julia {target} is older than the default {current}; use `julialang downgrade {spec}`")
    else:
        _replace(target, lst, current)
    return 0


def cmd_downgrade(a) -> int:
    spec = _spec(a.spec)
    _check_spec(spec)
    S.sync_config()
    current = S.default_version() or S.die("there is no default Julia to downgrade from; use `julialang install`")
    lst = M.get_list(fresh=True)
    target = _pick(spec, lst)
    if target == current:
        print(f"Julia {current} is already the default.")
    elif S.parse_version(target) > S.parse_version(current):
        S.die(f"Julia {target} is newer than the default {current}; use `julialang upgrade {spec}`")
    else:
        _replace(target, lst, current)
    return 0


def cmd_which(a) -> int:
    print(S.exe_in(S.resolve_root()))
    return 0


# --------------------------------------------------------------------------- argument parsing

SPEC_HELP = (
    "version spec: latest, 1.12 (newest 1.12.x), 1.12.4, ==, !=, >=, <=, >, <, ~= and comma-joined combinations "
    "(quote them: \">=1.10,<1.13\")"
)


def main(argv=None) -> int:
    from . import __version__

    p = argparse.ArgumentParser(
        prog="julialang",
        description="Install and switch the Julia versions that the `julia` command runs. No command: show status.",
        epilog="Julia lives in ~/.julialang (override with JULIALANG_HOME). "
               "JULIALANG_VERSION=<spec> overrides the default for one command.",
    )
    p.add_argument("--version", action="version", version=f"julialang {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")

    def add(name, func, help, *, spec=None, aliases=(), flags=()):
        sp = sub.add_parser(name, help=help, description=help, aliases=list(aliases))
        if spec:
            sp.add_argument("spec", nargs=spec, metavar="SPEC", help=SPEC_HELP)
        for flag, kw in flags:
            sp.add_argument(flag, **kw)
        sp.set_defaults(func=func)

    add("status", cmd_status, "show what is installed, the default and the latest version")
    add("list", cmd_list, "list installed versions and what the mirror offers", aliases=["ls"], flags=[
        ("--all", dict(action="store_true", help="show every mirrored version")),
        ("--installed", dict(action="store_true", help="only installed versions (no network)")),
    ])
    add("fetch", cmd_fetch, "refresh the cached list of mirrored versions")
    add("latest", cmd_latest, "print the newest version on the mirror")
    add("install", cmd_install, "install a version without removing others (default: latest) and make it the default",
        spec="*", flags=[("--no-default", dict(action="store_true", help="install only; keep the current default"))])
    add("uninstall", cmd_uninstall, "delete installed versions", spec="+", aliases=["remove", "rm"], flags=[
        ("--yes", dict(action="store_true", help="do not ask before removing several versions")),
        ("-y", dict(action="store_true", dest="yes", help=argparse.SUPPRESS)),
    ])
    add("use", cmd_use, "make an installed version the default", spec="+")
    add("upgrade", cmd_upgrade, "install a newer version (default: latest), make it the default, remove the old one",
        spec="*")
    add("downgrade", cmd_downgrade, "install an older version, make it the default, remove the newer one", spec="+")
    add("which", cmd_which, "print the path of the Julia executable that `julia` runs")

    args = p.parse_args(argv)
    if not args.cmd:
        return cmd_status(args)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
