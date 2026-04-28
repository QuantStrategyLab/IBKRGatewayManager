#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="${REPO_DIR:-$(cd "${script_dir}/.." && pwd)}"
systemd_dir="${SYSTEMD_DIR:-/etc/systemd/system}"
systemctl_bin="${SYSTEMCTL_BIN:-systemctl}"
container_name="${CONTAINER_NAME:-${IB_GATEWAY_CONTAINER_NAME:-ib-gateway}}"
gateway_mode="${IB_GATEWAY_MODE:-paper}"
health_interval_seconds="${IB_GATEWAY_HEALTHCHECK_INTERVAL_SECONDS:-300}"
daily_restart_calendar="${IB_GATEWAY_DAILY_RESTART_ON_CALENDAR:-*-*-* 10:30:00 UTC}"

install -d "$systemd_dir"

cat >"$systemd_dir/ibkr-gateway-healthcheck.service" <<EOF
[Unit]
Description=Check and recover IBKR Gateway API readiness
After=docker.service network-online.target
Wants=docker.service network-online.target

[Service]
Type=oneshot
WorkingDirectory=$repo_dir
Environment=IB_GATEWAY_CONTAINER_NAME=$container_name
Environment=IB_GATEWAY_MODE=$gateway_mode
Environment=IB_GATEWAY_RECOVERY_LOCK_WAIT_SECONDS=0
ExecStart=/bin/bash -lc 'cd "$repo_dir" && exec ./scripts/recover_ib_gateway_ready.sh "$gateway_mode"'
EOF

cat >"$systemd_dir/ibkr-gateway-healthcheck.timer" <<EOF
[Unit]
Description=Run IBKR Gateway API readiness recovery every $health_interval_seconds seconds

[Timer]
OnBootSec=5min
OnUnitActiveSec=$health_interval_seconds
Unit=ibkr-gateway-healthcheck.service

[Install]
WantedBy=timers.target
EOF

cat >"$systemd_dir/ibkr-gateway-daily-restart.service" <<EOF
[Unit]
Description=Scheduled IBKR Gateway container restart
After=docker.service network-online.target
Wants=docker.service network-online.target

[Service]
Type=oneshot
WorkingDirectory=$repo_dir
Environment=IB_GATEWAY_CONTAINER_NAME=$container_name
Environment=IB_GATEWAY_MODE=$gateway_mode
ExecStart=/bin/bash -lc 'cd "$repo_dir" && exec ./scripts/restart_ib_gateway_daily.sh "$gateway_mode"'
EOF

cat >"$systemd_dir/ibkr-gateway-daily-restart.timer" <<EOF
[Unit]
Description=Restart IBKR Gateway on a fixed daily schedule

[Timer]
OnCalendar=$daily_restart_calendar
Persistent=true
Unit=ibkr-gateway-daily-restart.service

[Install]
WantedBy=timers.target
EOF

"$systemctl_bin" daemon-reload
"$systemctl_bin" enable --now ibkr-gateway-healthcheck.timer
"$systemctl_bin" enable --now ibkr-gateway-daily-restart.timer
