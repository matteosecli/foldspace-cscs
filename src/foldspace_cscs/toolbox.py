"""Render the remote toolbox for one cluster and keep it in sync.

The toolbox lives in the user's (shared) $HOME, one copy per cluster:

    $HOME/.foldspace-cscs/<cluster>/            Foldspace user_dir (sessions, history)
    $HOME/.foldspace-cscs/<cluster>/toolbox/     scripts (architecture-neutral)

Software comes from uenv images. The only binary we install, Microsoft's
VS Code web server, goes per architecture:

    $HOME/.local/$(uname -m)/foldspace-cscs/vscode-web/<commit>
"""

from __future__ import annotations

import hashlib
import io
import shlex
import subprocess
import tarfile
from importlib import resources

from rich.console import Console

from . import ssh
from .clusters import STATUS_PAGE, Cluster

console = Console(highlight=False)  # no automatic colouring of paths, numbers, dates

TEMPLATE_SUFFIX = ".in"


def remote_home(c: Cluster) -> str:
    out = ssh.run(c.alias, 'printf %s "$HOME"', timeout=90)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"Cannot reach {c.name}: {out.stderr.decode(errors='replace').strip()}")
    return out.stdout.decode().strip()


def paths(c: Cluster, home: str) -> dict[str, str]:
    base = f"{home}/.foldspace-cscs/{c.name}"
    return {"user_dir": base, "toolbox": f"{base}/toolbox"}


def motd(c: Cluster) -> str:
    """Welcome box, in the same layout as CINECA's toolboxes (title centred)."""
    lines = [
        "",
        "You can find the User Guide here:",
        f"   {c.docs}",
        "You can check the status of the system here:",
        f"   {STATUS_PAGE}",
    ]
    title = f"Welcome to {c.pretty}!"
    pad = max(0, (max(map(len, lines)) - len(title)) // 2)
    links = {c.docs, STATUS_PAGE}
    styled = [f"[bold blue]{' ' * pad}{title}[/bold blue]"] + [
        f"   [dodger_blue1]{l.strip()}[/dodger_blue1]" if l.strip() in links else l for l in lines]
    return "\n".join(f"  {l}".rstrip() for l in styled)


def render(c: Cluster, home: str) -> dict[str, bytes]:
    """Return {relative path: content} with placeholders filled in."""
    p = paths(c, home)
    subst = {
        "@@CLUSTER@@": c.name,
        "@@CLUSTER_PRETTY@@": c.pretty,
        "@@MOTD@@": motd(c),
        "@@USER_DIR@@": p["user_dir"],
        "@@TOOLBOX_DIR@@": p["toolbox"],
    }
    root = resources.files("foldspace_cscs").joinpath("toolbox")
    files: dict[str, bytes] = {}

    def walk(node, rel=""):
        for child in sorted(node.iterdir(), key=lambda x: x.name):
            name = f"{rel}{child.name}"
            if child.is_dir():
                walk(child, name + "/")
            elif not child.name.startswith("."):
                data = child.read_bytes()
                if name.endswith(TEMPLATE_SUFFIX):
                    text = data.decode()
                    for k, v in subst.items():
                        text = text.replace(k, v)
                    data, name = text.encode(), name[: -len(TEMPLATE_SUFFIX)]
                files[name] = data

    walk(root)
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode() + b"\0" + files[name] + b"\0")
    files["VERSION"] = (digest.hexdigest()[:16] + "\n").encode()
    return files


def _tarball(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name.endswith(".sh") else 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def sync(c: Cluster, home: str, force: bool = False) -> str:
    """Upload the toolbox if the remote copy differs. Returns its remote path."""
    files = render(c, home)
    dest = paths(c, home)["toolbox"]
    q = shlex.quote(dest)
    current = ssh.run(c.alias, f"cat {q}/VERSION 2>/dev/null", timeout=90).stdout.decode().strip()
    if current == files["VERSION"].decode().strip() and not force:
        console.print(f"[green]✓[/green] Toolbox on {c.name} is up to date")
        return dest
    console.print(f"[cyan]→[/cyan] Installing toolbox on {c.name} in {dest}")
    script = (
        "set -e; umask 022; "
        f"rm -rf {q}.new && mkdir -p {q}.new && tar -xzf - -C {q}.new && "
        f"rm -rf {q}.old && {{ [ -d {q} ] && mv {q} {q}.old || true; }} && mv {q}.new {q} && rm -rf {q}.old && "
        f"mkdir -p {shlex.quote(paths(c, home)['user_dir'])}/sessions"
    )
    out = ssh.run(c.alias, script, input=_tarball(files), timeout=180)
    if out.returncode != 0:
        raise RuntimeError(f"Toolbox upload failed: {out.stderr.decode(errors='replace').strip()}")
    return dest


def ensure_uenvs(c: Cluster, images: list[str]) -> None:
    """Pull the uenv images on the login node if they are not there yet."""
    for img in images:
        if img.startswith("/"):  # a squashfs path: nothing to pull
            continue
        label = img.split(":/")[0] if ":/" in img else img  # strip an explicit mount point
        q = shlex.quote(label)
        check = ssh.run(c.alias, f"uenv image inspect {q} >/dev/null 2>&1", timeout=120)
        if check.returncode == 0:
            continue
        console.print(f"[cyan]→[/cyan] Pulling uenv {label} on {c.name} (first use only)")
        pulled = ssh.run(c.alias, f"uenv image pull {q}", capture=False, timeout=1800)
        if pulled.returncode != 0:
            raise RuntimeError(f"Could not pull uenv {label}; check `uenv image find` on {c.name}")


def container_environment(c: Cluster, toolbox_dir: str, value: str) -> str:
    """Resolve --environment (an EDF, or an image to make an EDF for); return the EDF path."""
    script = f"bash {shlex.quote(toolbox_dir)}/bin/container-environment.sh {shlex.quote(value)}"
    # stderr (pull progress, errors) goes straight to the terminal
    out = subprocess.run([ssh.real_ssh(), "-F", str(ssh.SSH_CONFIG), c.alias, script],
                         stdout=subprocess.PIPE, timeout=3600)
    edf = out.stdout.decode().strip().splitlines()[-1:] if out.stdout else []
    if out.returncode != 0 or not edf or not edf[0].startswith("/"):
        raise RuntimeError(f"Cannot use --environment {value} on {c.name}")
    return edf[0]


def ensure_vscode_web(c: Cluster, toolbox_dir: str, update: bool = False) -> None:
    """Install Microsoft's VS Code web server for this cluster's architecture.

    Done on the login node, so jobs start immediately. With update=True (setup)
    the latest stable release is installed if newer than the current one.
    """
    script = f"{shlex.quote(toolbox_dir)}/bin/install-vscode-web.sh latest"
    if not update and ssh.run(c.alias, f"{script} --check", timeout=90).returncode == 0:
        return
    console.print(f"[cyan]→[/cyan] Checking/installing the VS Code web server for {c.arch} on {c.name}")
    out = ssh.run(c.alias, script, capture=False, timeout=1800)
    if out.returncode != 0:
        raise RuntimeError("VS Code web server installation failed")

