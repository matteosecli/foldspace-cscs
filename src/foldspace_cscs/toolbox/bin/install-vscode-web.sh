#!/bin/bash
# Install Microsoft's VS Code web server (the build behind `code serve-web`)
# for the architecture of the current node. Approach adapted from codespeck
# (https://github.com/matteosecli/codespeck): download the server ahead of
# time, so jobs start instantly and all server options are available.
#
# Usage: install-vscode-web.sh [COMMIT|latest] [--check]
#   latest    (default) resolve the latest stable release
#   --check   exit 0 if some version is installed and selected, 1 otherwise
set -euo pipefail
want=${1:-latest}
mode=${2:-install}

arch=$(uname -m)
case $arch in
  x86_64)  platform=linux-x64 ;;
  aarch64) platform=linux-arm64 ;;
  *) echo "unsupported architecture: $arch" >&2; exit 2 ;;
esac
prefix=$HOME/.local/$arch/foldspace-cscs/vscode-web

if [[ $mode == --check ]]; then
  [[ -x $prefix/current/bin/code-server ]]
  exit
fi

if [[ $want == latest ]]; then
  commit=$(curl -fsSL "https://update.code.visualstudio.com/api/latest/$platform/stable" |
           sed -n 's/.*"version":"\([0-9a-f]\{40\}\)".*/\1/p')
  [[ -n $commit ]] || { echo "could not resolve the latest VS Code release" >&2; exit 1; }
else
  commit=$want
fi

if [[ ! -x $prefix/$commit/bin/code-server ]]; then
  mkdir -p "$prefix"
  tmp=$(mktemp -d "$prefix/.download.XXXXXX")
  trap 'rm -rf "$tmp"' EXIT
  url=https://update.code.visualstudio.com/commit:$commit/server-$platform-web/stable
  echo "Downloading VS Code web server $commit ($platform)"
  curl -fsSL "$url" | tar -xz -C "$tmp" --strip-components 1
  rm -rf "${prefix:?}/$commit"
  mv "$tmp" "$prefix/$commit"
  trap - EXIT
  chmod 755 "$prefix/$commit"
fi
ln -sfn "$commit" "$prefix/current"
ver=$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$prefix/current/package.json" 2>/dev/null | head -n1)
echo "VS Code web server ${ver:-?} ($commit) ready in $prefix/$commit"
