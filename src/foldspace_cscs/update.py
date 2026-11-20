"""`foldspace-cscs --update`: update this installation from where it came from.

The installer is recognised from files it leaves in the environment, and
the source from the metadata pip records for every install from a URL
(PEP 610, `direct_url.json`): the git URL, the requested branch or tag
(`stable`, `main`, `v0.2.0`, ...) and the installed commit.

- pip (a plain venv, the README's way): `python -m pip install --upgrade git+URL@REF`
- pipx (`pipx_metadata.json` in the environment): `pipx upgrade`
- uv (`uv-receipt.toml` in the environment): `uv tool upgrade`

pipx and uv re-install from the original requirement, so the branch is
kept. Installs pinned to a tag, or made from a local folder or a wheel,
are not updated: there is nothing to follow, so the user is told what to do.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console

DIST = "foldspace-cscs"
REPO = "https://github.com/matteosecli/foldspace-cscs.git"
console = Console(highlight=False)

# Reads the installed version and source in a fresh interpreter: after an
# update, the metadata of this (still running) process is out of date.
_PROBE = (
    "import json; from importlib import metadata as m; d = m.distribution('foldspace-cscs'); "
    "u = d.read_text('direct_url.json'); "
    "print(json.dumps({'version': d.version, 'direct_url': json.loads(u) if u else None}))"
)


class UpdateError(RuntimeError):
    pass


def installer(prefix: Path | None = None) -> str:
    prefix = Path(sys.prefix if prefix is None else prefix)
    if (prefix / "pipx_metadata.json").is_file():
        return "pipx"
    if (prefix / "uv-receipt.toml").is_file():
        return "uv"
    return "pip"


def installed() -> dict:
    """{'version': ..., 'direct_url': {...} or None}, read in a fresh interpreter."""
    out = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True, text=True)
    if out.returncode != 0:
        raise UpdateError(f"cannot read the installed version: {out.stderr.strip()}")
    return json.loads(out.stdout)


def source(direct_url: dict | None) -> tuple[str, str | None, str | None]:
    """(git URL, requested branch/tag or None, installed commit) of a git install."""
    if not direct_url or direct_url.get("vcs_info", {}).get("vcs") != "git":
        raise UpdateError(
            "this installation was not made from the git repository (e.g. from a local folder "
            "or a wheel), so it cannot follow a branch. Reinstall it from GitHub once:\n"
            f"  {sys.executable} -m pip install --force-reinstall --no-deps git+{REPO}@stable")
    vcs = direct_url["vcs_info"]
    return direct_url["url"], vcs.get("requested_revision"), vcs.get("commit_id")


def remote_commit(url: str, ref: str | None) -> tuple[str | None, bool]:
    """(commit the branch points to now, whether `ref` is a tag) from `git ls-remote`."""
    if not shutil.which("git"):
        raise UpdateError("git is needed to check for updates (it was needed to install, too)")
    out = subprocess.run(["git", "ls-remote", url], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise UpdateError(f"cannot reach {url}: {out.stderr.strip()}")
    refs = dict(reversed(line.split("\t")) for line in out.stdout.splitlines() if "\t" in line)
    if ref is None:
        return refs.get("HEAD"), False
    if f"refs/tags/{ref}" in refs:
        return refs.get(f"refs/tags/{ref}^{{}}", refs[f"refs/tags/{ref}"]), True
    if f"refs/heads/{ref}" in refs:
        return refs[f"refs/heads/{ref}"], False
    if re.fullmatch(r"[0-9a-f]{7,40}", ref):  # installed from a bare commit
        return ref, True
    raise UpdateError(f"'{ref}' no longer exists in {url}")


def _run(cmd: list[str]) -> None:
    shown = ["python" if c == sys.executable else c for c in cmd]
    console.print(f"$ {' '.join(shown)}", style="grey50", markup=False)
    if subprocess.run(cmd).returncode != 0:
        raise UpdateError(f"`{' '.join(cmd[:3])} …` failed (see above)")


def _short(commit: str | None) -> str:
    return (commit or "?")[:7]


def update() -> int:
    """Update to the newest commit of the installed branch. Returns an exit code."""
    try:
        how = installer()
        before = installed()
        url, ref, commit = source(before["direct_url"])
        channel = ref or "the default branch"
        latest, pinned = remote_commit(url, ref)
        if pinned:
            console.print(f"foldspace-cscs {before['version']} is pinned to [bold]{ref}[/bold], so there is "
                          "nothing to follow. To get the latest release, reinstall from @stable:\n"
                          + _switch_hint(how, url))
            return 0
        if latest == commit:
            console.print(f"[green]✓[/green] foldspace-cscs {before['version']} is up to date "
                          f"({channel}, {_short(commit)}).")
            return 0
        console.print(f"Updating foldspace-cscs {before['version']} ({channel}, {_short(commit)} → "
                      f"{_short(latest)}) with {how}:")
        if how == "pip":
            if subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True).returncode:
                raise UpdateError(f"this environment has no pip; reinstall foldspace-cscs, see {REPO}")
            pip = [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check"]
            spec = f"git+{url}" + (f"@{ref}" if ref else "")
            _run(pip + ["--upgrade", spec])
            # pip keeps an installed package whose version number did not
            # change (e.g. two commits on main): then replace it explicitly,
            # and let pip add any dependency the new commit needs.
            if installed()["direct_url"]["vcs_info"].get("commit_id") != latest:
                _run(pip + ["--force-reinstall", "--no-deps", spec])
                _run(pip + [spec])
        else:
            if not shutil.which(how):
                raise UpdateError(f"foldspace-cscs was installed with {how}, but `{how}` is not on your PATH")
            _run(["pipx", "upgrade", DIST] if how == "pipx" else ["uv", "tool", "upgrade", DIST])
            # Same as for pip: both may keep the old commit when the version
            # number did not change, so then force a re-install.
            if installed()["direct_url"]["vcs_info"].get("commit_id") != latest:
                _run(["pipx", "reinstall", DIST] if how == "pipx"
                     else ["uv", "tool", "upgrade", "--reinstall", DIST])
        after = installed()
        new = after["direct_url"]["vcs_info"].get("commit_id")
        if new != latest:
            raise UpdateError(f"the update ran, but the installed commit is {_short(new)}, "
                              f"not {_short(latest)}")
        console.print(f"[green]✓[/green] foldspace-cscs {before['version']} → {after['version']} "
                      f"({channel}, {_short(new)}). The job scripts on the clusters are updated on "
                      "your next run.")
        return 0
    except (UpdateError, subprocess.TimeoutExpired) as e:
        console.print(f"[red]✗ {e}[/red]")
        return 1


def _switch_hint(how: str, url: str) -> str:
    if how == "pipx":
        return f"  pipx install --force git+{url}@stable"
    if how == "uv":
        return f"  uv tool install --force git+{url}@stable"
    return f"  {sys.executable} -m pip install --force-reinstall git+{url}@stable"
