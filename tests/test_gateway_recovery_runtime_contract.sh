#!/bin/bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
recover_script="$repo_dir/scripts/recover_ib_gateway_ready.sh"

run_scenario() {
  local scenario="$1"
  local tmp_dir output

  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "$tmp_dir"' RETURN
  cat >"$tmp_dir/docker" <<'SH'
#!/bin/bash
set -euo pipefail

state_dir="${MOCK_STATE_DIR:?}"
next_count() {
  local name="$1" value=0
  if [ -f "$state_dir/$name" ]; then
    value="$(cat "$state_dir/$name")"
  fi
  value=$((value + 1))
  printf '%s' "$value" >"$state_dir/$name"
  printf '%s\n' "$value"
}

case "$1" in
  compose)
    exit 0
    ;;
  inspect)
    count="$(next_count inspect)"
    if [ "${MOCK_SCENARIO}" = drift ] && [ "$count" -ge 4 ]; then
      printf '%s\n' 'new-container 2026-07-15T16:39:00.000000000Z'
    else
      printf '%s\n' 'new-container 2026-07-15T16:38:00.000000000Z'
    fi
    ;;
  logs)
    count="$(next_count logs)"
    if [ "${MOCK_SCENARIO}" = terminal ] && [ "$count" -ge 2 ]; then
      printf '%s\n' '2026-07-15T16:38:02.000000000Z IBC closing because login has not completed'
    else
      printf '%s\n' '2026-07-15T16:38:01.000000000Z IBC: Login attempt'
    fi
    ;;
  exec)
    exit 0
    ;;
  *)
    exit 1
    ;;
esac
SH
  cat >"$tmp_dir/bash" <<'SH'
#!/bin/bash
set -euo pipefail

case "$1" in
  */wait_for_ib_gateway_ready.sh)
    count_file="${MOCK_STATE_DIR:?}/wait"
    count=0
    [ -f "$count_file" ] && count="$(cat "$count_file")"
    count=$((count + 1))
    printf '%s' "$count" >"$count_file"
    if [ "$count" -le 2 ]; then
      exit 1
    fi
    exit 0
    ;;
  */ensure_2fa_bot_running.sh)
    exit 0
    ;;
  *)
    exec /bin/bash "$@"
    ;;
esac
SH
  cat >"$tmp_dir/flock" <<'SH'
#!/bin/bash
exit 0
SH
  chmod +x "$tmp_dir/docker" "$tmp_dir/bash" "$tmp_dir/flock"

  output="$(PATH="$tmp_dir:$PATH" \
    MOCK_SCENARIO="$scenario" \
    MOCK_STATE_DIR="$tmp_dir" \
    IB_GATEWAY_RECOVERY_LOCK_FILE="$tmp_dir/recovery.lock" \
    IB_GATEWAY_RECOVERY_INITIAL_WAIT_SECONDS=0 \
    IB_GATEWAY_RECOVERY_RESTART_WAIT_SECONDS=0 \
    IB_GATEWAY_RECOVERY_RECREATE_WAIT_SECONDS=0 \
    IB_GATEWAY_RECOVERY_PROGRESS_WAIT_SECONDS=0 \
    IB_GATEWAY_RECOVERY_PROGRESS_EXTENSIONS=2 \
    bash "$recover_script" paper 2>&1)"
  printf '%s\n' "$output"

  if [ "$scenario" = terminal ]; then
    grep -Fq 'Terminal authentication event detected in the current recovery epoch' <<<"$output"
    test "$(cat "$tmp_dir/wait")" -eq 3
    test "$(cat "$tmp_dir/logs")" -eq 2
  else
    grep -Fq 'Container identity/StartedAt changed; discarding snapshot for a new epoch assessment.' <<<"$output"
    test "$(cat "$tmp_dir/wait")" -eq 3
    test "$(cat "$tmp_dir/logs")" -eq 1
  fi
}

run_scenario terminal >/dev/null
run_scenario drift >/dev/null
