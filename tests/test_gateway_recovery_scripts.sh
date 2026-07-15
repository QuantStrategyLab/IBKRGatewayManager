#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
recover_script="$repo_dir/scripts/recover_ib_gateway_ready.sh"
activity_classifier="$repo_dir/scripts/classify_ib_gateway_activity.awk"
twofa_bot="$repo_dir/2fa_bot.py"
swap_script="$repo_dir/scripts/ensure_host_swap.sh"
daily_restart_script="$repo_dir/scripts/restart_ib_gateway_daily.sh"
health_watcher_script="$repo_dir/scripts/install_gateway_health_watcher.sh"
unit_helper_script="$repo_dir/scripts/ibkr_gateway_units.sh"

test -f "$recover_script"
test -f "$activity_classifier"
test -f "$swap_script"
test -f "$daily_restart_script"
test -f "$health_watcher_script"
test -f "$unit_helper_script"
test -x "$recover_script"
test -x "$swap_script"
test -x "$daily_restart_script"
test -x "$health_watcher_script"
test -x "$unit_helper_script"

grep -Fq 'IB_GATEWAY_RECOVERY_INITIAL_WAIT_SECONDS:-240' "$recover_script"
grep -Fq 'IB_GATEWAY_RECOVERY_RESTART_WAIT_SECONDS:-300' "$recover_script"
grep -Fq 'IB_GATEWAY_RECOVERY_RECREATE_WAIT_SECONDS:-600' "$recover_script"
grep -Fq 'IB_GATEWAY_RECOVERY_PROGRESS_WAIT_SECONDS:-420' "$recover_script"
grep -Fq 'IB_GATEWAY_RECOVERY_PROGRESS_EXTENSIONS:-2' "$recover_script"
grep -Fq 'IB_GATEWAY_RECOVERY_PROGRESS_WINDOW_SECONDS:-420' "$recover_script"
grep -Fq 'IB_GATEWAY_RECOVERY_LOG_PROBE_TIMEOUT_SECONDS:-10' "$recover_script"
grep -Fq 'Passed token authentication' "$recover_script"
grep -Fq 'Authentication completed' "$recover_script"
grep -Fq 'Connection reset by peer' "$recover_script"
grep -Fq 'Server disconnected' "$recover_script"
grep -Fq 'gateway_recent_activity()' "$recover_script"
grep -Fq 'Recent terminal IB gateway authentication failure detected' "$recover_script"
if grep -Fq 'Dismissing post-login dialog' "$recover_script" "$twofa_bot"; then
  echo 'Ambiguous dismiss-dialog text must not be treated as recovery progress' >&2
  exit 1
fi
grep -Fq 'Dismissing gateway dialog candidate' "$twofa_bot"
default_progress_regex="$(sed -n 's/^progress_regex="${IB_GATEWAY_RECOVERY_PROGRESS_REGEX:-\(.*\)}"$/\1/p' "$recover_script")"
default_terminal_regex="$(sed -n 's/^terminal_regex="${IB_GATEWAY_RECOVERY_TERMINAL_REGEX:-\(.*\)}"$/\1/p' "$recover_script")"
test -n "$default_progress_regex"
test -n "$default_terminal_regex"
if printf '%s\n' 'Dismissing gateway dialog candidate' | grep -Eq "$default_progress_regex"; then
  echo 'Gateway dialog dismissal must not match recovery progress' >&2
  exit 1
fi
printf '%s\n' 'Connection reset by peer' | grep -Eq "$default_terminal_regex"
printf '%s\n' 'Server disconnected' | grep -Eq "$default_terminal_regex"
printf '%s\n' 'IBC: Login attempt timed out' | grep -Eq "$default_terminal_regex"
newer_progress="$(printf '%s\n' \
  '2026-07-15 16:00:01 Server disconnected' \
  '2026-07-15 16:00:02 IBC: Login attempt' \
  | awk -v cutoff_timestamp='2026-07-15 16:00:00' -v progress_regex="$default_progress_regex" -v terminal_regex="$default_terminal_regex" -f "$activity_classifier")"
test "$newer_progress" = $'2026-07-15 16:00:02.000000000\tprogress'
newer_terminal="$(printf '%s\n' \
  '2026-07-15 16:00:01 IBC: Login attempt' \
  '2026-07-15 16:00:02 Server disconnected' \
  | awk -v cutoff_timestamp='2026-07-15 16:00:00' -v progress_regex="$default_progress_regex" -v terminal_regex="$default_terminal_regex" -f "$activity_classifier")"
test "$newer_terminal" = $'2026-07-15 16:00:02.000000000\tterminal'
same_second_progress="$(printf '%s\n' \
  '2026-07-15T16:00:02.100000000Z Server disconnected' \
  '2026-07-15T16:00:02.200000000Z IBC: Login attempt' \
  | awk -v cutoff_timestamp='2026-07-15 16:00:00' -v progress_regex="$default_progress_regex" -v terminal_regex="$default_terminal_regex" -f "$activity_classifier")"
test "$same_second_progress" = $'2026-07-15 16:00:02.200000000\tprogress'
untimestamped_terminal="$(printf '%s\n' \
  '2026-07-15 15:59:59 IBC: Login attempt' \
  'Server disconnected' \
  | awk -v cutoff_timestamp='2026-07-15 16:00:00' -v progress_regex="$default_progress_regex" -v terminal_regex="$default_terminal_regex" -f "$activity_classifier")"
