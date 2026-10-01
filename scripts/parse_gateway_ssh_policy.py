"""Parse effective SSH policy from synthetic-safe gcloud metadata JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class PolicyError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _items(document: Any, section: str) -> dict[str, str]:
    if not isinstance(document, dict) or not isinstance(document.get(section), dict):
        raise PolicyError("metadata_malformed")
    items = document[section].get("items", [])
    if not isinstance(items, list):
        raise PolicyError("metadata_malformed")
    result: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise PolicyError("metadata_malformed")
        key = item["key"]
        if key in result:
            raise PolicyError("duplicate_metadata_key")
        value = item.get("value")
        if not isinstance(value, str):
            raise PolicyError("metadata_malformed")
        result[key] = value
    return result


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise PolicyError("metadata_unavailable") from None


def _bool_value(items: dict[str, str], key: str, source: str) -> tuple[str, str]:
    if key not in items:
        return "disabled", "default"
    value = items[key]
    if value == "TRUE":
        return "enabled", source
    if value == "FALSE":
        return "disabled", source
    raise PolicyError("metadata_value_invalid")


def parse_policy(instance_document: Any, project_document: Any) -> dict[str, str]:
    instance = _items(instance_document, "metadata")
    project = _items(project_document, "commonInstanceMetadata")

    if "block-project-ssh-keys" in project:
        raise PolicyError("unexpected_project_key")

    if "enable-oslogin" in instance:
        oslogin = _bool_value(instance, "enable-oslogin", "instance")
    elif "enable-oslogin" in project:
        oslogin = _bool_value(project, "enable-oslogin", "project")
    else:
        oslogin = ("disabled", "default")

    block_project_keys = _bool_value(instance, "block-project-ssh-keys", "instance")
    return {
        "enable_oslogin": oslogin[0],
        "enable_oslogin_source": oslogin[1],
        "block_project_ssh_keys": block_project_keys[0],
        "block_project_ssh_keys_source": block_project_keys[1],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-file", required=True, type=Path)
    parser.add_argument("--project-file", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        policy = parse_policy(_read(args.instance_file), _read(args.project_file))
    except PolicyError as exc:
        print("SSH_POLICY_ENABLE_OSLOGIN=unknown")
        print("SSH_POLICY_ENABLE_OSLOGIN_SOURCE=unknown")
        print("SSH_POLICY_BLOCK_PROJECT_SSH_KEYS=unknown")
        print("SSH_POLICY_BLOCK_PROJECT_SSH_KEYS_SOURCE=unknown")
        print(f"SSH_POLICY=blocked reason={exc.reason}")
        return 1

    print(f"SSH_POLICY_ENABLE_OSLOGIN={policy['enable_oslogin']}")
    print(f"SSH_POLICY_ENABLE_OSLOGIN_SOURCE={policy['enable_oslogin_source']}")
    print(f"SSH_POLICY_BLOCK_PROJECT_SSH_KEYS={policy['block_project_ssh_keys']}")
    print(f"SSH_POLICY_BLOCK_PROJECT_SSH_KEYS_SOURCE={policy['block_project_ssh_keys_source']}")
    print("SSH_POLICY=verified reason=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
