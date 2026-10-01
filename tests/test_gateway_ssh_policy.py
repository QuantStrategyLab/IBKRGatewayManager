from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "parse_gateway_ssh_policy.py"
WORKFLOW = ROOT / ".github" / "workflows" / "read-only-vm-metadata-diagnostic.yml"
SPEC = importlib.util.spec_from_file_location("parse_gateway_ssh_policy", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def instance(*pairs: tuple[str, str]) -> dict[str, Any]:
    return {"metadata": {"items": [{"key": key, "value": value} for key, value in pairs]}}


def project(*pairs: tuple[str, str]) -> dict[str, Any]:
    return {"commonInstanceMetadata": {"items": [{"key": key, "value": value} for key, value in pairs]}}


def ssh_policy_run_script() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        r"(?ms)^      - id: ssh_policy\n.*?^        run: \|\n(.*?)(?=^      - |\Z)",
        text,
    )
    if not match:
        raise AssertionError("SSH policy run step not found")
    return textwrap.dedent(match.group(1))


class GatewaySshPolicyParserTests(unittest.TestCase):
    def test_oslogin_instance_overrides_project_and_project_supplies_value(self):
        self.assertEqual(
            MODULE.parse_policy(instance(("enable-oslogin", "FALSE")), project(("enable-oslogin", "TRUE")))[
                "enable_oslogin"
            ],
            "disabled",
        )
        self.assertEqual(
            MODULE.parse_policy(instance(), project(("enable-oslogin", "TRUE")))["enable_oslogin_source"],
            "project",
        )

    def test_absent_values_use_documented_defaults(self):
        result = MODULE.parse_policy(instance(), project())
        self.assertEqual(result["enable_oslogin"], "disabled")
        self.assertEqual(result["enable_oslogin_source"], "default")
        self.assertEqual(result["block_project_ssh_keys"], "disabled")
        self.assertEqual(result["block_project_ssh_keys_source"], "default")

    def test_supported_boolean_values_are_exact_case_sensitive_tokens(self):
        for token, expected in (("TRUE", "enabled"), ("FALSE", "disabled")):
            with self.subTest(token=token):
                result = MODULE.parse_policy(
                    instance(("block-project-ssh-keys", token)), project()
                )
                self.assertEqual(result["block_project_ssh_keys"], expected)
                self.assertEqual(result["block_project_ssh_keys_source"], "instance")

    def test_duplicate_malformed_or_noncanonical_values_fail_closed(self):
        invalid_instances = [
            instance(("enable-oslogin", "TRUE"), ("enable-oslogin", "FALSE")),
            instance(("enable-oslogin", "true")),
            instance(("enable-oslogin", "TRUE\n")),
            {"metadata": {"items": "invalid"}},
            {"metadata": {"items": [{"key": "enable-oslogin"}]}},
        ]
        for payload in invalid_instances:
            with self.subTest(payload=payload), self.assertRaises(MODULE.PolicyError):
                MODULE.parse_policy(payload, project())

    def test_project_and_instance_duplicate_keys_are_rejected(self):
        cases = [
            (instance(("enable-oslogin", "TRUE"), ("enable-oslogin", "TRUE")), project()),
            (instance(), project(("enable-oslogin", "TRUE"), ("enable-oslogin", "FALSE"))),
        ]
        for instance_doc, project_doc in cases:
            with self.subTest(instance_doc=instance_doc, project_doc=project_doc), self.assertRaises(
                MODULE.PolicyError
            ):
                MODULE.parse_policy(instance_doc, project_doc)

    def test_project_block_ssh_key_metadata_never_becomes_effective(self):
        with self.assertRaises(MODULE.PolicyError) as context:
            MODULE.parse_policy(instance(), project(("block-project-ssh-keys", "TRUE")))
        self.assertEqual(context.exception.reason, "unexpected_project_key")

    def test_cli_failure_emits_only_fixed_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            instance_file = Path(directory) / "instance.json"
            project_file = Path(directory) / "project.json"
            instance_file.write_text(json.dumps(instance(("enable-oslogin", "TRUE\n"))), encoding="utf-8")
            project_file.write_text(json.dumps(project()), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--instance-file", str(instance_file), "--project-file", str(project_file)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "SSH_POLICY_ENABLE_OSLOGIN=unknown",
                "SSH_POLICY_ENABLE_OSLOGIN_SOURCE=unknown",
                "SSH_POLICY_BLOCK_PROJECT_SSH_KEYS=unknown",
                "SSH_POLICY_BLOCK_PROJECT_SSH_KEYS_SOURCE=unknown",
                "SSH_POLICY=blocked reason=metadata_value_invalid",
            ],
        )
        self.assertEqual(result.stderr, "")


