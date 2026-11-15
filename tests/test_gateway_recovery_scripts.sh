#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
recover_script="$repo_dir/scripts/recover_ib_gateway_ready.sh"
swap_script="$repo_dir/scripts/ensure_host_swap.sh"
daily_restart_script="$repo_dir/scripts/restart_ib_gateway_daily.sh"
health_watcher_script="$repo_dir/scripts/install_gateway_health_watcher.sh"
adaptive_monitor_script="$repo_dir/scripts/monitor_ib_gateway_ready.sh"
unit_helper_script="$repo_dir/scripts/ibkr_gateway_units.sh"

test -f "$recover_script"
test -f "$swap_script"
test -f "$daily_restart_script"
test -f "$health_watcher_script"
test -f "$adaptive_monitor_script"
test -f "$unit_helper_script"
test -x "$recover_script"
test -x "$swap_script"
test -x "$daily_restart_script"
test -x "$health_watcher_script"
test -x "$adaptive_monitor_script"
test -x "$unit_helper_script"

grep -Fq 'IB_GATEWAY_RECOVERY_INITIAL_WAIT_SECONDS:-240' "$recover_script"
grep -Fq 'IB_GATEWAY_RECOVERY_RESTART_WAIT_SECONDS:-300' "$recover_script"
grep -Fq 'IB_GATEWAY_RECOVERY_RECREATE_WAIT_SECONDS:-600' "$recover_script"
grep -Fq 'IB_GATEWAY_RECOVERY_PROGRESS_WAIT_SECONDS:-420' "$recover_script"
grep -Fq 'IB_GATEWAY_RECOVERY_PROGRESS_EXTENSIONS:-2' "$recover_script"
grep -Fq 'IB_GATEWAY_RECOVERY_PROGRESS_WINDOW_SECONDS:-420' "$recover_script"
grep -Fq 'IB_GATEWAY_TRANSIENT_DIALOG_RESTART_ATTEMPTS:-1' "$recover_script"
grep -Fq 'IB_GATEWAY_TRANSIENT_DIALOG_RESTART_WAIT_SECONDS:-180' "$recover_script"
grep -Fq 'Passed token authentication' "$recover_script"
grep -Fq 'Authentication completed' "$recover_script"
grep -Fq 'gateway_recently_progressing()' "$recover_script"
grep -Fq 'gateway_recently_progressing_from_docker_logs()' "$recover_script"
grep -Fq 'gateway_recently_progressing_from_file_logs()' "$recover_script"
grep -Fq '/home/ibgateway/Jts/launcher.log' "$recover_script"
grep -Fq '/home/ibgateway/2fa.log' "$recover_script"
grep -Fq 'stat -c %Y "${log_path}"' "$recover_script"
grep -Fq 'cutoff_timestamp="$(date -u -d "@$((now - progress_window_seconds))" "+%Y-%m-%d %H:%M:%S")"' "$recover_script"
grep -Fq 'substr($0, 1, 19) >= cutoff_timestamp && $0 ~ progress_regex' "$recover_script"
grep -Fq 'wait_for_ready_with_progress()' "$recover_script"
grep -Fq 'recover_from_gateway_ui_blocker()' "$recover_script"
grep -Fq 'restarting without acknowledging the dialog' "$recover_script"
grep -Fq 'return 3' "$recover_script"
grep -Fq 'Recent IB gateway login/config progress detected' "$recover_script"
grep -Fq 'IB_GATEWAY_RECOVERY_LOCK_FILE:-/var/lock/ib_gateway_recovery.lock' "$recover_script"
grep -Fq 'IB_GATEWAY_RECOVERY_LOCK_WAIT_SECONDS:-900' "$recover_script"
grep -Fq 'flock -n 9' "$recover_script"
grep -Fq 'flock -w "${lock_wait_seconds}" 9' "$recover_script"
grep -Fq 'compose_service_name="${IB_GATEWAY_COMPOSE_SERVICE_NAME:-ib-gateway}"' "$recover_script"
grep -Fq 'fail_recovery()' "$recover_script"
grep -Fq 'GATEWAY_RECOVERY_FAILURE_STAGE=${stage}' "$recover_script"
grep -Fq 'CONTAINER_START_FAILED' "$recover_script"
grep -Fq 'CONTAINER_RESTART_FAILED' "$recover_script"
grep -Fq 'CONTAINER_RECREATE_FAILED' "$recover_script"
grep -Fq 'GATEWAY_NOT_READY_AFTER_RECREATE' "$recover_script"
! grep -Fq 'docker logs --tail 160' "$recover_script"
if invalid_config_output="$(IB_GATEWAY_TRANSIENT_DIALOG_RESTART_ATTEMPTS=invalid bash "$recover_script" live 2>&1)"; then
  echo "Invalid recovery configuration unexpectedly succeeded." >&2
  exit 1
else
  invalid_config_status=$?
