# foldspace-cscs

Run **JupyterLab** or **VS Code** on a CSCS Alps compute node and use it from your own computer.

It is a CSCS plug-in for CINECA's [Foldspace](https://gitlab.hpc.cineca.it/interactive_computing/foldspace), which it installs and uses unmodified.

## Quick start

You need:

- [`cscs-key`](https://docs.cscs.ch/access/ssh/) on your PATH (`brew install eth-cscs/tap/cscs-key`);
- an SSH key at `~/.ssh/cscs-key`, for `cscs-key` to sign. `cscs-key` does not create it: if you have none, run `ssh-keygen -t ed25519 -f ~/.ssh/cscs-key` once;
- Python ≥ 3.9.

Install:

```bash
python3 -m venv ~/.local/share/foldspace-cscs
~/.local/share/foldspace-cscs/bin/pip install git+https://github.com/matteosecli/foldspace-cscs.git@stable
echo "alias foldspace-cscs='$HOME/.local/share/foldspace-cscs/bin/foldspace-cscs'" >> ~/.$(basename "$SHELL")rc
source ~/.$(basename "$SHELL")rc
```

The last two lines add an alias to your shell's startup file; you may have to adapt the file name to your shell (e.g. `~/.bash_profile` for bash on macOS).

Run:

```bash
foldspace-cscs eiger jupyter -A <project>
```

```bash
foldspace-cscs eiger vscode -A <project>
```

Open the link it prints. Press Enter when you are done; you are asked whether to cancel the job.

## Usage

```
foldspace-cscs [options] <cluster> <tool> [sbatch options]
```

- **Clusters:** `eiger`, `daint`.
- **Tools:**
  - `jupyter`: JupyterLab. Its launcher also has a VS Code (code-server) tile.
  - `vscode`: VS Code, in your browser or in VS Code desktop (see below).
- **sbatch options:** anything after the tool goes to `sbatch`. The defaults are 1 node for 1 hour, on the cluster's default partition.

### Examples

**Julia in VS Code**, with CSCS's Julia uenv, on the debug partition for 30 minutes:

```bash
foldspace-cscs eiger vscode -A <project> -p debug -t 00:30:00 --uenv julia/25.5:v1 --view juliaup
```

Terminals in VS Code then have `julia` and `juliaup`. For other software, `uenv image find` on the cluster lists the available uenvs.

**Julia notebooks in a container**, using the Jupyter project's [julia-notebook](https://quay.io/repository/jupyter/julia-notebook) image:

```bash
foldspace-cscs eiger jupyter -A <project> --environment quay.io/jupyter/julia-notebook
```

**A longer session in your project folder**, for 4 hours:

```bash
foldspace-cscs eiger jupyter -A <project> -t 04:00:00 -D '$SCRATCH/myproject'
```

The single quotes make `$SCRATCH` expand on the cluster, not on your computer.

### Good to know

- **uenvs** you ask for are pulled on the login node the first time; you do not need to pull them yourself.
- **Containers** ([CSCS Container Engine](https://docs.cscs.ch/software/container-engine/)): `--environment` takes one of your EDFs, as with `srun`, or an image name. For an image, foldspace-cscs writes the EDF `~/.edf/foldspace-cscs-<image>.toml`, which mounts `$SCRATCH`, `$STORE` and `$HOME`. Either way, the image is pulled on the login node the first time. With `jupyter`, the image must contain JupyterLab; with `vscode`, any image works. `--environment` and `--uenv` cannot be combined.
- **Reconnecting:** if a session is still running, the next run offers to reconnect to it instead of starting a new job.
- **Certificate:** your `cscs-key` certificate is reused while it is valid. If it is missing or expired, you are asked before a new one is signed (`cscs-key` limits signatures per day).

### VS Code desktop

The `vscode` tool also prints a `vscode://…` link. Click it, and VS Code desktop opens the same folder on the job's node, with the job's uenv or in its container.

- It needs VS Code's [Remote - SSH](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-ssh) extension.
- It works while `foldspace-cscs` is running.
- The first time, foldspace-cscs adds two settings to VS Code's `settings.json` (it prints them):
  - `remote.SSH.enableRemoteCommand: true`;
  - a `remote.SSH.serverInstallPath` entry for `foldspace-cscs-<cluster>`.

No Microsoft tunnel is used: the connection goes over SSH, like the browser one.

### Other commands and options

| Command | |
|---|---|
| `foldspace-cscs <cluster> login` | Only check the certificate (and renew it if expired). |
| `foldspace-cscs <cluster> setup` | Prepare a cluster ahead of time, and update the VS Code server there. Optional. |

| Option | |
|---|---|
| `--key PATH` | Key signed by `cscs-key`. Default: `~/.ssh/cscs-key`. |
| `--user NAME` | CSCS username. Default: read from the certificate. |
| `--headless` | If signing is needed, log in with a device code instead of a local browser. |
| `--renew` | Sign a new certificate even if the current one is valid. |
| `--yes` | Do not ask before signing. |
| `--jupyterlab-uenv UENV` | uenv providing JupyterLab. Default: `jupyterlab/v4.1.8:v3`. |
| `--update` | Update foldspace-cscs (see [Update and uninstall](#update-and-uninstall)). |

These options go before the cluster name, e.g. `foldspace-cscs --headless eiger vscode -A <project>`; everything after the tool goes to `sbatch`.

## Update and uninstall

Update to the latest release:

```bash
foldspace-cscs --update
```

It follows what you installed: `@stable` gets the latest release, `@main` the latest development version. It works for installs made with pip (as above), pipx or uv; an install pinned to a version tag stays as it is.

To install a specific version instead, put its tag in place of `stable` (e.g. `@v0.1.0`; see the [tags](https://github.com/matteosecli/foldspace-cscs/tags)). `@main` gives the latest development version.

Uninstall: delete `~/.local/share/foldspace-cscs` and the alias line in your shell's startup file. To also remove what it created, see the next section.

## What it changes

On your computer:

| Where | What |
|---|---|
| `~/.config/foldspace-cscs/` | Its own SSH config, known hosts, and an `ssh` wrapper. |
| `~/.ssh/config` | One `Include` line at the top, only while a `vscode` session runs. |
| VS Code `settings.json` | The two settings above. They are kept; remove the `foldspace-cscs-*` entries by hand if you uninstall. |

On the cluster:

| Where | What |
|---|---|
| `~/.foldspace-cscs/<cluster>/` | Job scripts, and job logs in `sessions/`. |
| `~/.local/<arch>/foldspace-cscs/` | VS Code server for the browser. |
| `~/.local/<arch>/share/vscode-web/` | Its extensions and settings. |
| `~/.vscode-server/<arch>/` | VS Code desktop's server (installed by VS Code). |
| `~/.edf/foldspace-cscs-*.toml` | EDFs written for `--environment <image>`. |
| `$SCRATCH/.edf_imagestore/` | Pulled container images (the Container Engine's own cache). |

`<arch>` is `x86_64`/`amd64` (eiger) or `aarch64`/`arm64` (daint): `$HOME` is shared between clusters with different CPUs, so binaries are kept apart.

## How it works

- **SSH:** every connection uses foldspace-cscs's own SSH config, with hosts named `foldspace-cscs-*` and the jump through `ela.cscs.ch`. Your `~/.ssh/config` is not read.
- **Job scripts:** written for CSCS. They use uenv instead of modules, and are uploaded to the cluster when they change.
- **Browser access:** Foldspace opens an SSH tunnel to the server's port on the compute node.
- **Containers:** the job script runs on the node and starts only the server in the container, as `srun --environment=…` (CSCS advises against `#SBATCH --environment`).
- **VS Code desktop:** VS Code connects to the node's own SSH server; CSCS lets you in while you have a job there. It then enters the job's uenv (`uenv start`) or container (`srun --environment=…`), because an SSH session does not get them otherwise.

## Development

```bash
git clone https://github.com/matteosecli/foldspace-cscs.git
cd foldspace-cscs
pip install -e .
```

To release: set the version in `pyproject.toml` and `src/foldspace_cscs/__init__.py`, then tag and push it (`git tag v0.2.0 && git push origin v0.2.0`). A workflow then moves the `stable` branch, which users install from, to the newest tag.

Code: `src/foldspace_cscs/` has the command (`cli.py`), certificates (`auth.py`), SSH (`ssh.py`), VS Code settings (`vscode_settings.py`), clusters (`clusters.py`), and the cluster-side scripts (`toolbox/`). `toolbox/tools/start_tool.sh` is copied unchanged from Foldspace.

## License

GPL-3.0-or-later, as Foldspace.
