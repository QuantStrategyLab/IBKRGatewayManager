#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
compose_file="$repo_dir/docker-compose.yml"
dockerfile="$repo_dir/Dockerfile"
run_override="$repo_dir/container_overrides/run.sh"

grep -Fq 'pip3 install pyotp ib_insync --break-system-packages' "$dockerfile"
grep -Eq '^FROM gnzsnz/ib-gateway:[0-9]+[.][0-9]+[.][0-9]+[[:alnum:]._-]*$' "$dockerfile"
grep -Fq 'LoginDialogDisplayTimeout=180' "$dockerfile"
grep -Fq 'failed to set LoginDialogDisplayTimeout' "$dockerfile"
grep -Fq '/home/ibgateway/ibc/config.ini.tmpl' "$dockerfile"
grep -Fq 'COPY --chown=1000:1000 ./container_overrides/run.sh /home/ibgateway/scripts/run.sh' "$dockerfile"
grep -Fq 'chmod a+x /home/ibgateway/scripts/run.sh' "$dockerfile"
grep -Fq 'libgtk-3-0' "$dockerfile"
grep -Fq 'libglib2.0-0' "$dockerfile"
grep -Fq 'libxtst6' "$dockerfile"
grep -Fq 'x11-apps' "$dockerfile"
grep -Fq 'Xvfb "$DISPLAY" -ac -screen 0 "${IB_XVFB_SCREEN:-1024x768x24}" &' "$run_override"
grep -Fq -- '-ncache_cr -noxdamage' "$run_override"
grep -Fq 'configure_ibc_login_dialog_timeout' "$run_override"
grep -Fq 'IBC_LOGIN_DIALOG_DISPLAY_TIMEOUT:-180' "$run_override"
grep -Fq 'set_ibc_config_value "LoginDialogDisplayTimeout" "$timeout"' "$run_override"
grep -Fq 'configure_ibc_second_factor_exit_interval' "$run_override"
grep -Fq 'IBC_SECOND_FACTOR_AUTHENTICATION_EXIT_INTERVAL:-180' "$run_override"
grep -Fq 'set_ibc_config_value "SecondFactorAuthenticationExitInterval" "$interval"' "$run_override"
grep -Fq 'configure_ibc_api_ui_settings' "$run_override"
grep -Fq 'IB_GATEWAY_SKIP_IBC_READ_ONLY_API_CONFIG:-yes' "$run_override"
grep -Fq "normalized_read_only_api=\"\$(printf '%s' \"\$read_only_api\" | tr '[:upper:]' '[:lower:]')\"" "$run_override"
grep -Fq 'set_ibc_config_value "ReadOnlyApi" "$normalized_read_only_api"' "$run_override"
grep -Fq 'IB_GATEWAY_SKIP_IBC_ACCEPT_INCOMING_CONFIG:-yes' "$run_override"
grep -Fq "normalized_accept_incoming=\"\$(printf '%s' \"\$accept_incoming\" | tr '[:upper:]' '[:lower:]')\"" "$run_override"
grep -Fq 'set_ibc_config_value "AcceptIncomingConnectionAction" "$normalized_accept_incoming"' "$run_override"
grep -Fq 'configure_ib_gateway_vmoptions' "$run_override"
grep -Fq 'find "${TWS_PATH}" -maxdepth 3 -name ibgateway.vmoptions' "$run_override"
grep -Fq 'IB_GATEWAY_PARALLEL_GC_THREADS:-2' "$run_override"
grep -Fq 'IB_GATEWAY_CONC_GC_THREADS:-1' "$run_override"
grep -Fq 'Java GC threads set to ParallelGCThreads=${parallel_threads}, ConcGCThreads=${conc_threads}' "$run_override"