fi
test "$invalid_config_status" -eq 2
test "$invalid_config_output" = 'GATEWAY_RECOVERY_FAILURE_STAGE=RECOVERY_CONFIGURATION_INVALID'
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
grep -Fq 'IB_GATEWAY_HEALTHCHECK_TICK_SECONDS:-300' "$health_watcher_script"
grep -Fq 'IB_GATEWAY_HEALTHCHECK_INTERVAL_SECONDS:-900' "$health_watcher_script"
grep -Fq 'IB_GATEWAY_EXECUTION_WINDOW_INTERVAL_SECONDS:-300' "$health_watcher_script"
grep -Fq 'IB_GATEWAY_HEALTHCHECK_FAILURE_THRESHOLD:-2' "$health_watcher_script"
grep -Fq 'IB_GATEWAY_DAILY_RESTART_ON_CALENDAR:-*-*-* 10:30:00 UTC' "$health_watcher_script"
grep -Fq 'compose_service_name="${IB_GATEWAY_COMPOSE_SERVICE_NAME:-ib-gateway}"' "$health_watcher_script"
grep -Fq 'gateway_mode="${1:-${IB_GATEWAY_MODE:-paper}}"' "$health_watcher_script"
grep -Fq 'compose_file="${COMPOSE_FILE:-docker-compose.yml}"' "$health_watcher_script"
grep -Fq 'Environment=IB_GATEWAY_COMPOSE_SERVICE_NAME=$compose_service_name' "$health_watcher_script"
grep -Fq 'Environment=COMPOSE_FILE=$compose_file' "$health_watcher_script"
grep -Fq 'Environment=IB_GATEWAY_RECOVERY_LOCK_FILE=$recovery_lock_file' "$health_watcher_script"
grep -Fq 'Environment=IB_GATEWAY_RECOVERY_LOCK_WAIT_SECONDS=0' "$health_watcher_script"
grep -Fq 'Environment=IB_GATEWAY_TRANSIENT_DIALOG_RESTART_ATTEMPTS=$transient_dialog_restart_attempts' "$health_watcher_script"
grep -Fq 'Environment=IB_GATEWAY_TRANSIENT_DIALOG_RESTART_WAIT_SECONDS=$transient_dialog_restart_wait_seconds' "$health_watcher_script"
grep -Fq 'Environment=IB_GATEWAY_HEALTHCHECK_INTERVAL_SECONDS=$health_interval_seconds' "$health_watcher_script"
grep -Fq 'Environment=IB_GATEWAY_EXECUTION_WINDOW_TIMES=$execution_window_times' "$health_watcher_script"
grep -Fq 'Environment=IB_GATEWAY_HEALTHCHECK_FAILURE_THRESHOLD=$failure_threshold' "$health_watcher_script"
grep -Fq 'monitor_ib_gateway_ready.sh' "$health_watcher_script"
grep -Fq 'OnActiveSec=$healthcheck_tick_seconds' "$health_watcher_script"
grep -Fq 'Persistent=false' "$health_watcher_script"
! grep -Fq 'OnBootSec=5min' "$health_watcher_script"
grep -Fq 'enable --now "$IBKR_GATEWAY_HEALTHCHECK_TIMER"' "$health_watcher_script"
grep -Fq 'enable --now "$IBKR_GATEWAY_DAILY_RESTART_TIMER"' "$health_watcher_script"
! grep -Fq 'start ibkr-gateway-healthcheck.service' "$health_watcher_script"

grep -Fq 'IB_GATEWAY_HEALTHCHECK_INTERVAL_SECONDS:-900' "$adaptive_monitor_script"
grep -Fq 'IB_GATEWAY_EXECUTION_WINDOW_INTERVAL_SECONDS:-300' "$adaptive_monitor_script"
grep -Fq 'IB_GATEWAY_EXECUTION_WINDOW_TIMES:-09:45,15:45' "$adaptive_monitor_script"
grep -Fq 'IB_GATEWAY_HEALTHCHECK_FAILURE_THRESHOLD:-2' "$adaptive_monitor_script"
grep -Fq 'IB_GATEWAY_READY_STABILITY_SECONDS=0' "$adaptive_monitor_script"
grep -Fq 'recovery is deferred until the threshold is reached' "$adaptive_monitor_script"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
mkdir -p "$tmp_dir/bin" "$tmp_dir/systemd"
cat >"$tmp_dir/bin/systemctl" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "$tmp_dir/bin/systemctl"

SYSTEMD_DIR="$tmp_dir/systemd" \
SYSTEMCTL_BIN="$tmp_dir/bin/systemctl" \
IB_GATEWAY_HEALTHCHECK_TICK_SECONDS=300 \
IB_GATEWAY_HEALTHCHECK_INTERVAL_SECONDS=900 \
IB_GATEWAY_EXECUTION_WINDOW_INTERVAL_SECONDS=300 \
IB_GATEWAY_HEALTHCHECK_FAILURE_THRESHOLD=2 \
  bash "$health_watcher_script" live

