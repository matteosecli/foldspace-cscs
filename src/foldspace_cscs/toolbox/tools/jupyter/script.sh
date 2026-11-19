#!/usr/bin/env bash
# Started in the background by start_tool.sh
# in_job_environment: as is, or in the job's container (see common.sh)
exec bash -c 'in_job_environment "$@"' _ "$jupyter_bin" lab --config="$config_file"
