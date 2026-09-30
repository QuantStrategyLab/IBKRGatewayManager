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


class GatewayMetadataMatchTests(unittest.TestCase):
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