generated_health_service="$tmp_dir/systemd/ibkr-gateway-healthcheck.service"
generated_health_timer="$tmp_dir/systemd/ibkr-gateway-healthcheck.timer"
test -f "$generated_health_service"
test -f "$generated_health_timer"
grep -Fq 'Environment=IB_GATEWAY_HEALTHCHECK_INTERVAL_SECONDS=900' "$generated_health_service"
grep -Fq 'Environment=IB_GATEWAY_EXECUTION_WINDOW_INTERVAL_SECONDS=300' "$generated_health_service"
grep -Fq 'Environment=IB_GATEWAY_HEALTHCHECK_FAILURE_THRESHOLD=2' "$generated_health_service"
grep -Fq 'Environment=IB_GATEWAY_TRANSIENT_DIALOG_RESTART_ATTEMPTS=1' "$generated_health_service"
grep -Fq 'Environment=IB_GATEWAY_TRANSIENT_DIALOG_RESTART_WAIT_SECONDS=180' "$generated_health_service"
grep -Fq 'ExecStart=/bin/bash -lc' "$generated_health_service"
grep -Fq 'monitor_ib_gateway_ready.sh' "$generated_health_service"
grep -Fq 'OnActiveSec=300' "$generated_health_timer"
grep -Fq 'OnUnitActiveSec=300' "$generated_health_timer"

fake_docker_dir="$tmp_dir/fake-docker"
mkdir -p "$fake_docker_dir"
cat >"$fake_docker_dir/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' "$*" >>"${FAKE_DOCKER_LOG:?}"
case "${1:-}" in
  inspect)
    echo true
    ;;
  compose|exec|logs)
    ;;
  *)
    echo "Unexpected docker invocation: $*" >&2
    exit 1
    ;;
esac
SH
chmod +x "$fake_docker_dir/docker"

fake_docker_log="$tmp_dir/fake-docker.log"
FAKE_DOCKER_LOG="$fake_docker_log" \
PATH="$fake_docker_dir:$PATH" \
IB_GATEWAY_RECOVERY_LOCK_FILE="$tmp_dir/recovery.lock" \
IB_GATEWAY_READY_STABILITY_SECONDS=0 \
IB_GATEWAY_RECOVERY_INITIAL_WAIT_SECONDS=1 \
IB_GATEWAY_RECOVERY_RESTART_WAIT_SECONDS=1 \
IB_GATEWAY_RECOVERY_RECREATE_WAIT_SECONDS=1 \
IB_GATEWAY_TRANSIENT_DIALOG_RESTART_WAIT_SECONDS=1 \
  bash "$recover_script" live >"$tmp_dir/transient-dialog-recovery.log" 2>&1

grep -Fq 'restarting without acknowledging the dialog (1/1)' "$tmp_dir/transient-dialog-recovery.log"
grep -Fq 'compose restart ib-gateway' "$fake_docker_log"
if grep -Fq 'key Return' "$fake_docker_log"; then
  echo "Bounded dialog recovery must not acknowledge the Gateway dialog." >&2
  exit 1
fi

grep -Fq 'resolve_ibkr_gateway_unit_suffix()' "$unit_helper_script"
grep -Fq 'IBKR_2FA_BOT_SERVICE="ibkr-2fa-bot${unit_infix}.service"' "$unit_helper_script"

if invalid_deadline_output="$(IB_GATEWAY_MAINTENANCE_DEADLINE_EPOCH=notanumber bash "$recover_script" live 2>&1)"; then
  echo "Invalid maintenance deadline unexpectedly succeeded." >&2
  exit 1
else
  invalid_deadline_status=$?
fi
test "$invalid_deadline_status" -eq 2
test "$invalid_deadline_output" = 'GATEWAY_RECOVERY_FAILURE_STAGE=RECOVERY_CONFIGURATION_INVALID'

deadline_docker_log="$tmp_dir/deadline-docker.log"
: >"$deadline_docker_log"
deadline_rc=0
FAKE_DOCKER_LOG="$deadline_docker_log" \
PATH="$fake_docker_dir:$PATH" \
IB_GATEWAY_RECOVERY_LOCK_FILE="$tmp_dir/deadline-recovery.lock" \
IB_GATEWAY_READY_STABILITY_SECONDS=0 \
IB_GATEWAY_RECOVERY_INITIAL_WAIT_SECONDS=1 \
IB_GATEWAY_RECOVERY_RESTART_WAIT_SECONDS=1 \
IB_GATEWAY_RECOVERY_RECREATE_WAIT_SECONDS=1 \
IB_GATEWAY_TRANSIENT_DIALOG_RESTART_WAIT_SECONDS=1 \
IB_GATEWAY_MAINTENANCE_DEADLINE_EPOCH=1700000000 \
IB_GATEWAY_RECOVERY_NOW_EPOCH=1700000001 \
  bash "$recover_script" live >"$tmp_dir/deadline-recovery.log" 2>&1 || deadline_rc=$?
test "$deadline_rc" -eq 10
grep -Fq 'Maintenance window deadline (1700000000) reached before dialog recovery restart' "$tmp_dir/deadline-recovery.log"
if grep -Fq 'compose restart' "$deadline_docker_log" || grep -Fq -- '--force-recreate' "$deadline_docker_log"; then
  echo "Expired maintenance deadline must skip disruptive compose restart or force-recreate." >&2
  exit 1
fi