grep -Fq 'container_name: ${IB_GATEWAY_CONTAINER_NAME:-ib-gateway}' "$compose_file"
grep -Fq '      - "${IB_GATEWAY_LIVE_HOST_PORT:-4001}:4003"' "$compose_file"
grep -Fq '      - "${IB_GATEWAY_PAPER_HOST_PORT:-4002}:4004"' "$compose_file"
grep -Fq '      - "${IB_GATEWAY_VNC_HOST_ADDRESS:-127.0.0.1}:${IB_GATEWAY_VNC_HOST_PORT:-5900}:5900"' "$compose_file"
grep -Fq '      - TWS_ACCEPT_INCOMING=${TWS_ACCEPT_INCOMING:-accept}' "$compose_file"
grep -Fq '      - READ_ONLY_API=${READ_ONLY_API:-no}' "$compose_file"
grep -Fq '      - IB_GATEWAY_SKIP_IBC_READ_ONLY_API_CONFIG=${IB_GATEWAY_SKIP_IBC_READ_ONLY_API_CONFIG:-yes}' "$compose_file"
grep -Fq '      - IB_GATEWAY_SKIP_IBC_ACCEPT_INCOMING_CONFIG=${IB_GATEWAY_SKIP_IBC_ACCEPT_INCOMING_CONFIG:-yes}' "$compose_file"
grep -Fq '      - TWOFA_DEVICE=${TWOFA_DEVICE:-}' "$compose_file"
grep -Fq '      - TWOFA_TIMEOUT_ACTION=${TWOFA_TIMEOUT_ACTION:-restart}' "$compose_file"
grep -Fq '      - RELOGIN_AFTER_TWOFA_TIMEOUT=${RELOGIN_AFTER_TWOFA_TIMEOUT:-yes}' "$compose_file"
grep -Fq '      - IBC_SECOND_FACTOR_AUTHENTICATION_EXIT_INTERVAL=${IBC_SECOND_FACTOR_AUTHENTICATION_EXIT_INTERVAL:-180}' "$compose_file"
grep -Fq '      - EXISTING_SESSION_DETECTED_ACTION=${EXISTING_SESSION_DETECTED_ACTION:-primary}' "$compose_file"
grep -Fq '      - IBKR_2FA_AUTOFILL=${IBKR_2FA_AUTOFILL:-yes}' "$compose_file"
grep -Fq '      - IBKR_2FA_MAX_SUBMISSIONS=${IBKR_2FA_MAX_SUBMISSIONS:-1}' "$compose_file"
grep -Fq '      - JAVA_HEAP_SIZE=${JAVA_HEAP_SIZE:-512}' "$compose_file"
grep -Fq '      - IB_GATEWAY_PARALLEL_GC_THREADS=${IB_GATEWAY_PARALLEL_GC_THREADS:-2}' "$compose_file"
grep -Fq '      - IB_GATEWAY_CONC_GC_THREADS=${IB_GATEWAY_CONC_GC_THREADS:-1}' "$compose_file"
grep -Fq '      - ACCEPT_API_FROM_IP=${ACCEPT_API_FROM_IP:?Set ACCEPT_API_FROM_IP to your Cloud Run egress subnet or connector CIDR}' "$compose_file"

grep -Fq 'INPUT_CLICK_POSITION = (0.50, 0.40)' "$repo_dir/2fa_bot.py"
grep -Fq 'MIN_TOTP_SECONDS_REMAINING = 15' "$repo_dir/2fa_bot.py"
grep -Fq 'SMALL_GATEWAY_DIALOG_MAX_WIDTH = 650' "$repo_dir/2fa_bot.py"
grep -Fq 'SMALL_GATEWAY_DIALOG_MAX_HEIGHT = 220' "$repo_dir/2fa_bot.py"
grep -Fq 'def is_small_gateway_dialog(title, width, height):' "$repo_dir/2fa_bot.py"
grep -Fq 'SMALL_CONNECTION_DIALOG_TITLE = "gateway"' "$repo_dir/2fa_bot.py"
grep -Fq 'def is_small_connection_dialog(title, width, height):' "$repo_dir/2fa_bot.py"
grep -Fq 'is_dismissible_dialog_candidate(title, width, height)' "$repo_dir/2fa_bot.py"
grep -Fq 'def type_totp_into_active_window(code):' "$repo_dir/2fa_bot.py"

REPO_DIR="$repo_dir" python3 <<'PY'
import importlib.util
import os
import sys
import types

sys.modules["pyotp"] = types.SimpleNamespace()
module_path = os.path.join(os.environ["REPO_DIR"], "2fa_bot.py")
spec = importlib.util.spec_from_file_location("ibkr_2fa_bot_test", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

assert module.is_dismissible_dialog_candidate("Login Messages")
assert module.is_dismissible_dialog_candidate("IBKR Gateway", 509, 131)
assert module.is_dismissible_dialog_candidate("Gateway", 510, 131)
assert not module.is_dismissible_dialog_candidate("IBKR Gateway", 700, 550)
assert not module.is_dismissible_dialog_candidate("IBKR Gateway", 790, 610)
assert not module.is_dismissible_dialog_candidate("Gateway", 790, 610)
PY
