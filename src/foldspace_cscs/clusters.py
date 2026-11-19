"""Static description of the CSCS clusters this plug-in knows about."""

from dataclasses import dataclass

JUMP_HOST = "ela.cscs.ch"
STATUS_PAGE = "https://status.cscs.ch"

# CSCS's jupyterlab uenv (mounted at /user-tools) provides both JupyterLab and
# code-server (used by jupyter-vscode-proxy). Override with --jupyterlab-uenv.
JUPYTERLAB_UENV = "jupyterlab/v4.1.8:v3"


@dataclass(frozen=True)
class Cluster:
    name: str          # short name, used in paths and host aliases
    pretty: str        # name shown by Foldspace
    host: str          # login node address (reached through JUMP_HOST)
    arch: str          # `uname -m` of login and compute nodes
    docs: str          # user guide

    @property
    def alias(self) -> str:
        """Host alias of the login node in the plug-in's private ssh config."""
        return f"foldspace-cscs-{self.name}-login"

    @property
    def vscode_alias(self) -> str:
        """Host alias for VS Code desktop (Remote-SSH) into the running vscode job.

        The short name is the user-facing one: it appears in the vscode://
        link, which must fit on one line of Foldspace's 72-column panel.
        """
        return f"foldspace-cscs-{self.name}"


CLUSTERS = {
    "eiger": Cluster("eiger", "Eiger", "eiger.alps.cscs.ch", "x86_64",
                     "https://docs.cscs.ch/clusters/eiger/"),
    "daint": Cluster("daint", "Daint", "daint.alps.cscs.ch", "aarch64",
                     "https://docs.cscs.ch/clusters/daint/"),
}
