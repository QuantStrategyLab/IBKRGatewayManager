#!/usr/bin/env bash
set -euo pipefail

key_file="${SSH_KEY_FILE:-}"
if [[ -z "${key_file}" || ! -f "${key_file}" ]]; then
  echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=credential_invalid"
  exit 1
fi

normalized_file=""
cleanup() {
  if [[ -n "${normalized_file}" ]]; then rm -f -- "${normalized_file}" 2>/dev/null || true; fi
}
trap cleanup EXIT

normalized_file="$(mktemp "${RUNNER_TEMP:-/tmp}/gateway-ssh-key-normalized.XXXXXX" 2>/dev/null)" || {
  rm -f -- "${key_file}" 2>/dev/null || true
  echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=credential_invalid"
  exit 1
}
chmod 600 "${normalized_file}" 2>/dev/null || {
  rm -f -- "${key_file}" 2>/dev/null || true
  echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=credential_invalid"
  exit 1
}
if ! tr -d '\r' <"${key_file}" >"${normalized_file}" 2>/dev/null || [[ ! -s "${normalized_file}" ]]; then
  rm -f -- "${key_file}" 2>/dev/null || true
  echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=credential_invalid"
  exit 1
fi
if ! ssh-keygen -y -P '' -f "${normalized_file}" >/dev/null 2>/dev/null; then
  rm -f -- "${key_file}" 2>/dev/null || true
  echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=credential_invalid"
  exit 1
fi
if ! cat "${normalized_file}" >"${key_file}" 2>/dev/null || ! chmod 600 "${key_file}" 2>/dev/null; then
  rm -f -- "${key_file}"
  echo "GATEWAY_CONNECTION_INSPECTION=blocked reason=credential_invalid"
  exit 1
fi

echo "GATEWAY_SSH_KEY_STATUS=ready"
