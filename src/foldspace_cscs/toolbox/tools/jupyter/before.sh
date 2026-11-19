# Sourced by start_tool.sh. Must set: port, password.
trap 'echo "SIGTERM received, cleaning up"; clean_up 143' SIGTERM

# In a container, JupyterLab must come with the image (found on its PATH).
# Otherwise it comes from CSCS's jupyterlab uenv, always mounted at
# /user-tools, called by absolute path so the user's own views stay first.
if [[ -n $FOLDSPACE_CSCS_EDF ]]; then
  export jupyter_bin=jupyter
  if ! in_job_environment sh -c 'command -v jupyter' >/dev/null 2>&1; then
    echo "ERROR: the container has no 'jupyter' command: use an image with JupyterLab, or the vscode tool" >&2
    clean_up 1
  fi
else
  export jupyter_bin=/user-tools/env/jupyter/bin/jupyter
  if [[ ! -x $jupyter_bin ]]; then
    echo "ERROR: $jupyter_bin not found: the jupyterlab uenv is not mounted at /user-tools" >&2
    clean_up 1
  fi
fi

port=$(find_port "$host" 20000 60000)
password=$(create_password 32)  # short enough for the URL not to wrap in the panel

# Kernels and other Jupyter data may be architecture specific: search
# ~/.local/<arch>/share/jupyter first, then the usual (shared) locations.
export JUPYTER_PATH=$HOME/.local/$arch/share/jupyter${JUPYTER_PATH:+:$JUPYTER_PATH}

# JupyterLab's launcher offers VS Code through jupyter-vscode-proxy, which
# starts `code-server` from PATH. When the user's own uenv views are active
# the jupyter view is not, so expose just that one binary.
if [[ -z $FOLDSPACE_CSCS_EDF ]]; then
  mkdir -p "$session_files_dir/bin"
  ln -sf /user-tools/env/jupyter/bin/code-server "$session_files_dir/bin/code-server"
  export PATH=$session_files_dir/bin:$PATH
fi
export CODE_EXTENSIONSDIR=$HOME/.local/$arch/share/code-server/extensions

export config_file=$session_files_dir/jupyter_server_config.py
(
umask 077
cat > "$config_file" <<EOT
import os
c.ServerApp.ip = '0.0.0.0'
c.ServerApp.port = $port
c.ServerApp.port_retries = 0
c.ServerApp.open_browser = False
c.IdentityProvider.token = '$password'
# the job's working directory: \$HOME, or sbatch -D/--chdir
c.ServerApp.root_dir = os.getcwd()
c.FileContentsManager.delete_to_trash = False
EOT
)
