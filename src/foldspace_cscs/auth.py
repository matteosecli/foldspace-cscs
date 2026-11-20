"""CSCS SSH certificate handling (cscs-key).

Policy: an existing certificate is always preferred. A new one is requested
(`cscs-key sign`, which counts against the daily signing limit) only when
there is no certificate or it has expired, and only after asking.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from InquirerPy import inquirer
from rich.console import Console

console = Console(highlight=False)  # no automatic colouring of paths, numbers, dates

DEFAULT_KEY = Path.home() / ".ssh" / "cscs-key"
WARN_BELOW = timedelta(hours=1)


class AuthError(RuntimeError):
    pass


@dataclass
class CertInfo:
    valid_from: datetime | None
    valid_to: datetime | None  # None means "forever"
    principals: list[str]

    def remaining(self) -> timedelta | None:
        return None if self.valid_to is None else self.valid_to - datetime.now()

    def is_valid(self) -> bool:
        now = datetime.now()
        if self.valid_from and now < self.valid_from:
            return False
        return self.valid_to is None or now < self.valid_to


def cert_path(key: Path) -> Path:
    return Path(f"{key}-cert.pub")


def _short(path: Path) -> str:
    """Path with $HOME shown as ~ (keeps messages on one line)."""
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def read_cert(key: Path) -> CertInfo | None:
    """Parse `ssh-keygen -L` for the certificate next to `key`."""
    cert = cert_path(key)
    if not cert.exists():
        return None
    out = subprocess.run(["ssh-keygen", "-L", "-f", str(cert)], capture_output=True, text=True)
    if out.returncode != 0:
        return None
    text = out.stdout
    m = re.search(r"Valid:\s+from\s+(\S+)\s+to\s+(\S+)", text)
    valid_from = valid_to = None
    if m:
        valid_from = datetime.fromisoformat(m.group(1))
        valid_to = None if m.group(2) == "forever" else datetime.fromisoformat(m.group(2))
    elif "Valid: forever" not in text:
        return None
    principals: list[str] = []
    pm = re.search(r"Principals:[ \t]*\n((?:[ \t]{9,}\S.*\n)+)", text)
    if pm:
        principals = [p.strip() for p in pm.group(1).splitlines() if p.strip()]
    return CertInfo(valid_from, valid_to, principals)


def _fmt(td: timedelta) -> str:
    minutes = int(td.total_seconds() // 60)
    return f"{minutes // 60} h {minutes % 60:02d} min"


def describe(info: CertInfo | None, key: Path) -> str:
    if info is None:
        return f"no CSCS certificate found at {_short(cert_path(key))}"
    if not info.is_valid():
        return f"CSCS certificate expired on {info.valid_to:%Y-%m-%d %H:%M}"
    rem = info.remaining()
    return "CSCS certificate valid forever" if rem is None else \
        f"CSCS certificate valid until {info.valid_to:%Y-%m-%d %H:%M} ({_fmt(rem)} left)"


def ensure_in_agent(key: Path, info: CertInfo) -> None:
    """Load key+certificate into ssh-agent if not there yet (best effort).

    Not required for the plug-in itself (its ssh config points at the key
    files), but it mirrors the usual CSCS workflow and avoids repeated
    passphrase prompts for protected keys.
    """
    if not shutil.which("ssh-add"):
        return
    listed = subprocess.run(["ssh-add", "-l"], capture_output=True, text=True)
    if listed.returncode == 2:  # no agent running
        return
    fp = subprocess.run(["ssh-keygen", "-lf", str(cert_path(key))], capture_output=True, text=True)
    fingerprint = fp.stdout.split()[1] if fp.returncode == 0 and fp.stdout.split() else None
    if fingerprint and any(fingerprint in line and "CERT" in line for line in listed.stdout.splitlines()):
        return
    rem = info.remaining()
    cmd = ["ssh-add"]
    if rem is not None:
        cmd += ["-t", str(max(60, int(rem.total_seconds())))]
    subprocess.run(cmd + [str(key)])


def check_signing_prerequisites(key: Path) -> None:
    """Fail early, before asking to sign, if signing cannot work.

    cscs-key is not a Python package: it comes from Homebrew (macOS) or as a
    binary (Linux), and only has to be on PATH. It signs an existing public
    key (<key>.pub); it does not create one.
    """
    if not shutil.which("cscs-key"):
        raise AuthError("`cscs-key` was not found on your PATH. Install it (brew install "
                        "eth-cscs/tap/cscs-key, or see https://docs.cscs.ch/access/ssh/) and try again.")
    pub = Path(f"{key}.pub")
    if not key.exists():
        raise AuthError(f"No SSH key at {_short(key)}. Create one with: ssh-keygen -t ed25519 -f {_short(key)} "
                        "(or pass --key)")
    if not pub.exists():
        raise AuthError(f"No public key at {_short(pub)}, which cscs-key needs. Recreate it with: "
                        f"ssh-keygen -y -f {_short(key)} > {_short(pub)}")


def sign_new(key: Path, headless: bool) -> None:
    """The usual CSCS login: sign, show the registered keys, load into the agent."""
    cmd = ["cscs-key", "sign", "-d", "1d", "-f", str(key)]
    if headless:
        cmd.append("--headless")
    if subprocess.run(cmd).returncode != 0:
        raise AuthError("`cscs-key sign` failed")
    console.print("[grey50]Your keys registered with CSCS:[/grey50]")
    subprocess.run(["cscs-key", "list"])
    if shutil.which("ssh-add"):
        subprocess.run(["ssh-add", "-t", "1d", str(key)])


def confirm_signing() -> bool:
    """Ask before signing (it uses one of the limited daily signatures).

    An arrow-key menu, like Foldspace's own questions; Enter picks the
    highlighted choice, which is to sign. Without a terminal to ask in,
    the answer is no (use --yes).
    """
    if not sys.stdin.isatty():
        return False
    options = ["Sign a new 24 h certificate now (uses one of your daily cscs-key signatures)",
               "Abort"]
    choice = inquirer.select(message="What do you want to do?", choices=options,
                             default=options[0], qmark="", amark="").execute()
    return choice == options[0]


def ensure_certificate(key: Path, *, headless: bool = False, assume_yes: bool = False,
                       force: bool = False) -> CertInfo:
    """Return a valid certificate, signing a new one only if really needed."""
    info = read_cert(key)
    if info and info.is_valid() and not force:
        console.print(f"[green]✓[/green] {describe(info, key)}")
        rem = info.remaining()
        if rem is not None and rem < WARN_BELOW:
            console.print("[yellow]  It expires soon: running jobs keep going, but you will have to sign a new "
                          "certificate to reconnect after it expires.[/yellow]")
        ensure_in_agent(key, info)
        return info

    reason = "you asked for a new certificate" if force else describe(info, key)
    console.print(f"[yellow]![/yellow] {reason}.")
    check_signing_prerequisites(key)
    if not assume_yes and not confirm_signing():
        raise AuthError("No valid CSCS certificate; aborting. "
                        "(Run again and choose to sign, or pass --yes to sign without asking.)")
    sign_new(key, headless)
    info = read_cert(key)
    if not (info and info.is_valid()):
        raise AuthError(f"Still no valid certificate at {cert_path(key)} after signing.")
    console.print(f"[green]✓[/green] {describe(info, key)}")
    return info
