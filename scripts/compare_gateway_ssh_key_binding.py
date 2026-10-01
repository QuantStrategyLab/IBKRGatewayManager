"""Compare a private-key-derived public key with effective VM SSH-key metadata."""

from __future__ import annotations

import argparse
import base64
import binascii
import importlib.util
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


_POLICY_PATH = Path(__file__).with_name("parse_gateway_ssh_policy.py")
_POLICY_SPEC = importlib.util.spec_from_file_location("gateway_ssh_policy", _POLICY_PATH)
if _POLICY_SPEC is None or _POLICY_SPEC.loader is None:  # pragma: no cover - packaging guard
    raise RuntimeError("SSH policy parser unavailable")
_POLICY = importlib.util.module_from_spec(_POLICY_SPEC)
_POLICY_SPEC.loader.exec_module(_POLICY)


class BindingError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _metadata_items(document: Any, section: str) -> dict[str, str]:
    try:
        return _POLICY._items(document, section)
    except _POLICY.PolicyError:
        raise BindingError("metadata_invalid") from None


def _derived_public_key(private_key_file: Path) -> tuple[str, str]:
    try:
        result = subprocess.run(
            ["ssh-keygen", "-y", "-P", "", "-f", str(private_key_file)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise BindingError("key_invalid") from None
    fields = result.stdout.split()
    if len(fields) < 2 or not re.fullmatch(r"[A-Za-z0-9@._+-]{1,80}", fields[0]):
        raise BindingError("key_invalid")
    try:
        decoded = base64.b64decode(fields[1], validate=True)
    except (binascii.Error, ValueError):
        raise BindingError("key_invalid") from None
    if not decoded:
        raise BindingError("key_invalid")
    return fields[0], fields[1]


def _parse_expiry(suffix: str) -> datetime | None:
    marker = re.search(r"(?:^|\s)google-ssh\s+(\{.*\})\s*$", suffix)
    if marker is None:
        if "google-ssh" in suffix:
            raise BindingError("metadata_invalid")
        return None
    try:
        def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise BindingError("metadata_invalid")
                result[key] = value
            return result

        payload = json.loads(marker.group(1), object_pairs_hook=reject_duplicate_pairs)
    except BindingError:
        raise
    except json.JSONDecodeError:
        raise BindingError("metadata_invalid") from None
    if not isinstance(payload, dict):
        raise BindingError("metadata_invalid")
    if not isinstance(payload.get("userName"), str) or not isinstance(payload.get("expireOn"), str):
        raise BindingError("metadata_invalid")
    value = payload["expireOn"]
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})",
        value,
    ):
        raise BindingError("metadata_invalid")
    if re.search(r"[+-]\d{4}$", value):
        value = value[:-2] + ":" + value[-2:]
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        raise BindingError("metadata_invalid") from None
    if parsed.tzinfo is None:
        raise BindingError("metadata_invalid")
    return parsed.astimezone(UTC)


def _source_matches(
    value: str,
    username: str,
    public_key: tuple[str, str],
    now: datetime,
) -> tuple[bool, bool]:
    expired_match = False
    for line in value.splitlines():
        if not line:
            continue
        if ":" not in line:
            raise BindingError("metadata_invalid")
        line_username, key_and_suffix = line.split(":", 1)
        fields = key_and_suffix.split(None, 2)
        if (
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", line_username)
            or len(fields) < 2
            or not re.fullmatch(r"[A-Za-z0-9@._+-]{1,80}", fields[0])
        ):
            raise BindingError("metadata_invalid")
        try:
            blob = base64.b64decode(fields[1], validate=True)
        except (binascii.Error, ValueError):
            raise BindingError("metadata_invalid") from None
        if not blob:
            raise BindingError("metadata_invalid")
        suffix = fields[2] if len(fields) == 3 else ""
        expiry = _parse_expiry(suffix)
        google_username_match = re.search(r"(?:^|\s)google-ssh\s+(\{.*\})\s*$", suffix)
        if google_username_match:
            metadata_user = json.loads(google_username_match.group(1)).get("userName")
            if metadata_user is not None and metadata_user != line_username:
                raise BindingError("metadata_invalid")
        if line_username != username or (fields[0], fields[1]) != public_key:
            continue
        if expiry is not None and expiry <= now:
            expired_match = True
        else:
            return True, expired_match
    return False, expired_match


def compare_binding(
    private_key_file: Path,
    username: str,
    instance_document: Any,
    project_document: Any,
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    """Return only a fixed result/source/reason; never return key or metadata content."""
    try:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", username):
            raise BindingError("username_invalid")
        current_time = now or datetime.now(UTC)
        if current_time.tzinfo is None:
            raise BindingError("metadata_invalid")
        instance = _metadata_items(instance_document, "metadata")
        project = _metadata_items(project_document, "commonInstanceMetadata")
        try:
            policy = _POLICY.parse_policy(instance_document, project_document)
        except _POLICY.PolicyError:
            raise BindingError("metadata_invalid") from None
        if policy["enable_oslogin"] == "enabled":
            raise BindingError("oslogin_enabled")

        public_key = _derived_public_key(private_key_file)
        found_expired = False
        for source, items in (("instance", instance), ("project", project)):
            if source == "project" and policy["block_project_ssh_keys"] == "enabled":
                continue
            if "ssh-keys" not in items:
                continue
            matched, expired = _source_matches(
                items["ssh-keys"], username, public_key, current_time.astimezone(UTC)
            )
            found_expired = found_expired or expired
            if matched:
                return {"status": "match", "source": source, "reason": "matched"}
        if found_expired:
            return {"status": "no_match", "source": "none", "reason": "key_expired"}
        return {"status": "no_match", "source": "none", "reason": "key_not_found"}
    except BindingError as exc:
        return {"status": "unknown", "source": "unknown", "reason": exc.reason}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise BindingError("metadata_invalid") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-key-file", required=True, type=Path)
    parser.add_argument("--instance-file", required=True, type=Path)
    parser.add_argument("--project-file", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = compare_binding(
            args.private_key_file,
            os.environ.get("GCE_USER", ""),
            _read_json(args.instance_file),
            _read_json(args.project_file),
        )
    except BindingError as exc:
        result = {"status": "unknown", "source": "unknown", "reason": exc.reason}
    print(f"SSH_KEY_BINDING={result['status']}")
    print(f"SSH_KEY_BINDING_SOURCE={result['source']}")
    print(f"SSH_KEY_BINDING_REASON={result['reason']}")
    return 1 if result["status"] == "unknown" else 0


if __name__ == "__main__":
    raise SystemExit(main())
