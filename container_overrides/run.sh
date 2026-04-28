#!/bin/bash
# shellcheck disable=SC2317
# Don't warn about unreachable commands in this file

set -Eeo pipefail

echo "*************************************************************************"
echo ".> Starting IBC/IB gateway"
echo "*************************************************************************"

source "${SCRIPT_PATH}/common.sh"

stop_ibc() {
	echo ".> 😘 Received SIGINT or SIGTERM. Shutting down IB Gateway."

	if pgrep x11vnc >/dev/null; then
		echo ".> Stopping x11vnc."
		pkill x11vnc
	fi

	echo ".> Stopping Xvfb."
	pkill Xvfb

	if [ -n "$SSH_TUNNEL" ]; then
		echo ".> Stopping ssh."
		pkill run_ssh.sh
		pkill ssh
		echo ".> Stopping socat."
		pkill run_socat.sh
		pkill socat
	else
		echo ".> Stopping socat."
		pkill run_socat.sh
		pkill socat
	fi

	echo ".> Stopping IBC."
	kill -SIGTERM "${pid[@]}"
	wait "${pid[@]}"
	echo ".> Done... $?"
}

start_xvfb() {
	echo ".> Starting Xvfb server"
	DISPLAY=:1
	export DISPLAY
	rm -f /tmp/.X1-lock
	Xvfb "$DISPLAY" -ac -screen 0 "${IB_XVFB_SCREEN:-1024x768x24}" &
}

start_vnc() {
	wait_x_socket
	file_env 'VNC_SERVER_PASSWORD'
	if [ -n "$VNC_SERVER_PASSWORD" ]; then
		echo ".> Starting VNC server"
		x11vnc -display "$DISPLAY" -forever -shared -bg -noipv6 \
			-ncache_cr -noxdamage \
			-passwd "$VNC_SERVER_PASSWORD" &
		unset_env 'VNC_SERVER_PASSWORD'
	else
		echo ".> VNC server disabled"
	fi
}

start_IBC() {
	configure_ibc_login_dialog_timeout
	echo ".> Starting IBC in ${TRADING_MODE} mode, with params:"
	echo ".>		Version: ${TWS_MAJOR_VRSN}"
	echo ".>		program: ${IBC_COMMAND:-gateway}"
	echo ".>		tws-path: ${TWS_PATH}"
	echo ".>		ibc-path: ${IBC_PATH}"
	echo ".>		ibc-init: ${IBC_INI}"
	echo ".>		tws-settings-path: ${TWS_SETTINGS_PATH:-$TWS_PATH}"
	echo ".>		on2fatimeout: ${TWOFA_TIMEOUT_ACTION}"
	"${IBC_PATH}/scripts/ibcstart.sh" "${TWS_MAJOR_VRSN}" -g \
		"--tws-path=${TWS_PATH}" \
		"--ibc-path=${IBC_PATH}" "--ibc-ini=${IBC_INI}" \
		"--on2fatimeout=${TWOFA_TIMEOUT_ACTION}" \
		"--tws-settings-path=${TWS_SETTINGS_PATH:-}" &
	_p="$!"
	pid+=("$_p")
	export pid
	echo "$_p" >"/tmp/pid_${TRADING_MODE}"
}

configure_ibc_login_dialog_timeout() {
	local timeout="${IBC_LOGIN_DIALOG_DISPLAY_TIMEOUT:-180}"
	local files=(
		"${IBC_INI:-/home/ibgateway/ibc/config.ini}"
		"/home/ibgateway/ibc/config.ini"
		"/home/ibgateway/ibc/config.ini.tmpl"
	)
	local file

	for file in "${files[@]}"; do
		if [ ! -f "$file" ]; then
			continue
		fi
		if grep -Eq '^LoginDialogDisplayTimeout\s*=' "$file"; then
			sed -i -E "s/^LoginDialogDisplayTimeout\s*=.*/LoginDialogDisplayTimeout=${timeout}/" "$file"
		else
			printf '\nLoginDialogDisplayTimeout=%s\n' "$timeout" >>"$file"
		fi
	done
}