test -z "$untimestamped_terminal"
grep -Fq 'gateway_recent_activity_from_docker_logs()' "$recover_script"
grep -Fq 'gateway_recent_activity_from_file_logs()' "$recover_script"
grep -Fq 'docker logs --timestamps --since' "$recover_script"
grep -Fq 'timeout "${log_probe_timeout_seconds}" docker logs' "$recover_script"
grep -Fq 'timeout "${log_probe_timeout_seconds}" docker exec' "$recover_script"
grep -Fq '/home/ibgateway/Jts/launcher.log' "$recover_script"
grep -Fq '/home/ibgateway/2fa.log' "$recover_script"
grep -Fq 'cutoff_timestamp="$(date -u -d "@$((now - progress_window_seconds))" "+%Y-%m-%d %H:%M:%S")"' "$recover_script"
grep -Fq 'activity="$(gateway_recent_activity)"' "$recover_script"
grep -Fq 'wait_for_ready_with_progress()' "$recover_script"
grep -Fq 'Recent IB gateway login/config progress detected' "$recover_script"
grep -Fq 'case "${activity}" in' "$recover_script"
grep -Fq 'IB_GATEWAY_RECOVERY_LOCK_FILE:-/var/lock/ib_gateway_recovery.lock' "$recover_script"
grep -Fq 'IB_GATEWAY_RECOVERY_LOCK_WAIT_SECONDS:-900' "$recover_script"
grep -Fq 'flock -n 9' "$recover_script"
grep -Fq 'flock -w "${lock_wait_seconds}" 9' "$recover_script"
grep -Fq 'compose_service_name="${IB_GATEWAY_COMPOSE_SERVICE_NAME:-ib-gateway}"' "$recover_script"
grep -Fq 'docker compose restart "${compose_service_name}"' "$recover_script"
grep -Fq 'docker compose up -d --force-recreate --no-build "${compose_service_name}"' "$recover_script"
grep -Fq 'IB_GATEWAY_READY_TIMEOUT_SECONDS="${timeout_seconds}"' "$recover_script"
grep -Fq 'CONTAINER_NAME="${container_name}" bash "${script_dir}/ensure_2fa_bot_running.sh"' "$recover_script"
ensure_count="$(grep -c 'ensure_2fa_bot_running' "$recover_script")"
test "$ensure_count" -ge 4

grep -Fq 'swap_size_mib="${IB_GATEWAY_SWAP_SIZE_MIB:-2048}"' "$swap_script"
grep -Fq 'fallocate -l "${swap_size_mib}M" "${swap_file}"' "$swap_script"
grep -Fq 'swapon "${swap_file}"' "$swap_script"
grep -Fq 'grep -Fq "${swap_file} none swap sw 0 0" /etc/fstab' "$swap_script"
grep -Fq 'printf '\''%s none swap sw 0 0\n'\'' "${swap_file}" >>/etc/fstab' "$swap_script"

grep -Fq 'compose_service_name="${IB_GATEWAY_COMPOSE_SERVICE_NAME:-ib-gateway}"' "$daily_restart_script"
grep -Fq 'docker compose restart "${compose_service_name}"' "$daily_restart_script"
grep -Fq 'recover_ib_gateway_ready.sh" "${gateway_mode}"' "$daily_restart_script"

grep -Fq 'resolve_ibkr_gateway_unit_names "$container_name" "$unit_suffix"' "$health_watcher_script"
grep -Fq '$IBKR_GATEWAY_HEALTHCHECK_SERVICE' "$health_watcher_script"
grep -Fq '$IBKR_GATEWAY_HEALTHCHECK_TIMER' "$health_watcher_script"
grep -Fq '$IBKR_GATEWAY_DAILY_RESTART_SERVICE' "$health_watcher_script"
grep -Fq '$IBKR_GATEWAY_DAILY_RESTART_TIMER' "$health_watcher_script"
grep -Fq 'IB_GATEWAY_HEALTHCHECK_INTERVAL_SECONDS:-300' "$health_watcher_script"
grep -Fq 'IB_GATEWAY_DAILY_RESTART_ON_CALENDAR:-*-*-* 10:30:00 UTC' "$health_watcher_script"
grep -Fq 'compose_service_name="${IB_GATEWAY_COMPOSE_SERVICE_NAME:-ib-gateway}"' "$health_watcher_script"
grep -Fq 'gateway_mode="${1:-${IB_GATEWAY_MODE:-paper}}"' "$health_watcher_script"
grep -Fq 'compose_file="${COMPOSE_FILE:-docker-compose.yml}"' "$health_watcher_script"
grep -Fq 'Environment=IB_GATEWAY_COMPOSE_SERVICE_NAME=$compose_service_name' "$health_watcher_script"
grep -Fq 'Environment=COMPOSE_FILE=$compose_file' "$health_watcher_script"
grep -Fq 'Environment=IB_GATEWAY_RECOVERY_LOCK_FILE=$recovery_lock_file' "$health_watcher_script"
grep -Fq 'Environment=IB_GATEWAY_RECOVERY_LOCK_WAIT_SECONDS=0' "$health_watcher_script"
grep -Fq 'OnActiveSec=$health_interval_seconds' "$health_watcher_script"
grep -Fq 'Persistent=false' "$health_watcher_script"
! grep -Fq 'OnBootSec=5min' "$health_watcher_script"
grep -Fq 'enable --now "$IBKR_GATEWAY_HEALTHCHECK_TIMER"' "$health_watcher_script"
grep -Fq 'enable --now "$IBKR_GATEWAY_DAILY_RESTART_TIMER"' "$health_watcher_script"
! grep -Fq 'start ibkr-gateway-healthcheck.service' "$health_watcher_script"

grep -Fq 'resolve_ibkr_gateway_unit_suffix()' "$unit_helper_script"
grep -Fq 'IBKR_2FA_BOT_SERVICE="ibkr-2fa-bot${unit_infix}.service"' "$unit_helper_script"
