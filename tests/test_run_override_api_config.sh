#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
run_override="$repo_dir/container_overrides/run.sh"
functions_file="$(mktemp)"
config_file="$(mktemp)"
trap 'rm -f "$functions_file" "$config_file"' EXIT

awk '
/^set_ibc_config_value\(\)/ { capture=1 }
/^configure_ib_gateway_vmoptions\(\)/ { capture=0; exit }
capture { print }
' "$run_override" > "$functions_file"

# shellcheck source=/dev/null
source "$functions_file"

cat > "$config_file" <<'CFG'
ReadOnlyApi=yes
AcceptIncomingConnectionAction=manual
CFG

IBC_INI="$config_file"
READ_ONLY_API=no
TWS_ACCEPT_INCOMING=accept
IB_GATEWAY_SKIP_IBC_READ_ONLY_API_CONFIG=yes
IB_GATEWAY_SKIP_IBC_ACCEPT_INCOMING_CONFIG=yes
configure_ibc_api_ui_settings

grep -Fxq 'ReadOnlyApi=no' "$config_file"
grep -Fxq 'AcceptIncomingConnectionAction=accept' "$config_file"

cat > "$config_file" <<'CFG'
ReadOnlyApi=yes
AcceptIncomingConnectionAction=manual
CFG

READ_ONLY_API=''
TWS_ACCEPT_INCOMING=''
IB_GATEWAY_SKIP_IBC_READ_ONLY_API_CONFIG=yes
IB_GATEWAY_SKIP_IBC_ACCEPT_INCOMING_CONFIG=yes
configure_ibc_api_ui_settings

grep -Fxq 'ReadOnlyApi=yes' "$config_file"
grep -Fxq 'AcceptIncomingConnectionAction=manual' "$config_file"
