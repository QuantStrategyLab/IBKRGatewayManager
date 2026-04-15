#!/usr/bin/env bash
set -euo pipefail

container_name="${IB_GATEWAY_CONTAINER_NAME:-ib-gateway}"
gateway_mode="${1:-${IB_GATEWAY_MODE:-paper}}"
ready_timeout_seconds="${IB_GATEWAY_READY_TIMEOUT_SECONDS:-240}"
poll_interval_seconds="${IB_GATEWAY_READY_POLL_INTERVAL_SECONDS:-5}"
handshake_timeout_seconds="${IB_GATEWAY_HANDSHAKE_TIMEOUT_SECONDS:-12}"
healthcheck_client_id="${IB_GATEWAY_HEALTHCHECK_CLIENT_ID:-999}"

case "${gateway_mode}" in
  paper)
    gateway_port=4002
    ;;
  live)
    gateway_port=4001
    ;;
  *)
    echo "Unsupported IB gateway mode: ${gateway_mode}" >&2
    exit 1
    ;;
esac

deadline=$((SECONDS + ready_timeout_seconds))

check_api_handshake() {
  timeout "${handshake_timeout_seconds}" docker exec -i "${container_name}" \
    env IB_GATEWAY_HEALTHCHECK_PORT="${gateway_port}" \
      IB_GATEWAY_HEALTHCHECK_CLIENT_ID="${healthcheck_client_id}" \
      IB_GATEWAY_HEALTHCHECK_TIMEOUT_SECONDS="${handshake_timeout_seconds}" \
    python3 <<'PY'
import os
import socket
import struct
import time


host = "127.0.0.1"
port = int(os.environ["IB_GATEWAY_HEALTHCHECK_PORT"])
client_id = int(os.environ["IB_GATEWAY_HEALTHCHECK_CLIENT_ID"])
timeout_seconds = float(os.environ["IB_GATEWAY_HEALTHCHECK_TIMEOUT_SECONDS"])
deadline = time.monotonic() + timeout_seconds


def remaining_timeout() -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("IB API healthcheck timed out")
    return remaining


def recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining > 0:
        sock.settimeout(remaining_timeout())
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("IB API socket closed during healthcheck")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_fields(sock: socket.socket) -> list[str]:
    raw_size = recv_exact(sock, 4)
    size = struct.unpack(">I", raw_size)[0]
    payload = recv_exact(sock, size).decode(errors="backslashreplace")
    fields = payload.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    return fields


def send_prefixed(sock: socket.socket, payload: bytes) -> None:
    sock.sendall(struct.pack(">I", len(payload)) + payload)


with socket.create_connection((host, port), timeout=remaining_timeout()) as sock:
    sock.settimeout(remaining_timeout())
    # Match the modern IB API v100+ handshake used by ib_insync.
    hello = b"API\0" + struct.pack(">I", len(b"v157..176")) + b"v157..176"
    sock.sendall(hello)

    handshake_fields = read_fields(sock)
    if len(handshake_fields) != 2:
        raise RuntimeError(f"unexpected IB handshake response: {handshake_fields!r}")
    server_version = int(handshake_fields[0])
    if server_version < 157:
        raise RuntimeError(f"IB server version too old for healthcheck: {server_version}")

    start_api_payload = b"71\0" + b"2\0" + str(client_id).encode() + b"\0\0"
    send_prefixed(sock, start_api_payload)

    has_next_valid_id = False
    has_managed_accounts = False
    while not (has_next_valid_id and has_managed_accounts):
        fields = read_fields(sock)
        if not fields:
            continue
        msg_id = fields[0]
        if msg_id == "9":
            has_next_valid_id = True
        elif msg_id == "15":
            has_managed_accounts = True

print(f"IB API handshake ready: server_version={server_version} client_id={client_id}")
PY
}

echo "Waiting for ${container_name} IB API handshake readiness on internal port ${gateway_port} (mode=${gateway_mode}, client_id=${healthcheck_client_id})"

while true; do
  if docker inspect --format '{{.State.Running}}' "${container_name}" 2>/dev/null | grep -Fxq 'true'; then
    if check_api_handshake; then
      echo "IB gateway API handshake is ready on internal port ${gateway_port} (mode=${gateway_mode})"
      exit 0
    fi
  fi

  if [ "${SECONDS}" -ge "${deadline}" ]; then
    echo "Timed out waiting for ${container_name} IB API handshake readiness on internal port ${gateway_port}" >&2
    echo "--- docker compose ps ---" >&2
    docker compose ps >&2 || true
    echo "--- recent container logs ---" >&2
    docker logs --tail 120 "${container_name}" >&2 || true
    exit 1
  fi

  sleep "${poll_interval_seconds}"
done
