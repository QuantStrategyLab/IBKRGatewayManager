"""Classify captured SSH/IAP errors into fixed, non-sensitive categories."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


_PATTERNS = {
    "timeout": re.compile(r"(?:connection|operation|command|connect) timed out|\btimeout\b", re.I),
    "key_invalid": re.compile(
        r"invalid format|error in libcrypto|incorrect passphrase|bad passphrase|load key .*: invalid",
        re.I,
    ),
    "auth_denied": re.compile(
        r"permission denied \(publickey[^)]*\)|no supported authentication methods|authentication failed|too many authentication failures",
        re.I,
    ),
    "iap_denied": re.compile(
        r"(?:start-iap-tunnel|iap tunnel|iap-tunnel).{0,160}(?:4033|not authorized|permission denied|forbidden)|"
        r"(?:4033|not authorized|permission denied|forbidden).{0,160}(?:start-iap-tunnel|iap tunnel|iap-tunnel)",
        re.I | re.S,
    ),
    "iap_transport": re.compile(
        r"(?:start-iap-tunnel|iap tunnel|iap-tunnel).{0,160}(?:failed to connect|connection refused|backend|unreachable|closed)|"
        r"(?:failed to connect|connection refused|backend|unreachable|closed).{0,160}(?:start-iap-tunnel|iap tunnel|iap-tunnel)",
        re.I | re.S,
    ),
}


def classify_gateway_ssh_failure(message: str) -> str:
    """Return a category only when the captured text identifies exactly one."""

    matches = [name for name, pattern in _PATTERNS.items() if pattern.search(message)]
    return matches[0] if len(matches) == 1 else "unknown"


_RESPONSE_PATTERNS = {
    "GATEWAY_CONNECTION_INSPECTION": r"GATEWAY_CONNECTION_INSPECTION=observed",
    "GATEWAY_CONTAINER_RUNNING": r"GATEWAY_CONTAINER_RUNNING=(true|false)",
    "GATEWAY_API_LISTENER": r"GATEWAY_API_LISTENER=(true|false)",
    "GATEWAY_ESTABLISHED_CONNECTION_COUNT": r"GATEWAY_ESTABLISHED_CONNECTION_COUNT=[0-9]+",
    "GATEWAY_CONNECTION_OBSERVED_AT_UTC": r"GATEWAY_CONNECTION_OBSERVED_AT_UTC=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
    "GATEWAY_CONNECTION_INSPECTION_LIMIT": (
        "GATEWAY_CONNECTION_INSPECTION_LIMIT="
        "OBSERVATION_ONLY_NO_AUTH_OR_CONCURRENCY_ASSERTION"
    ),
}
_HELPER_BLOCKED_REASONS = {
    "configuration_invalid",
    "container_inspection_failed",
    "container_state_invalid",
    "container_pid_invalid",
    "socket_inspection_failed",
    "socket_result_invalid",
    "port_mapping_inspection_failed",
    "port_mapping_invalid",
}
_PRESENCE_PATTERNS = {
    "GATEWAY_PUBLISHED_API_MAPPING": r"GATEWAY_PUBLISHED_API_MAPPING=(observed|not_published|container_stopped)",
    "GATEWAY_PUBLISHED_CONTAINER_API_LISTENER": r"GATEWAY_PUBLISHED_CONTAINER_API_LISTENER=(true|false|unknown)",
    "GATEWAY_HOST_API_LISTENER": r"GATEWAY_HOST_API_LISTENER=(true|false)",
    "GATEWAY_HOST_WEB_DEFAULT_PORT_LISTENER": r"GATEWAY_HOST_WEB_DEFAULT_PORT_LISTENER=(true|false)",
    "GATEWAY_CONTAINER_WEB_DEFAULT_PORT_LISTENER": r"GATEWAY_CONTAINER_WEB_DEFAULT_PORT_LISTENER=(true|false|unknown)",
}


_READONLY_API_PATTERNS = {
    "GATEWAY_READONLY_API_STATUS": r"GATEWAY_READONLY_API_STATUS=(observed|unavailable)",
    "GATEWAY_READONLY_API_REASON": r"GATEWAY_READONLY_API_REASON=(probe_failed|client_prerequisite_unavailable|api_session_ready|api_session_incomplete|api_session_timeout|api_connection_refused|api_probe_failed|native_transport_timeout|binding_invalid|probe_source_unavailable|native_execution_failed|native_response_invalid|contract_details_failed|contract_details_ready|contract_details_timeout|contract_details_disconnected|contract_details_rejected|contract_details_identity_mismatch|contract_details_empty|contract_details_ambiguous)",
    "GATEWAY_READONLY_API_CONNECTION_ATTEMPTS": r"GATEWAY_READONLY_API_CONNECTION_ATTEMPTS=(unknown|[01])",
    "GATEWAY_READONLY_API_SESSION_READY": r"GATEWAY_READONLY_API_SESSION_READY=(true|false)",
    "GATEWAY_READONLY_API_MANAGED_ACCOUNT_COUNT": r"GATEWAY_READONLY_API_MANAGED_ACCOUNT_COUNT=(unknown|[0-9]{1,4})",
    "GATEWAY_READONLY_API_LIMIT": r"GATEWAY_READONLY_API_LIMIT=NO_ACCOUNT_IDENTITY_OR_ORDER_CAPABILITY_ASSERTION",
}
_CONTRACT_DETAILS_PATTERNS = {
    "GATEWAY_CONTRACT_DETAILS_STATUS": r"GATEWAY_CONTRACT_DETAILS_STATUS=(unknown|not_requested|ready|empty|timeout|rejected|disconnected|identity_mismatch|ambiguous|probe_failed)",
    "GATEWAY_CONTRACT_DETAILS_REQUEST_ATTEMPTS": r"GATEWAY_CONTRACT_DETAILS_REQUEST_ATTEMPTS=(unknown|[01])",
    "GATEWAY_CONTRACT_DETAILS_RECORD_COUNT": r"GATEWAY_CONTRACT_DETAILS_RECORD_COUNT=(unknown|[0-9]{1,5})",
    "GATEWAY_CONTRACT_DETAILS_END_OBSERVED": r"GATEWAY_CONTRACT_DETAILS_END_OBSERVED=(unknown|true|false)",
    "GATEWAY_CONTRACT_DETAILS_IDENTITY_MATCH": r"GATEWAY_CONTRACT_DETAILS_IDENTITY_MATCH=(unknown|true|false)",
    "GATEWAY_CONTRACT_DETAILS_ERROR_CODES": r"GATEWAY_CONTRACT_DETAILS_ERROR_CODES=(none|unknown|(?:1100|1101|1102|2103|2104|2105|2106|2158|326|504|200|321|354|other)(?:,(?:1100|1101|1102|2103|2104|2105|2106|2158|326|504|200|321|354|other))*)",
}


def validate_gateway_ssh_response(lines: list[str], *, readonly_api: bool = False) -> str | None:
    """Return safe helper output or a fixed local response error."""

    if len(lines) == 1 and any(
        lines[0] == f"GATEWAY_CONNECTION_INSPECTION=blocked reason={reason}"
        for reason in _HELPER_BLOCKED_REASONS
    ):
        return lines[0]
    names = [line.split("=", 1)[0] for line in lines]
    patterns = dict(_READONLY_API_PATTERNS if readonly_api else _RESPONSE_PATTERNS)
    if readonly_api and set(names) & set(_CONTRACT_DETAILS_PATTERNS):
        patterns.update(_CONTRACT_DETAILS_PATTERNS)
    elif any(line.startswith("GATEWAY_READONLY_API_REASON=contract_details_") for line in lines):
        return None
    if not readonly_api and set(names) & set(_PRESENCE_PATTERNS):
        patterns.update(_PRESENCE_PATTERNS)
    if (
        len(lines) != len(patterns)
        or set(names) != set(patterns)
        or len(set(names)) != len(names)
        or any(
            not re.fullmatch(patterns.get(name, ""), line)
            for name, line in zip(names, lines)
        )
    ):
        return None
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdout-file", required=True, type=Path)
    parser.add_argument("--stderr-file", required=True, type=Path)
    parser.add_argument("--exit-code", required=True, type=int)
    parser.add_argument("--readonly-api", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.exit_code <= 255:
        print("GATEWAY_CONNECTION_INSPECTION=blocked reason=ssh_unknown exit_code=1")
        return 1
    if args.exit_code == 0:
        try:
            lines = args.stdout_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        response = validate_gateway_ssh_response(lines, readonly_api=args.readonly_api)
        if response is None:
            print("GATEWAY_CONNECTION_INSPECTION=blocked reason=remote_response_invalid")
            return 1
        print(response)
        return 1 if response.startswith("GATEWAY_CONNECTION_INSPECTION=blocked reason=") else 0
    try:
        lines = args.stdout_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    helper_response = validate_gateway_ssh_response(lines, readonly_api=args.readonly_api)
    if helper_response is not None and helper_response.startswith(
        "GATEWAY_CONNECTION_INSPECTION=blocked reason="
    ):
        print(helper_response)
        return 1
    try:
        message = args.stderr_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        message = ""
    category = "timeout" if args.exit_code == 124 else classify_gateway_ssh_failure(message)
    print(
        "GATEWAY_CONNECTION_INSPECTION=blocked "
        f"reason=ssh_{category} exit_code={args.exit_code}"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
