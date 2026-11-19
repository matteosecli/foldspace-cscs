"""`foldspace-cscs`: run CINECA's Foldspace against CSCS Alps clusters."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

from rich.console import Console

from . import __version__, ssh, toolbox, vscode_settings
from .auth import DEFAULT_KEY, AuthError, ensure_certificate
from .clusters import CLUSTERS, JUPYTERLAB_UENV

console = Console(highlight=False)  # no automatic colouring of paths, numbers, dates

TOOLS = ("jupyter", "vscode")
ACTIONS = TOOLS + ("setup", "login")

EPILOG = """\
actions:
  jupyter      JupyterLab in a Slurm job (from CSCS's jupyterlab uenv); its launcher
               also offers VS Code through code-server (same uenv)
  vscode       VS Code in the browser (official web server, installed per architecture), or
               VS Code desktop over SSH (Remote-SSH) into the same job
  setup        install/refresh the remote toolbox, the jupyterlab uenv and the VS Code web server
  login        only check (or, if expired, renew) your CSCS SSH certificate

Everything after the action is passed to Foldspace and from there to sbatch,
e.g. -A/--account, -p/--partition, -t/--time, -D/--chdir, --uenv, --view.
--environment takes an EDF (as for srun) or a container image name.

examples:
  foldspace-cscs eiger jupyter -A <project> -t 01:00:00
  foldspace-cscs eiger jupyter -A <project> --uenv prgenv-gnu/24.11:v1 --view default
  foldspace-cscs eiger vscode -A <project> -p debug -t 00:30:00 --uenv julia/25.5:v1 --view juliaup
  foldspace-cscs eiger jupyter -A <project> --environment quay.io/jupyter/julia-notebook
"""


def parse(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="foldspace-cscs",
        description="Interactive Jupyter / VS Code sessions on CSCS Alps compute nodes, "
                    "tunnelled to your laptop (a CSCS plug-in for CINECA's Foldspace).",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--key", type=Path, default=DEFAULT_KEY,
                   help=f"private key signed by cscs-key (default: {DEFAULT_KEY})")
    p.add_argument("--user", help="CSCS username (default: read from the certificate)")
    p.add_argument("--headless", action="store_true",
                   help="if a new certificate is needed, use cscs-key's device flow (no local browser)")
    p.add_argument("--renew", action="store_true",
                   help="sign a new certificate even if the current one looks valid")
    p.add_argument("-y", "--yes", action="store_true", help="do not ask before signing a new certificate")
    p.add_argument("--jupyterlab-uenv", default=JUPYTERLAB_UENV,
                   help=f"uenv providing JupyterLab, mounted at /user-tools (default: {JUPYTERLAB_UENV})")
    p.add_argument("cluster", choices=sorted(CLUSTERS))
    p.add_argument("action", choices=ACTIONS)
    p.add_argument("passthrough", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return p.parse_args(argv)


def split_uenv_options(args: list[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    """Pull --uenv/--view/--environment out of the passthrough options."""
    rest, uenvs, views, envs = [], [], [], []
    i = 0
    while i < len(args):
        a = args[i]
        for name, bucket in (("--uenv", uenvs), ("--view", views), ("--environment", envs)):
            if a == name and i + 1 < len(args):
                bucket += [x for x in args[i + 1].split(",") if x]
                i += 2
                break
            if a.startswith(name + "="):
                bucket += [x for x in a.split("=", 1)[1].split(",") if x]
                i += 1
                break
        else:
            rest.append(a)
            i += 1
    return rest, uenvs, views, envs


def add_export(rest: list[str], assignment: str) -> list[str]:
    """Pass VAR=value to the job with sbatch --export, keeping the user's own --export."""
    out, found = [], False
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--export" and i + 1 < len(rest):
            a, i = f"--export={rest[i + 1]}", i + 1
        if a.startswith("--export="):
            found = True
            value = a.split("=", 1)[1]
            a = f"--export={value},{assignment}" if value not in ("NONE", "NIL") else f"--export={assignment}"
        out.append(a)
        i += 1
    return out if found else out + [f"--export=ALL,{assignment}"]


def uenv_name(spec: str) -> str | None:
    """'prgenv-gnu/24.11:v1[:/mnt]' -> 'prgenv-gnu'; squashfs paths -> None."""
    if spec.startswith("/"):
        return None
    return spec.split("/")[0].split(":")[0]


def compose_uenv(tool: str, uenvs: list[str], views: list[str], jupyterlab: str
                 ) -> tuple[list[str], list[str]]:
    """Decide the final --uenv/--view for sbatch.

    `vscode` brings its own server: only the user's uenv (if any) is mounted.
    `jupyter` needs the jupyterlab uenv at /user-tools (it provides jupyter and
    code-server). Without a user uenv its `jupyter` view is activated, so
    terminals get its Python too. With a user uenv (at /user-environment) only
    the user's views are activated: the servers are started by absolute path.
    With two images mounted, views must be namespaced ("name:view").
    """
    if tool == "vscode":
        return uenvs, views
    if not uenvs:
        return [jupyterlab], views or ["jupyter"]
    names = [n for n in (uenv_name(u) for u in uenvs) if n]
    ns_views = [v if ":" in v or len(names) != 1 else f"{names[0]}:{v}" for v in views]
    return uenvs + [jupyterlab], ns_views


def setup_vscode_desktop(cluster, home: str) -> None:
    """Set the VS Code settings desktop access needs (see vscode_settings)."""
    if vscode_settings.find() is None:
        return  # no VS Code desktop on this machine (or not in a standard place)
    if not vscode_settings.has_remote_ssh():
        console.print("[yellow]VS Code desktop needs the Remote - SSH extension:[/yellow] "
                      f"code --install-extension {vscode_settings.REMOTE_SSH}", highlight=False)
    changed, manual = vscode_settings.ensure(cluster.vscode_alias, home, cluster.arch)
    if changed:
        where = str(vscode_settings.find()).replace(str(Path.home()), "~", 1)
        console.print(f"[green]✓[/green] VS Code settings updated for desktop access ({where}):")
        for line in changed:
            console.print(f"  {line}", markup=False, highlight=False)
    if manual:
        console.print("[yellow]For VS Code desktop, please set in your VS Code settings.json:[/yellow]")
        for line in manual:
            console.print(f"  {line}", markup=False, highlight=False)


def _exit_on_signal(signum, frame):
    # Turn hangup/termination into a normal exit, so that clean-up still runs.
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None) -> None:
    a = parse(sys.argv[1:] if argv is None else argv)
    cluster = CLUSTERS[a.cluster]
    key = a.key.expanduser()
    try:
        # 1. Credentials: reuse a valid certificate, sign only if needed.
        info = ensure_certificate(key, headless=a.headless, assume_yes=a.yes, force=a.renew)
        user = a.user or (info.principals[0] if info.principals else None)
        if not user:
            raise AuthError("Cannot tell your CSCS username from the certificate; pass --user.")

        # 2. Private ssh config (+ wrapper used by Foldspace) and a connection test.
        ssh.write_config(user, key)
        ssh.cleanup_stale_include()
        test = ssh.run(cluster.alias, "true", timeout=90)
        if test.returncode != 0:
            err = test.stderr.decode(errors="replace").strip()
            console.print(f"[red]✗ Cannot connect to {cluster.name} as {user}:[/red]\n{err}")
            if "Permission denied" in err:
                console.print("[yellow]The certificate looks valid locally but was rejected. If it was revoked, "
                              f"run: foldspace-cscs {cluster.name} login --renew[/yellow]")
            sys.exit(1)
        console.print(f"[green]✓[/green] Connected to {cluster.name} as {user}")
        if a.action == "login":
            return

        # 3. Remote toolbox.
        home = toolbox.remote_home(cluster)
        tb = toolbox.sync(cluster, home, force=a.action == "setup")
        if a.action == "setup":
            toolbox.ensure_uenvs(cluster, [a.jupyterlab_uenv])
            toolbox.ensure_vscode_web(cluster, tb, update=True)
            console.print(f"[green]✓[/green] {cluster.name} is ready")
            return

        # 4. Software environment for the job.
        rest, uenvs, views, envs = split_uenv_options(a.passthrough)
        if envs:
            # Container: never `#SBATCH --environment` (see toolbox/tools/common.sh).
            if uenvs or views:
                raise RuntimeError("--environment (container) and --uenv/--view cannot be combined")
            if len(envs) > 1:
                raise RuntimeError("only one --environment can be given")
            edf = toolbox.container_environment(cluster, tb, envs[0])
            console.print(f"[green]✓[/green] Container environment: {edf}")
            rest = add_export(rest, f"FOLDSPACE_CSCS_EDF={edf}")
        else:
            uenvs, views = compose_uenv(a.action, uenvs, views, a.jupyterlab_uenv)
        toolbox.ensure_uenvs(cluster, uenvs)
        env_opts = ([f"--uenv={','.join(uenvs)}"] if uenvs else []) + \
                   ([f"--view={','.join(views)}"] if views else [])
        if a.action == "vscode":
            toolbox.ensure_vscode_web(cluster, tb)
            setup_vscode_desktop(cluster, home)

        # 5. Hand over to upstream Foldspace, which only sees our private ssh config.
        fs_argv = ["foldspace", "--host", cluster.alias, "--toolbox", tb, "--tool", a.action,
                   "--navigator", "nosocket", *env_opts, *rest]
        if "--debug" in rest:
            console.print(f"[grey50]$ {' '.join(fs_argv)}[/grey50]")
        os.environ["PATH"] = ssh.env_with_shim()["PATH"]
        sys.argv = fs_argv
        from foldspace.main import main as foldspace_main
        if a.action == "vscode":
            # VS Code desktop reads ~/.ssh/config: include our hosts while the session runs.
            for sig in (signal.SIGHUP, signal.SIGTERM):
                signal.signal(sig, _exit_on_signal)
            with ssh.vscode_include():
                foldspace_main()
        else:
            foldspace_main()
    except subprocess.TimeoutExpired as e:
        console.print(f"[red]✗ Timed out talking to {cluster.name}: {' '.join(map(str, e.cmd[-2:]))}[/red]")
        sys.exit(1)
    except (AuthError, RuntimeError) as e:
        console.print(f"[red]✗ {e}[/red]")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
