#!/usr/bin/env bash

ib_gateway_started_at_is_valid() {
  local started_at="${1:-}"

  [[ "${started_at}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$ ]] \
    && [[ "${started_at}" != 0001-01-01T00:00:00* ]]
}

ib_gateway_inspect_container_epoch() {
  local container_ref="${1:-}"
  local inspect_record container_id started_at

  [ -n "${container_ref}" ] || return 1
  inspect_record="$(docker inspect --format '{{.Id}} {{.State.StartedAt}}' "${container_ref}" 2>/dev/null)" \
    || return 1
  read -r container_id started_at <<<"${inspect_record}"
  [ -n "${container_id}" ] || return 1
  ib_gateway_started_at_is_valid "${started_at}" || return 1
  printf '%s %s\n' "${container_id}" "${started_at}"
}

ib_gateway_validate_replacement_epoch() {
  local old_container_id="${1:-}"
  local replacement_container_id="${2:-}"
  local replacement_started_at="${3:-}"

  [ -n "${old_container_id}" ] \
    && [ -n "${replacement_container_id}" ] \
    && [ "${old_container_id}" != "${replacement_container_id}" ] \
    && ib_gateway_started_at_is_valid "${replacement_started_at}"
}
