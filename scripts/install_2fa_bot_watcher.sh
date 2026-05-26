#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
bin_dir="${BIN_DIR:-/usr/local/bin}"
systemd_dir="${SYSTEMD_DIR:-/etc/systemd/system}"
systemctl_bin="${SYSTEMCTL_BIN:-systemctl}"
container_name="${CONTAINER_NAME:-${IB_GATEWAY_CONTAINER_NAME:-ib-gateway}}"
unit_suffix="${IB_GATEWAY_UNIT_SUFFIX:-}"

. "$script_dir/ibkr_gateway_units.sh"
resolve_ibkr_gateway_unit_names "$container_name" "$unit_suffix"

install -d "$bin_dir" "$systemd_dir"
install -m 0755 "$script_dir/ensure_2fa_bot_running.sh" "$bin_dir/ensure-ibkr-2fa-bot-running"

cat >"$systemd_dir/$IBKR_2FA_BOT_SERVICE" <<EOF
[Unit]
Description=Ensure IBKR 2FA bot is running inside Docker
After=docker.service network-online.target
Wants=docker.service network-online.target

[Service]
Type=oneshot
Environment=CONTAINER_NAME=$container_name
ExecStart=$bin_dir/ensure-ibkr-2fa-bot-running
EOF

cat >"$systemd_dir/$IBKR_2FA_BOT_TIMER" <<EOF
[Unit]
Description=Run IBKR 2FA bot watcher every minute

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
Unit=$IBKR_2FA_BOT_SERVICE

[Install]
WantedBy=timers.target
EOF

"$systemctl_bin" daemon-reload
"$systemctl_bin" enable --now "$IBKR_2FA_BOT_TIMER"
"$systemctl_bin" start "$IBKR_2FA_BOT_SERVICE"
