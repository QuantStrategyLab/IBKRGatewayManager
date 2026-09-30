"""Compare one authorized VM metadata response with the protected Gateway host."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
from typing import Any


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-file", required=True, type=Path)
    parser.add_argument("--target-index", required=True, type=int)
    args = parser.parse_args(argv)

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