class GatewaySshPolicyWorkflowTests(unittest.TestCase):
    def _run_embedded_policy_step(
        self, fail_command: str | None = None, instance_ip: str = "10.20.30.40"
    ) -> tuple[subprocess.CompletedProcess[str], list[str], list[str]]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            call_log = root / "calls.log"
            fake_gcloud = bin_dir / "gcloud"
            fake_gcloud.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, pathlib, sys\n"
                "args=sys.argv[1:]\n"
                "with open(os.environ['FAKE_GCLOUD_LOG'], 'a', encoding='utf-8') as f: f.write(' '.join(args[:3])+'\\n')\n"
                f"if {fail_command!r} and len(args) > 1 and args[1] == {fail_command!r}:\n"
                " print('PRIVATE_PROVIDER_ERROR_DO_NOT_SHOW', file=sys.stderr); sys.exit(1)\n"
                "if args[:2] == ['compute','instances']:\n"
                " print(json.dumps({'networkInterfaces':[{'networkIP':os.environ['FAKE_INSTANCE_IP']}], 'metadata': {'items': [{'key':'enable-oslogin','value':'TRUE'}]}}))\n"
                "elif args[:2] == ['compute','project-info']:\n"
                " print(json.dumps({'commonInstanceMetadata': {'items': []}}))\n"
                "else: sys.exit(2)\n",
                encoding="utf-8",
            )
            fake_gcloud.chmod(0o700)
            runner_temp = root / "runner-temp"
            runner_temp.mkdir()
            isolated_env = {
                key: value for key, value in os.environ.items()
                if key not in {
                    "INSPECT_SSH_KEY_BINDING",
                    "SSH_PRIVATE_KEY_SECRET_NAME",
                    "GCP_SECRET_PROJECT_ID",
                    "GCE_USER",
                }
            }
            environment = {
                **isolated_env,
                "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                "GCP_PROJECT_ID": "synthetic-project",
                "GCE_INSTANCE_NAME": "synthetic-instance",
                "GCE_ZONE": "us-central1-a",
                "TARGET_INDEX": "1",
                "IB_GATEWAY_EXPECTED_HOST": "10.20.30.40",
                "FAKE_INSTANCE_IP": instance_ip,
                "RUNNER_TEMP": str(runner_temp),
                "FAKE_GCLOUD_LOG": str(call_log),
                "INSPECT_SSH_KEY_BINDING": "false",
                "SSH_PRIVATE_KEY_SECRET_NAME": "synthetic-secret-name",
                "GCP_SECRET_PROJECT_ID": "synthetic-secret-project",
                "GCE_USER": "synthetic-user",
            }
            completed = subprocess.run(
                ["bash", "-euo", "pipefail", "-c", ssh_policy_run_script()],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            calls = call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []
            leftovers = [path.name for path in runner_temp.iterdir()]
            return completed, calls, leftovers

    def test_embedded_step_uses_only_two_metadata_gets_and_never_ssh(self):
        shell_source = ssh_policy_run_script().lower()
        for forbidden in ("ssh ", "start-iap-tunnel"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, shell_source)
        result, calls, leftovers = self._run_embedded_policy_step()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].startswith("compute instances"))
        self.assertTrue(calls[1].startswith("compute project-info"))
        self.assertFalse(any("ssh" in call or "tunnel" in call or "secrets" in call for call in calls))
        self.assertIn("SSH_POLICY_ENABLE_OSLOGIN=enabled", result.stdout)
        self.assertIn("SSH_POLICY=verified reason=none", result.stdout)
        self.assertNotIn("synthetic-project", result.stdout + result.stderr)
        self.assertEqual(leftovers, [])

    def test_project_get_failure_is_fixed_and_does_not_fallback(self):
        result, calls, leftovers = self._run_embedded_policy_step("project-info")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[-1].split()[:2], ["compute", "project-info"])
        self.assertIn("SSH_POLICY=blocked reason=project_metadata_unavailable", result.stdout)
        self.assertNotIn("PRIVATE_PROVIDER_ERROR_DO_NOT_SHOW", result.stdout + result.stderr)
        self.assertEqual(leftovers, [])

    def test_changed_instance_host_stops_before_project_get(self):
        result, calls, leftovers = self._run_embedded_policy_step(instance_ip="10.20.30.41")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("compute instances"))
        self.assertIn("SSH_POLICY=blocked reason=instance_host_unverified", result.stdout)
        self.assertNotIn("10.20.30.40", result.stdout + result.stderr)
        self.assertNotIn("10.20.30.41", result.stdout + result.stderr)
        self.assertNotIn("GATEWAY_IP_MATCH_INDEX", result.stdout + result.stderr)
        self.assertEqual(leftovers, [])

    def test_instance_get_failure_stops_before_project_get(self):
        result, calls, leftovers = self._run_embedded_policy_step("instances")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("compute instances"))
        self.assertIn("SSH_POLICY=blocked reason=instance_metadata_unavailable", result.stdout)
        self.assertNotIn("PRIVATE_PROVIDER_ERROR_DO_NOT_SHOW", result.stdout + result.stderr)
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
