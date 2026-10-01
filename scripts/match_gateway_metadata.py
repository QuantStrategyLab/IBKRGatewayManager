"""Compare one authorized VM metadata response with the protected Gateway host."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


_PRIVATE_V4_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def _private_ipv4(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if parsed.version != 4 or not any(parsed in network for network in _PRIVATE_V4_NETWORKS):
        return None
    return str(parsed)


def compare_gateway_host(metadata: Any, expected_host: Any) -> str:
    """Return match/no_match only for a complete, valid private-IPv4 payload."""
    expected = _private_ipv4(expected_host)
    if expected is None or not isinstance(metadata, dict):
        return "unknown"
    interfaces = metadata.get("networkInterfaces")
    if not isinstance(interfaces, list) or not interfaces:
        return "unknown"

    addresses: list[str] = []
    for interface in interfaces:
        if not isinstance(interface, dict):
            return "unknown"
        address = _private_ipv4(interface.get("networkIP"))
        if address is None:
            return "unknown"
        addresses.append(address)
    return "match" if expected in addresses else "no_match"


def _compute_resource_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.googleapis.com"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
    ):
        return None
    return parsed.path


def compare_gateway_target_identity(
    metadata: Any, expected_project: Any, expected_zone: Any, expected_instance: Any
) -> tuple[str, str]:
    """Verify a describe response is the exact protected VM resource, then classify state."""
    if (
        not isinstance(expected_project, str)
        or not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", expected_project)
        or not isinstance(expected_zone, str)
        or not re.fullmatch(r"[a-z]+(?:-[a-z]+)*[0-9]+-[a-z]", expected_zone)
        or not isinstance(expected_instance, str)
        or not re.fullmatch(r"[a-z]([-a-z0-9]*[a-z0-9])?", expected_instance)
        or not isinstance(metadata, dict)
    ):
        return "UNKNOWN", "METADATA_IDENTITY_UNVERIFIED"

    expected_zone_path = f"/compute/v1/projects/{expected_project}/zones/{expected_zone}"
    expected_instance_path = f"{expected_zone_path}/instances/{expected_instance}"
    if (
        metadata.get("name") != expected_instance
        or _compute_resource_path(metadata.get("zone")) != expected_zone_path
        or _compute_resource_path(metadata.get("selfLink")) != expected_instance_path
    ):
        return "UNKNOWN", "METADATA_IDENTITY_UNVERIFIED"

    status = metadata.get("status")
    known_states = {
        "PROVISIONING",
        "STAGING",
        "RUNNING",
        "STOPPING",
        "SUSPENDING",
        "SUSPENDED",
        "REPAIRING",
        "TERMINATED",
    }
    if not isinstance(status, str) or status not in known_states:
        return "UNKNOWN", "METADATA_STATUS_UNKNOWN"
    return ("VM_RUNNING" if status == "RUNNING" else "VM_NOT_RUNNING"), "NONE"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-file", required=True, type=Path)
    parser.add_argument("--target-index", required=True, type=int)
    parser.add_argument("--verify-target-identity", action="store_true")
    args = parser.parse_args(argv)

    if args.verify_target_identity:
        status = "UNKNOWN"
        failure_class = "METADATA_IDENTITY_UNVERIFIED"
        metadata = None
        try:
            metadata = json.loads(args.metadata_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            failure_class = "METADATA_INVALID"
        if not 0 <= args.target_index < 4:
            failure_class = "METADATA_IDENTITY_UNVERIFIED"
        elif failure_class != "METADATA_INVALID":
            status, failure_class = compare_gateway_target_identity(
                metadata,
                os.environ.get("EXPECTED_GCP_PROJECT_ID"),
                os.environ.get("EXPECTED_GCE_ZONE"),
                os.environ.get("EXPECTED_GCE_INSTANCE_NAME"),
            )
        print(f"GATEWAY_VM_DIAGNOSTIC_STATUS={status}")
        print(f"GATEWAY_VM_DIAGNOSTIC_TARGET_INDEX={args.target_index if 0 <= args.target_index < 4 else 'unknown'}")
        if failure_class != "NONE":
            print(f"GATEWAY_VM_DIAGNOSTIC_FAILURE_CLASS={failure_class}")
        return 0 if status != "UNKNOWN" else 1

    status = "unknown"
    if 0 <= args.target_index < 4:
        expected = os.environ.get("IB_GATEWAY_EXPECTED_HOST")
        try:
            metadata = json.loads(args.metadata_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            metadata = None
        status = compare_gateway_host(metadata, expected)

    print(f"GATEWAY_IP_MATCH_STATUS={status}")
    print(f"GATEWAY_IP_MATCH_INDEX={args.target_index if 0 <= args.target_index < 4 else 'unknown'}")
    return 1 if status == "unknown" else 0


if __name__ == "__main__":
    raise SystemExit(main())
