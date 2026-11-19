# Sourced by start_tool.sh after the server is started in the background:
# give it a moment to listen before Foldspace opens the tunnel.
echo "Waiting for the server to listen on $host:$port ..."
for ((i = 0; i < 120; i++)); do          # up to 60 s (a container takes a few seconds more)
  port_used "$host:$port" && break
  kill -0 "$tool_pid" 2>/dev/null || break
  sleep 0.5
done
if ! kill -0 "$tool_pid" 2>/dev/null; then
  # The server died: show why in Foldspace's "Tool details" instead of a dead link.
  log=${session_files_dir%-files}-output.log
  # the specific lines, without Slurm/pyxis's generic follow-ups
  why=$(grep -iE 'error|not found|denied|failed|no such' "$log" \
        | grep -viE 'spank|terminating|task [0-9]+: exited|start failed with|exited too soon|printing engine log|start container' \
        | tail -n 3 | sed -E 's/^\[[0-9T:.-]+\] //; s/^error: pyxis: +//; s/\[/\\[/g')
  tool_info="[red]The server failed to start.[/red]

$why

The full log is on the cluster: $log"
elif ! port_used "$host:$port"; then
  echo "WARNING: the server is not listening yet after 60 s; continuing anyway" >&2
fi
