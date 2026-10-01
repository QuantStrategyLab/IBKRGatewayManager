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
}


def validate_gateway_ssh_response(lines: list[str]) -> str | None:
    """Return safe helper output or a fixed local response error."""

    if len(lines) == 1 and any(
        lines[0] == f"GATEWAY_CONNECTION_INSPECTION=blocked reason={reason}"
        for reason in _HELPER_BLOCKED_REASONS
    ):
        return lines[0]
    names = [line.split("=", 1)[0] for line in lines]
    if (
        len(lines) != len(_RESPONSE_PATTERNS)
        or set(names) != set(_RESPONSE_PATTERNS)
        or len(set(names)) != len(names)
        or any(
            not re.fullmatch(_RESPONSE_PATTERNS.get(name, ""), line)
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
    args = parser.parse_args(argv)
    if not 0 <= args.exit_code <= 255:
        print("GATEWAY_CONNECTION_INSPECTION=blocked reason=ssh_unknown exit_code=1")
        return 1
    if args.exit_code == 0:
        try:
            lines = args.stdout_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        response = validate_gateway_ssh_response(lines)
        if response is None:
            print("GATEWAY_CONNECTION_INSPECTION=blocked reason=remote_response_invalid")
            return 1
        print(response)
        return 1 if response.startswith("GATEWAY_CONNECTION_INSPECTION=blocked reason=") else 0
    try:
        lines = args.stdout_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    helper_response = validate_gateway_ssh_response(lines)
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
