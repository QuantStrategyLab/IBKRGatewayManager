from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "match_gateway_metadata.py"
SPEC = importlib.util.spec_from_file_location("match_gateway_metadata", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _metadata(*addresses: str) -> dict[str, object]:
    return {"networkInterfaces": [{"networkIP": address} for address in addresses]}


def _target_metadata(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "mock-gateway-a",
        "zone": "https://www.googleapis.com/compute/v1/projects/mock-project-a/zones/us-central1-a",
        "selfLink": "https://www.googleapis.com/compute/v1/projects/mock-project-a/zones/us-central1-a/instances/mock-gateway-a",
        "status": "RUNNING",
        "networkInterfaces": [{"networkIP": "10.1.2.3"}],
    }
    payload.update(overrides)
    return payload


class GatewayMetadataMatchTests(unittest.TestCase):
    def test_exact_compute_resource_identity_and_closed_status(self):
        self.assertEqual(
            MODULE.compare_gateway_target_identity(
                _target_metadata(), "mock-project-a", "us-central1-a", "mock-gateway-a"
            ),
            ("VM_RUNNING", "NONE"),
        )
        stopped = _target_metadata(status="TERMINATED")
        self.assertEqual(
            MODULE.compare_gateway_target_identity(
                stopped, "mock-project-a", "us-central1-a", "mock-gateway-a"
            ),
            ("VM_NOT_RUNNING", "NONE"),
        )

    def test_identity_mismatch_or_untrusted_uri_fails_closed(self):
        cases = [
            (_target_metadata(), "other-project", "us-central1-a", "mock-gateway-a"),
            (_target_metadata(), "mock-project-a", "us-east1-b", "mock-gateway-a"),
            (_target_metadata(), "mock-project-a", "us-central1-a", "other-gateway"),
            (_target_metadata(zone="https://attacker.invalid/compute/v1/projects/mock-project-a/zones/us-central1-a"),
             "mock-project-a", "us-central1-a", "mock-gateway-a"),
            (_target_metadata(selfLink="https://www.googleapis.com/compute/v1/projects/other-project/zones/us-central1-a/instances/mock-gateway-a"),
             "mock-project-a", "us-central1-a", "mock-gateway-a"),
            (_target_metadata(selfLink="https://www.googleapis.com/compute/v1/projects/mock-project-a/zones/us-central1-a/instances/mock-gateway-a?redirect=1"),
             "mock-project-a", "us-central1-a", "mock-gateway-a"),
            (_target_metadata(status="UNKNOWN_STATE"), "mock-project-a", "us-central1-a", "mock-gateway-a"),
            (None, "mock-project-a", "us-central1-a", "mock-gateway-a"),
        ]
        for payload, project, zone, instance in cases:
            with self.subTest(project=project, zone=zone, instance=instance):
                status, reason = MODULE.compare_gateway_target_identity(payload, project, zone, instance)
                self.assertEqual(status, "UNKNOWN")
                self.assertIn(reason, {"METADATA_IDENTITY_UNVERIFIED", "METADATA_STATUS_UNKNOWN"})

    def test_identity_cli_outputs_only_closed_status_index_and_failure_class(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temp_dir:
            metadata_file = Path(temp_dir) / "metadata.json"
            metadata_file.write_text(json.dumps(_target_metadata()), encoding="utf-8")
            environment = {
                **os.environ,
                "EXPECTED_GCP_PROJECT_ID": "mock-project-a",
                "EXPECTED_GCE_ZONE": "us-central1-a",
                "EXPECTED_GCE_INSTANCE_NAME": "mock-gateway-a",
            }
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--metadata-file", str(metadata_file), "--target-index", "3", "--verify-target-identity"],
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )

        self.assertEqual(
            completed.stdout.splitlines(),
            ["GATEWAY_VM_DIAGNOSTIC_STATUS=VM_RUNNING", "GATEWAY_VM_DIAGNOSTIC_TARGET_INDEX=3"],
        )
        for private_fixture_value in ("mock-project-a", "mock-gateway-a", "10.1.2.3", "selfLink", "networkInterfaces"):
            self.assertNotIn(private_fixture_value, completed.stdout + completed.stderr)

    def test_identity_cli_mismatch_is_unknown_without_metadata_leak(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temp_dir:
            metadata_file = Path(temp_dir) / "metadata.json"
            metadata_file.write_text(json.dumps(_target_metadata()), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--metadata-file", str(metadata_file), "--target-index", "1", "--verify-target-identity"],
                env={
                    **os.environ,
                    "EXPECTED_GCP_PROJECT_ID": "mock-project-b",
                    "EXPECTED_GCE_ZONE": "us-central1-a",
                    "EXPECTED_GCE_INSTANCE_NAME": "mock-gateway-a",
                },
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(
            completed.stdout.splitlines(),
            [
                "GATEWAY_VM_DIAGNOSTIC_STATUS=UNKNOWN",
                "GATEWAY_VM_DIAGNOSTIC_TARGET_INDEX=1",
                "GATEWAY_VM_DIAGNOSTIC_FAILURE_CLASS=METADATA_IDENTITY_UNVERIFIED",
            ],
        )
        self.assertNotIn("mock-project-a", completed.stdout + completed.stderr)
        self.assertNotIn("mock-gateway-a", completed.stdout + completed.stderr)
        self.assertNotIn("10.1.2.3", completed.stdout + completed.stderr)

    def test_identity_cli_invalid_json_uses_fixed_failure_category(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temp_dir:
            metadata_file = Path(temp_dir) / "metadata.json"
            metadata_file.write_text('{"private":"fixture-value"', encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--metadata-file", str(metadata_file), "--target-index", "0", "--verify-target-identity"],
                env={
                    **os.environ,
                    "EXPECTED_GCP_PROJECT_ID": "mock-project-a",
                    "EXPECTED_GCE_ZONE": "us-central1-a",
                    "EXPECTED_GCE_INSTANCE_NAME": "mock-gateway-a",
                },
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(
            completed.stdout.splitlines(),
            [
                "GATEWAY_VM_DIAGNOSTIC_STATUS=UNKNOWN",
                "GATEWAY_VM_DIAGNOSTIC_TARGET_INDEX=0",
                "GATEWAY_VM_DIAGNOSTIC_FAILURE_CLASS=METADATA_INVALID",
            ],
        )
        self.assertNotIn("fixture-value", completed.stdout + completed.stderr)

    def test_actual_metadata_payload_validation(self):
        cases = [
            (_metadata("10.1.2.3"), "10.1.2.3", "match"),
            (_metadata("10.1.2.3", "192.168.4.5"), "192.168.4.5", "match"),
            (_metadata("10.1.2.3"), "10.1.2.4", "no_match"),
            ({}, "10.1.2.3", "unknown"),
            ({"networkInterfaces": []}, "10.1.2.3", "unknown"),
            ({"networkInterfaces": [None]}, "10.1.2.3", "unknown"),
            ({"networkInterfaces": [{"networkIP": "not-an-ip"}]}, "10.1.2.3", "unknown"),
            ({"networkInterfaces": [{"networkIP": "2001:db8::1"}]}, "10.1.2.3", "unknown"),
            ({"networkInterfaces": [{"networkIP": "8.8.8.8"}]}, "10.1.2.3", "unknown"),
            (_metadata("10.1.2.3"), "8.8.8.8", "unknown"),
            (_metadata("10.1.2.3"), "2001:db8::1", "unknown"),
        ]
        for payload, expected, status in cases:
            with self.subTest(payload=payload, expected=expected):
                self.assertEqual(MODULE.compare_gateway_host(payload, expected), status)

    def test_multiple_targets_can_match_and_cannot_be_declared_unique_locally(self):
        statuses = [
            MODULE.compare_gateway_host(_metadata("10.1.2.3"), "10.1.2.3"),
            MODULE.compare_gateway_host(_metadata("10.1.2.3", "192.168.4.5"), "10.1.2.3"),
            MODULE.compare_gateway_host(_metadata("10.1.2.4"), "10.1.2.3"),
            MODULE.compare_gateway_host(_metadata("10.1.2.5"), "10.1.2.3"),
        ]
        self.assertEqual(statuses.count("match"), 2)
        self.assertEqual(statuses.count("no_match"), 2)

    def test_cli_reads_expected_host_from_environment_and_emits_only_fixed_fields(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temp_dir:
            metadata_file = Path(temp_dir) / "metadata.json"
            metadata_file.write_text(json.dumps(_metadata("10.34.56.78")), encoding="utf-8")
            sentinel = "10.34.56.78"
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--metadata-file", str(metadata_file), "--target-index", "2"],
                env={**os.environ, "IB_GATEWAY_EXPECTED_HOST": sentinel},
                capture_output=True,
                text=True,
                check=True,
            )

        self.assertEqual(
            completed.stdout.splitlines(),
            ["GATEWAY_IP_MATCH_STATUS=match", "GATEWAY_IP_MATCH_INDEX=2"],
        )
        self.assertNotIn(sentinel, completed.stdout + completed.stderr)
        self.assertNotIn("networkInterfaces", completed.stdout + completed.stderr)

    def test_cli_missing_expected_host_fails_closed_with_only_unknown(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temp_dir:
            metadata_file = Path(temp_dir) / "metadata.json"
            metadata_file.write_text(json.dumps(_metadata("10.34.56.78")), encoding="utf-8")
            environment = dict(os.environ)
            environment.pop("IB_GATEWAY_EXPECTED_HOST", None)
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--metadata-file", str(metadata_file), "--target-index", "0"],
                env=environment,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(
            completed.stdout.splitlines(),
            ["GATEWAY_IP_MATCH_STATUS=unknown", "GATEWAY_IP_MATCH_INDEX=0"],
        )

    def test_cli_rejects_out_of_range_index_without_echoing_it(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temp_dir:
            metadata_file = Path(temp_dir) / "metadata.json"
            metadata_file.write_text(json.dumps(_metadata("10.34.56.78")), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--metadata-file", str(metadata_file), "--target-index", "999"],
                env={**os.environ, "IB_GATEWAY_EXPECTED_HOST": "10.34.56.78"},
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(
            completed.stdout.splitlines(),
            ["GATEWAY_IP_MATCH_STATUS=unknown", "GATEWAY_IP_MATCH_INDEX=unknown"],
        )
        self.assertNotIn("999", completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