configure_ib_gateway_vmoptions() {
	local parallel_threads="${IB_GATEWAY_PARALLEL_GC_THREADS:-2}"
	local conc_threads="${IB_GATEWAY_CONC_GC_THREADS:-1}"
	local vmoptions

	vmoptions="$(find "${TWS_PATH}" -maxdepth 3 -name ibgateway.vmoptions -type f 2>/dev/null | head -n 1 || true)"
	if [ -z "$vmoptions" ]; then
		echo ".> IB Gateway vmoptions file not found; skipping Java GC thread tuning"
		return
	fi

	if grep -Eq '^-XX:ParallelGCThreads=' "$vmoptions"; then
		sed -i -E "s/^-XX:ParallelGCThreads=.*/-XX:ParallelGCThreads=${parallel_threads}/" "$vmoptions"
	else
		printf '\n-XX:ParallelGCThreads=%s\n' "$parallel_threads" >>"$vmoptions"
	fi
	if grep -Eq '^-XX:ConcGCThreads=' "$vmoptions"; then
		sed -i -E "s/^-XX:ConcGCThreads=.*/-XX:ConcGCThreads=${conc_threads}/" "$vmoptions"
	else
		printf '\n-XX:ConcGCThreads=%s\n' "$conc_threads" >>"$vmoptions"
	fi
	echo ".> Java GC threads set to ParallelGCThreads=${parallel_threads}, ConcGCThreads=${conc_threads}"
}

start_process() {
	set_ports
	apply_settings
	port_forwarding
	start_IBC
}

if [ -n "$START_SCRIPTS" ]; then
	run_scripts "$HOME/$START_SCRIPTS"
fi

start_xvfb
setup_ssh
set_java_heap
configure_ib_gateway_vmoptions
start_vnc

if [ -n "$X_SCRIPTS" ]; then
	wait_x_socket
	run_scripts "$HOME/$X_SCRIPTS"
fi

if [ "$TRADING_MODE" == "both" ] || [ "$DUAL_MODE" == "yes" ]; then
	DUAL_MODE=yes
	export DUAL_MODE
	TRADING_MODE=live
	_IBC_INI="${IBC_INI}"
	export _IBC_INI
	IBC_INI="${_IBC_INI}_${TRADING_MODE}"
	if [ -n "$TWS_SETTINGS_PATH" ]; then
		_TWS_SETTINGS_PATH="${TWS_SETTINGS_PATH}"
		export _TWS_SETTINGS_PATH
		TWS_SETTINGS_PATH="${_TWS_SETTINGS_PATH}_${TRADING_MODE}"
	else
		_TWS_SETTINGS_PATH="${TWS_PATH}"
		export _TWS_SETTINGS_PATH
		TWS_SETTINGS_PATH="${_TWS_SETTINGS_PATH}_${TRADING_MODE}"
	fi
fi

start_process

if [ "$DUAL_MODE" == "yes" ]; then
	TRADING_MODE=paper
	TWS_USERID="${TWS_USERID_PAPER}"
	export TWS_USERID

	if [ -n "${TWS_PASSWORD_PAPER_FILE}" ]; then
		TWS_PASSWORD_FILE="${TWS_PASSWORD_PAPER_FILE}"
		export TWS_PASSWORD_FILE
	else
		TWS_PASSWORD="${TWS_PASSWORD_PAPER}"
		export TWS_PASSWORD
	fi

	SSH_VNC_PORT=
	export SSH_VNC_PORT
	SSH_REMOTE_PORT=
	export SSH_REMOTE_PORT
	IBC_INI="${_IBC_INI}_${TRADING_MODE}"
	TWS_SETTINGS_PATH="${_TWS_SETTINGS_PATH}_${TRADING_MODE}"

	sleep 15
	start_process
fi

if [ -n "$IBC_SCRIPTS" ]; then
	run_scripts "$HOME/$IBC_SCRIPTS"
fi

trap stop_ibc SIGINT SIGTERM
wait "${pid[@]}"
exit $?
