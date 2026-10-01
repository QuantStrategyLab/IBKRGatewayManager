from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREPARE_KEY = ROOT / "scripts" / "prepare_gateway_ssh_key.sh"
CLASSIFIER = ROOT / "scripts" / "classify_gateway_ssh_failure.py"
WORKFLOW = ROOT / ".github" / "workflows" / "read-only-vm-metadata-diagnostic.yml"


def _make_key(path: Path, passphrase: str = "") -> None:
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", passphrase, "-f", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    path.with_suffix(path.suffix + ".pub").unlink()


def _prepare_key(path: Path, runner_temp: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "SSH_KEY_FILE": str(path), "RUNNER_TEMP": str(runner_temp)}
    return subprocess.run(
        ["bash", str(PREPARE_KEY)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _classify(
    tmp_path: Path, stderr: str, exit_code: int, stdout: str = ""
) -> subprocess.CompletedProcess[str]:
    stdout_file = tmp_path / "ssh.stdout"
    stderr_file = tmp_path / "ssh.stderr"
    stdout_file.write_text(stdout, encoding="utf-8")
    stderr_file.write_text(stderr, encoding="utf-8")
    return subprocess.run(
        [
            "python3",
            str(CLASSIFIER),
            "--stdout-file",
            str(stdout_file),
            "--stderr-file",
            str(stderr_file),
            "--exit-code",
            str(exit_code),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


class GatewaySshFailureDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_crlf_key_is_normalized_and_preflighted_without_outputting_key(self) -> None:
        key_file = self.tmp_path / "private-key"
        _make_key(key_file)
        original = key_file.read_bytes()
        key_file.write_bytes(original.replace(b"\n", b"\r\n"))

        result = _prepare_key(key_file, self.tmp_path)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "GATEWAY_SSH_KEY_STATUS=ready\n")
        self.assertEqual(result.stderr, "")
        self.assertNotIn(b"\r", key_file.read_bytes())
        self.assertIn(b"PRIVATE KEY", key_file.read_bytes())
        check = subprocess.run(
            ["ssh-keygen", "-y", "-P", "", "-f", str(key_file)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertTrue(check.stdout.startswith("ssh-ed25519 "))
        self.assertNotIn("PRIVATE KEY", result.stdout + result.stderr)

    def test_crlf_key_without_final_lf_is_repaired_without_changing_public_key(self) -> None:
        key_file = self.tmp_path / "private-key-no-eof-lf"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key_file)],
            check=True,
            capture_output=True,
            text=True,
        )
        expected_public_key = key_file.with_suffix(key_file.suffix + ".pub").read_text(encoding="utf-8").split()[:2]
        key_file.with_suffix(key_file.suffix + ".pub").unlink()
        original = key_file.read_bytes()
        key_file.write_bytes(original.replace(b"\n", b"\r\n").rstrip(b"\r\n"))

        result = _prepare_key(key_file, self.tmp_path)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "GATEWAY_SSH_KEY_STATUS=ready\n")
        self.assertEqual(result.stderr, "")
        normalized = key_file.read_bytes()
        self.assertNotIn(b"\r", normalized)
        self.assertTrue(normalized.endswith(b"\n"))
        derived = subprocess.run(
            ["ssh-keygen", "-y", "-P", "", "-f", str(key_file)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()[:2]
        self.assertEqual(derived, expected_public_key)
        self.assertNotIn(expected_public_key[1], result.stdout + result.stderr)

    def test_invalid_and_encrypted_keys_fail_closed_and_are_removed(self) -> None:
        runner_temp = self.tmp_path / "runner-temp"
        runner_temp.mkdir()
        invalid_key = self.tmp_path / "invalid-key"
        invalid_marker = "synthetic-private-material-marker"
        invalid_key.write_text(
            f"-----BEGIN PRIVATE KEY-----\n{invalid_marker}\n", encoding="utf-8"
        )

        invalid_result = _prepare_key(invalid_key, runner_temp)

        self.assertNotEqual(invalid_result.returncode, 0)
        self.assertEqual(
            invalid_result.stdout,
            "GATEWAY_CONNECTION_INSPECTION=blocked reason=credential_invalid\n",
        )
        self.assertFalse(invalid_key.exists())
        self.assertNotIn(invalid_marker, invalid_result.stdout + invalid_result.stderr)

        encrypted_key = self.tmp_path / "encrypted-key"
        passphrase_marker = "synthetic-passphrase-marker"
        _make_key(encrypted_key, passphrase_marker)
        encrypted_result = _prepare_key(encrypted_key, runner_temp)

        self.assertNotEqual(encrypted_result.returncode, 0)
        self.assertEqual(
            encrypted_result.stdout,
            "GATEWAY_CONNECTION_INSPECTION=blocked reason=credential_invalid\n",
        )
        self.assertFalse(encrypted_key.exists())
        self.assertNotIn(passphrase_marker, encrypted_result.stdout + encrypted_result.stderr)
        self.assertEqual(list(runner_temp.iterdir()), [])

    def test_ssh_stderr_maps_to_closed_categories_and_hides_raw_text(self) -> None:
        examples = {
            "timeout": "ssh: connect to host synthetic.invalid port 22: Connection timed out",
            "key_invalid": 'Load key "synthetic-path": invalid format; hidden-key-marker',
            "auth_denied": "Permission denied (publickey); hidden-auth-marker",
            "iap_denied": "ERROR: gcloud.compute.start-iap-tunnel Error while connecting [4033: not authorized]",
            "iap_transport": "start-iap-tunnel failed to connect to backend; hidden-endpoint-marker",
        }
        for category, error_text in examples.items():
            with self.subTest(category=category):
                result = _classify(self.tmp_path, error_text, 255)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(
                    result.stdout,
                    f"GATEWAY_CONNECTION_INSPECTION=blocked reason=ssh_{category} exit_code=255\n",
                )
                self.assertNotIn(error_text, result.stdout + result.stderr)
                self.assertNotIn("hidden-", result.stdout + result.stderr)

    def test_ambiguous_or_unrecognized_errors_fall_back_to_unknown(self) -> None:
        for error_text in (
            "unrecognized provider detail hidden-provider-marker",
            "Connection timed out; Permission denied (publickey)",
        ):
            with self.subTest(error_text=error_text):
                result = _classify(self.tmp_path, error_text, 255)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(
                    result.stdout,
                    "GATEWAY_CONNECTION_INSPECTION=blocked reason=ssh_unknown exit_code=255\n",
                )
                self.assertNotIn(error_text, result.stdout + result.stderr)

        timed_out = _classify(self.tmp_path, "", 124)
        self.assertEqual(
            timed_out.stdout,
            "GATEWAY_CONNECTION_INSPECTION=blocked reason=ssh_timeout exit_code=124\n",
        )

    def test_successful_response_and_helper_block_retain_only_fixed_fields(self) -> None:
        valid = "\n".join(
            (
                "GATEWAY_CONNECTION_INSPECTION=observed",
                "GATEWAY_CONTAINER_RUNNING=true",
                "GATEWAY_API_LISTENER=true",
                "GATEWAY_ESTABLISHED_CONNECTION_COUNT=2",
                "GATEWAY_CONNECTION_OBSERVED_AT_UTC=2026-10-01T00:00:00Z",
                "GATEWAY_CONNECTION_INSPECTION_LIMIT=OBSERVATION_ONLY_NO_AUTH_OR_CONCURRENCY_ASSERTION",
            )
        )
        result = _classify(self.tmp_path, "", 0, valid)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, f"{valid}\n")

        helper_error = "GATEWAY_CONNECTION_INSPECTION=blocked reason=socket_inspection_failed"
        result = _classify(self.tmp_path, "", 1, helper_error)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, f"{helper_error}\n")
        result = _classify(self.tmp_path, "", 0, helper_error)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, f"{helper_error}\n")

        untrusted_reason = "GATEWAY_CONNECTION_INSPECTION=blocked reason=made_up_sensitive_detail"
        result = _classify(self.tmp_path, "", 0, untrusted_reason)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout,
            "GATEWAY_CONNECTION_INSPECTION=blocked reason=remote_response_invalid\n",
        )
        self.assertNotIn("sensitive", result.stdout + result.stderr)

    def test_workflow_uses_helpers_and_retains_single_bounded_ssh_path(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("bash scripts/prepare_gateway_ssh_key.sh", workflow)
        self.assertIn("scripts/classify_gateway_ssh_failure.py", workflow)
        self.assertIn('--stdout-file "${output_file}"', workflow)
        self.assertIn('--stderr-file "${error_file}"', workflow)
        self.assertIn("timeout 75 ssh", workflow)
        self.assertIn("ConnectionAttempts=1", workflow)
        self.assertIn("gcloud compute instances describe", workflow)
        self.assertIn('"${match_status}" != "match"', workflow)
        self.assertIn("always() && inputs.inspect_connections", workflow)
        self.assertIn("gcloud compute start-iap-tunnel", workflow)
        self.assertNotIn("gcloud compute ssh", workflow)


if __name__ == "__main__":
    unittest.main()
