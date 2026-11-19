# Copied unchanged from CINECA Foldspace 1.0.3 (toolboxes/leonardo/tools/start_tool.sh, GPLv3):
# https://gitlab.hpc.cineca.it/interactive_computing/foldspace
#
# All the credits for this script goes to the Open Ondemand project (https://openondemand.org/)
# from which its original version comes from.

# Export useful connection variables
export host
export port

# Generate a connection yaml file with given parameters
create_yml () {
  echo "Generating connection YAML file..."
  (
    umask 077
    echo -e "node: $host\nport: $port\ntoken: $password\ntool_info: |\n  ${tool_info//$'\n'/$'\n  '}\njob_info: |\n  ${job_info//$'\n'/$'\n  '}" > "$session_files_dir/connection.yml"
  )
}

# Cleanliness is next to Godliness
clean_up () {
  echo "Cleaning up..."
  [[ -e "$tool_dir/clean.sh" ]] && source "$tool_dir/clean.sh"
  [[ ${tool_pid} ]] && pkill -P ${tool_pid} || :
  pkill -P $$
  exit ${1:-0}
}

# Source in all the helper functions
source_helpers () {
  # Generate random integer in range [$1..$2]
  random_number () {
    shuf -i ${1}-${2} -n 1
  }
  export -f random_number

  port_used_python() {
    python -c "import socket; socket.socket().connect(('$1',$2))" >/dev/null 2>&1
  }

  port_used_python3() {
    python3 -c "import socket; socket.socket().connect(('$1',$2))" >/dev/null 2>&1
  }

  port_used_nc(){
    nc -w 2 "$1" "$2" < /dev/null > /dev/null 2>&1
  }

  port_used_lsof(){
    lsof -i :"$2" >/dev/null 2>&1
  }

  port_used_bash(){
    local bash_supported=$(strings /bin/bash 2>/dev/null | grep tcp)
    if [ "$bash_supported" == "/dev/tcp/*/*" ]; then
      (: < /dev/tcp/$1/$2) >/dev/null 2>&1
    else
      return 127
    fi
  }

  # Check if port $1 is in use
  port_used () {
    local port="${1#*:}"
    local node=$((expr "${1}" : '\(.*\):' || echo "localhost") | awk 'END{print $NF}')
    local port_strategies=(port_used_nc port_used_lsof port_used_bash port_used_python port_used_python3)

    for strategy in ${port_strategies[@]};
    do
      $strategy $node $port
      status=$?
      if [[ "$status" == "0" ]] || [[ "$status" == "1" ]]; then
        return $status
      fi
    done

    return 127
  }
  export -f port_used

  # Find available port in range [$2..$3] for node $1
  # Default node: localhost
  # Default port range: [2000..65535]
  # returns error code (0: success, 1: failed)
  # On success, the chosen port is echoed on stdout.
  find_port () {
    local node="${1:-localhost}"
    local min_port=${2:-2000}
    local max_port=${3:-65535}
    local port_range=($(shuf -i ${min_port}-${max_port}))
    local retries=1 # number of retries over the port range if first attempt fails
    for ((attempt=0; attempt<=$retries; attempt++)); do
      for port in "${port_range[@]}"; do
        if port_used "${node}:${port}"; then
continue
        fi
        echo "${port}"
        return 0 # success
      done
    done

    echo "error: failed to find available port in range ${min_port}..${max_port}" >&2
    return 1 # failure
  }
  export -f find_port

  # Wait $2 seconds until port $1 is in use
  # Default: wait 30 seconds
  wait_until_port_used () {
    local port="${1}"
    local time="${2:-30}"
    for ((i=1; i<=time*2; i++)); do
      port_used "${port}"
      port_status=$?
      if [ "$port_status" == "0" ]; then
        return 0
      elif [ "$port_status" == "127" ]; then
         echo "commands to find port were either not found or inaccessible."
         echo "command options are lsof, nc, bash's /dev/tcp, or python (or python3) with socket lib."
         return 127
      fi
      sleep 0.5
    done
    return 1
  }
  export -f wait_until_port_used

  # Generate random alphanumeric token with $1 (default: 8) characters
  create_password () (
    set +o pipefail # ensure pipefail disabled, `head` closing stdin causes SIGPIPE
    tr -cd 'a-zA-Z0-9' < /dev/urandom 2> /dev/null | head -c${1:-8}
  )
  export -f create_password
}
export -f source_helpers

source_helpers

# Store the hostname of the current node
host=$(hostname -s)

# Run preliminary configurations for the incoming server
[[ -e "$tool_dir/before.sh" ]] && source "$tool_dir/before.sh"

# Start the tool
echo "Script starting..."
"$tool_dir/script.sh" &
tool_pid=$!

# Run post-tool operations
[[ -e "$tool_dir/after.sh" ]] && source "$tool_dir/after.sh"

# Create the connection yaml file
create_yml

# Wait for tool process to finish
wait ${tool_pid} || clean_up 1

# Exit cleanly
clean_up
