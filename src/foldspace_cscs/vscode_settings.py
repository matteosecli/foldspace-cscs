"""The VS Code (desktop) settings that VS Code desktop access needs, set for the user.

Remote-SSH needs two things for the `vscode` tool's desktop access:

- `remote.SSH.enableRemoteCommand: true`, because the job's uenv is entered
  through the ssh config's RemoteCommand (it is off by default);
- a per-architecture `remote.SSH.serverInstallPath` for our host alias:
  $HOME is shared between x86_64 and aarch64 clusters, and Remote-SSH would
  otherwise put both architectures' servers in the same ~/.vscode-server.

settings.json is JSON with comments, owned by the user and watched by VS Code,
so it is edited textually and minimally: one line is inserted, nothing else
changes. The result is parsed before writing. If anything looks unusual
(unparsable file, a setting explicitly set to another value), nothing is
written and the user gets the line to add by hand instead.
"""

from __future__ import annotations

import copy
import json
import os
import re
import stat
from pathlib import Path

CANDIDATES = [
    Path.home() / "Library" / "Application Support" / "Code" / "User" / "settings.json",  # macOS
    Path.home() / ".config" / "Code" / "User" / "settings.json",                          # Linux
    Path(os.environ.get("APPDATA", "/nonexistent")) / "Code" / "User" / "settings.json",  # Windows
]
ARCH_DIR = {"x86_64": "amd64", "aarch64": "arm64"}


REMOTE_SSH = "ms-vscode-remote.remote-ssh"


def has_remote_ssh() -> bool:
    """Is the Remote - SSH extension installed (in the default extensions dir)?"""
    ext_dir = Path(os.environ.get("VSCODE_EXTENSIONS", Path.home() / ".vscode" / "extensions"))
    return any(ext_dir.glob(f"{REMOTE_SSH}-[0-9]*"))


def find() -> Path | None:
    return next((f for f in CANDIDATES if f.is_file()), None)


def parse(text: str) -> dict:
    """Parse JSONC: drop comments outside strings and trailing commas."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
            out.append(ch)
        elif text.startswith("//", i):
            i = text.find("\n", i)
            i = n if i < 0 else i
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        else:
            out.append(ch)
        i += 1
    clean = re.sub(r",(\s*[}\]])", r"\1", "".join(out))
    return json.loads(clean or "{}")


def _insert_in_object(text: str, key: str, entry: str) -> str | None:
    """Insert `entry` as the first member of the object value of `key`."""
    m = re.search(rf'^([ \t]*)"{re.escape(key)}"\s*:\s*\{{', text, re.M)
    if not m:
        return None
    outer = m.group(1)
    empty = re.match(r"\s*\}", text[m.end():])
    if empty:
        return text[: m.end()] + f"\n{outer}    {entry}\n{outer}}}" + text[m.end() + empty.end():]
    return text[: m.end()] + f"\n{outer}    {entry}," + text[m.end():]


def _insert_top_level(text: str, entry: str) -> str | None:
    """Insert `entry` as the first member of the top-level object.

    (First rather than last: the last member may be followed by a comment.)
    """
    m = re.search(r"^\s*\{", text)
    if not m:
        return None
    empty = re.match(r"\s*\}", text[m.end():])
    if empty:
        return text[: m.end()] + f"\n    {entry}\n}}" + text[m.end() + empty.end():]
    return text[: m.end()] + f"\n    {entry}," + text[m.end():]


def ensure(alias: str, home: str, arch: str) -> tuple[list[str], list[str]]:
    """Make the settings right. Returns (what was changed, lines to add by hand)."""
    path = find()
    if path is None:
        return [], []  # VS Code desktop not installed (or not in a standard place)
    install_path = f"{home}/.vscode-server/{ARCH_DIR.get(arch, arch)}/"
    path = path.resolve()  # a symlinked settings.json (dotfiles) is edited in place
    text = path.read_text()
    try:
        current = parse(text)
    except ValueError:
        current = None
    wanted = [
        ("remote.SSH.enableRemoteCommand", None, True, '"remote.SSH.enableRemoteCommand": true'),
        ("remote.SSH.serverInstallPath", alias, install_path,
         f'"remote.SSH.serverInstallPath": {{"{alias}": "{install_path}"}}'),
    ]
    if current is None or not isinstance(current, dict):
        return [], [w[3] for w in wanted]

    changed, manual, new = [], [], text
    expected = copy.deepcopy(current)
    for key, sub, value, by_hand in wanted:
        have = current.get(key)
        if sub is None:
            if have == value:
                continue
            if have is not None:  # explicitly set otherwise: the user's choice
                manual.append(by_hand)
                continue
            new = _insert_top_level(new, f'"{key}": {json.dumps(value)}')
            expected[key] = value
        else:
            if isinstance(have, dict) and sub in have:
                if have[sub] != value:
                    manual.append(by_hand)  # customised for our alias: leave it
                continue
            if have is None:
                new = _insert_top_level(new, f'"{key}": {{\n        "{sub}": {json.dumps(value)}\n    }}')
            elif isinstance(have, dict):
                new = _insert_in_object(new, key, f'"{sub}": {json.dumps(value)}')
            else:
                new = None
            expected.setdefault(key, {})[sub] = value
        if new is None:
            return [], [w[3] for w in wanted]
        changed.append(by_hand)

    if changed:
        try:
            ok = parse(new) == expected  # exactly our additions, nothing else
        except ValueError:
            ok = False
        if not ok:
            return [], [w[3] for w in wanted]
        tmp = path.with_name(path.name + ".foldspace-cscs.tmp")
        tmp.write_text(new)
        tmp.chmod(stat.S_IMODE(path.stat().st_mode))
        os.replace(tmp, path)
    return changed, manual
