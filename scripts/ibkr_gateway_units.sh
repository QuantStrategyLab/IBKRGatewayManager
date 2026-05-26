#!/usr/bin/env bash

sanitize_ibkr_systemd_suffix() {
  local raw_suffix="${1:-}"
  local sanitized
  sanitized="$(printf '%s' "$raw_suffix" | tr -cs 'A-Za-z0-9_.@-' '-' | sed -e 's/^-//' -e 's/-$//')"
  printf '%s' "$sanitized"
}

resolve_ibkr_gateway_unit_suffix() {
  local container_name="${1:-ib-gateway}"
  local configured_suffix="${2:-}"
  local raw_suffix=""

  if [ -n "$configured_suffix" ]; then
    raw_suffix="$configured_suffix"
  elif [ "$container_name" != "ib-gateway" ]; then
    raw_suffix="$container_name"
  fi

  sanitize_ibkr_systemd_suffix "$raw_suffix"
}

resolve_ibkr_gateway_unit_names() {
  local container_name="${1:-ib-gateway}"
  local configured_suffix="${2:-}"
  local unit_suffix
  local unit_infix=""

  unit_suffix="$(resolve_ibkr_gateway_unit_suffix "$container_name" "$configured_suffix")"
  if [ -n "$unit_suffix" ]; then
    unit_infix="-$unit_suffix"
  fi

  IBKR_2FA_BOT_SERVICE="ibkr-2fa-bot${unit_infix}.service"
  IBKR_2FA_BOT_TIMER="ibkr-2fa-bot${unit_infix}.timer"
  IBKR_GATEWAY_HEALTHCHECK_SERVICE="ibkr-gateway-healthcheck${unit_infix}.service"
  IBKR_GATEWAY_HEALTHCHECK_TIMER="ibkr-gateway-healthcheck${unit_infix}.timer"
  IBKR_GATEWAY_DAILY_RESTART_SERVICE="ibkr-gateway-daily-restart${unit_infix}.service"
  IBKR_GATEWAY_DAILY_RESTART_TIMER="ibkr-gateway-daily-restart${unit_infix}.timer"

  export IBKR_2FA_BOT_SERVICE
  export IBKR_2FA_BOT_TIMER
  export IBKR_GATEWAY_HEALTHCHECK_SERVICE
  export IBKR_GATEWAY_HEALTHCHECK_TIMER
  export IBKR_GATEWAY_DAILY_RESTART_SERVICE
  export IBKR_GATEWAY_DAILY_RESTART_TIMER
}
