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

# Verify configure_ib_gateway_vmoptions opt-in SerialGC safety
vmopt_dir="$(mktemp -d)"
vmopt_fn_file="$(mktemp)"
trap 'rm -f "$functions_file" "$config_file" "$vmopt_fn_file"; rm -rf "$vmopt_dir"' EXIT
awk '
/^configure_ib_gateway_vmoptions\(\)/ { capture=1 }
/^start_process\(\)/ { capture=0; exit }
capture { print }
' "$run_override" > "$vmopt_fn_file"
# shellcheck source=/dev/null
source "$vmopt_fn_file"

TWS_PATH="$vmopt_dir"
cat > "$vmopt_dir/ibgateway.vmoptions" <<'VMOPT'
-Xmx768m
-XX:+UseG1GC
-XX:ParallelGCThreads=20
-XX:ConcGCThreads=4
VMOPT

IB_GATEWAY_USE_SERIAL_GC=no
IB_GATEWAY_PARALLEL_GC_THREADS=2
IB_GATEWAY_CONC_GC_THREADS=1
configure_ib_gateway_vmoptions
grep -Fxq -- '-XX:+UseG1GC' "$vmopt_dir/ibgateway.vmoptions"
grep -Fxq -- '-XX:ParallelGCThreads=2' "$vmopt_dir/ibgateway.vmoptions"
grep -Fxq -- '-XX:ConcGCThreads=1' "$vmopt_dir/ibgateway.vmoptions"

IB_GATEWAY_USE_SERIAL_GC=yes
configure_ib_gateway_vmoptions
! grep -Fq -- '-XX:+UseG1GC' "$vmopt_dir/ibgateway.vmoptions"
grep -Fxq -- '-XX:+UseSerialGC' "$vmopt_dir/ibgateway.vmoptions"
grep -Fxq -- '-XX:ParallelGCThreads=2' "$vmopt_dir/ibgateway.vmoptions"
