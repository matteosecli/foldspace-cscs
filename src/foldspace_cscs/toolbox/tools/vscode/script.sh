#!/usr/bin/env bash
# Started in the background by start_tool.sh. Running this server means
# accepting the VS Code Server license: https://aka.ms/vscode-server-license
# in_job_environment: as is, or in the job's container (see common.sh)
exec bash -c 'in_job_environment "$@"' _ "$vscode_bin" \
  --host 0.0.0.0 \
  --port "$port" \
  --connection-token-file "$vscode_token_file" \
  --accept-server-license-terms \
  --server-data-dir "$vscode_data" \
  --user-data-dir "$vscode_data/user-data" \
  --extensions-dir "$vscode_data/extensions" \
  --telemetry-level off \
  --default-folder "$PWD"
