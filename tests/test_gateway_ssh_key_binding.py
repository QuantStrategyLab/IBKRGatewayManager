from __future__ import annotations

import base64
import importlib.util
import json
import os
import re
import shlex
import subprocess
import tempfile
import textwrap
import unittest
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "compare_gateway_ssh_key_binding.py"
WORKFLOW = ROOT / ".github" / "workflows" / "read-only-vm-metadata-diagnostic.yml"


def load_module():
    spec = importlib.util.spec_from_file_location("compare_gateway_ssh_key_binding", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def metadata(items: list[tuple[str, str]]) -> dict[str, Any]:
    return {"metadata": {"items": [{"key": key, "value": value} for key, value in items]}}


def project(items: list[tuple[str, str]]) -> dict[str, Any]:
    return {"commonInstanceMetadata": {"items": [{"key": key, "value": value} for key, value in items]}}


class GatewaySshKeyBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.key_path = self.root / "synthetic-key"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.key_path)],
            check=True,
            capture_output=True,
        )
        self.public_fields = self.key_path.with_suffix(".pub").read_text(encoding="utf-8").split()
        self.key_path.with_suffix(".pub").unlink()
        self.module = load_module()
        self.now = datetime(2026, 10, 1, tzinfo=UTC)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def key_entry(self, username: str = "synthetic-user", *, expires: str | None = None) -> str:
        algorithm, blob = self.public_fields[:2]
        suffix = ""
        if expires is not None:
            suffix = " google-ssh " + json.dumps(
                {"userName": username, "expireOn": expires}, separators=(",", ":")
            )
        return f"{username}:{algorithm} {blob}{suffix}"

    def compare(
        self,
        instance_items: list[tuple[str, str]] | None = None,
        project_items: list[tuple[str, str]] | None = None,
        username: str = "synthetic-user",
    ) -> dict[str, str]:
        return self.module.compare_binding(
            self.key_path,
            username,
            metadata(instance_items or []),
            project(project_items or []),
            now=self.now,
        )

    def test_matches_full_username_and_key_from_instance_or_project(self) -> None:
        self.assertEqual(
            self.compare([("ssh-keys", self.key_entry())])["status"], "match"
        )
        result = self.compare(project_items=[("ssh-keys", self.key_entry())])
        self.assertEqual((result["status"], result["source"]), ("match", "project"))
        self.assertEqual(
            self.compare([("ssh-keys", self.key_entry("synthetic-user-extra"))])["status"],
            "no_match",
        )
        other_blob = base64.b64encode(b"different-key-blob").decode("ascii")
        self.assertEqual(
            self.compare([("ssh-keys", f"synthetic-user:ssh-ed25519 {other_blob}")])["status"],
            "no_match",
        )

    def test_instance_match_wins_and_block_project_excludes_project_keys(self) -> None:
        result = self.compare(
            [("ssh-keys", self.key_entry())],
            [("ssh-keys", self.key_entry("other-user"))],
        )
        self.assertEqual((result["status"], result["source"]), ("match", "instance"))
        blocked = self.compare(
            [("block-project-ssh-keys", "TRUE")],
            [("ssh-keys", self.key_entry())],
        )
        self.assertEqual((blocked["status"], blocked["source"]), ("no_match", "none"))

    def test_oslogin_enabled_makes_metadata_key_comparison_unknown(self) -> None:
        result = self.compare(
            [("enable-oslogin", "TRUE"), ("ssh-keys", self.key_entry())]
        )
        self.assertEqual((result["status"], result["reason"]), ("unknown", "oslogin_enabled"))
        inherited = self.compare(
            [], [("enable-oslogin", "TRUE"), ("ssh-keys", self.key_entry())]
        )
        self.assertEqual((inherited["status"], inherited["reason"]), ("unknown", "oslogin_enabled"))
        instance_override = self.compare(
            [("enable-oslogin", "FALSE"), ("ssh-keys", self.key_entry())],
            [("enable-oslogin", "TRUE")],
        )
        self.assertEqual((instance_override["status"], instance_override["source"]), ("match", "instance"))

    def test_expiry_is_enforced_and_malformed_expiry_fails_closed(self) -> None:
        self.assertEqual(
            self.compare(
                [("ssh-keys", self.key_entry(expires="2026-10-02T00:00:00Z"))]
            )["status"],
            "match",
        )
        compact_zone = self.compare(
            [("ssh-keys", self.key_entry(expires="2026-10-02T00:00:00+0000"))]
        )
        self.assertEqual(compact_zone["status"], "match")
        expired = self.compare(
            [("ssh-keys", self.key_entry(expires="2026-10-01T00:00:00Z"))]
        )
        self.assertEqual((expired["status"], expired["reason"]), ("no_match", "key_expired"))
        malformed = self.compare(
            [("ssh-keys", self.key_entry(expires="not-a-date"))]
        )
        self.assertEqual((malformed["status"], malformed["reason"]), ("unknown", "metadata_invalid"))
        missing_expiry = self.compare(
            [("ssh-keys", f"synthetic-user:{self.public_fields[0]} {self.public_fields[1]} google-ssh {{\"userName\":\"synthetic-user\"}}")]
        )
        self.assertEqual((missing_expiry["status"], missing_expiry["reason"]), ("unknown", "metadata_invalid"))
        duplicate_json_key = self.compare(
            [("ssh-keys", f"synthetic-user:{self.public_fields[0]} {self.public_fields[1]} google-ssh {{\"userName\":\"synthetic-user\",\"userName\":\"synthetic-user\",\"expireOn\":\"2026-10-02T00:00:00Z\"}}")]
        )
        self.assertEqual((duplicate_json_key["status"], duplicate_json_key["reason"]), ("unknown", "metadata_invalid"))
        wrong_metadata_username = self.compare(
            [("ssh-keys", self.key_entry(expires="2026-10-02T00:00:00Z").replace('"userName":"synthetic-user"', '"userName":"other-user"'))]
        )
        self.assertEqual(
            (wrong_metadata_username["status"], wrong_metadata_username["reason"]),
            ("unknown", "metadata_invalid"),
        )

    def test_malformed_duplicate_and_private_key_fail_closed(self) -> None:
        malformed = self.compare([("ssh-keys", "broken-entry-private-marker")])
        self.assertEqual((malformed["status"], malformed["reason"]), ("unknown", "metadata_invalid"))
        duplicate = self.compare(
            [("ssh-keys", self.key_entry()), ("ssh-keys", self.key_entry())]
        )
        self.assertEqual((duplicate["status"], duplicate["reason"]), ("unknown", "metadata_invalid"))

        self.key_path.write_text("not-a-private-key-marker", encoding="utf-8")
        invalid = self.compare([("ssh-keys", self.key_entry())])
        self.assertEqual((invalid["status"], invalid["reason"]), ("unknown", "key_invalid"))
        self.assertNotIn("not-a-private-key-marker", json.dumps(invalid))

    def test_cli_never_prints_key_or_metadata_and_uses_fixed_fields(self) -> None:
        instance_path = self.root / "instance.json"
        project_path = self.root / "project.json"
        instance_path.write_text(
            json.dumps(metadata([("ssh-keys", self.key_entry())])), encoding="utf-8"
        )
        project_path.write_text(json.dumps(project([])), encoding="utf-8")
        result = subprocess.run(
            ["python3", str(SCRIPT), "--private-key-file", str(self.key_path),
             "--instance-file", str(instance_path), "--project-file", str(project_path)],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "GCE_USER": "synthetic-user"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "SSH_KEY_BINDING=match",
                "SSH_KEY_BINDING_SOURCE=instance",
                "SSH_KEY_BINDING_REASON=matched",
            ],
        )
        self.assertEqual(result.stderr, "")
        self.assertNotIn(self.public_fields[1], result.stdout + result.stderr)
        self.assertNotIn("synthetic-user", result.stdout + result.stderr)

    @staticmethod
    def _embedded_resolve_script() -> str:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        block = workflow[workflow.index("name: Resolve one gateway target"):]
        script_start = block.find("script: |")
        if script_start < 0:
            raise AssertionError("resolve script not found")
        lines = block[script_start + len("script: |"):].lstrip("\n").splitlines()
        script_lines: list[str] = []
        for line in lines:
            if line.strip() and not line.startswith("            "):
                break
            script_lines.append(line[12:] if line.startswith("            ") else "")
        return textwrap.dedent("\n".join(script_lines))

    def _run_resolve(self, env_values: dict[str, str]) -> dict[str, Any]:
        script = self._embedded_resolve_script()
        harness = r"""
          const fs = require('fs');
          const core = {outputs: {}, failure: null,
            setOutput(name, value) { this.outputs[name] = value; },
            setFailed(value) { this.failure = value; }};
          new Function('core', 'require', fs.readFileSync(0, 'utf8'))(core, require);
          process.stdout.write(JSON.stringify(core));
        """
        env = {**os.environ, "GITHUB_WORKSPACE": str(ROOT), **env_values}
        result = subprocess.run(
            ["node", "-e", harness], input=script, capture_output=True, text=True,
            check=False, env=env, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_resolver_requires_protected_single_target_and_policy_mode(self) -> None:
        targets = [
            {
                "name": f"synthetic-{index}",
                "gcp_project_id": f"mock-project-{index}",
                "gcp_workload_identity_provider": f"mock-provider-{index}",
                "gcp_workload_identity_service_account": f"mock-service-{index}",
                "gce_instance_name": f"mock-gateway-{index}",
                "gce_zone": "us-central1-a",
                "gcp_secret_project_id": f"mock-secret-project-{index}",
                "gce_user": "synthetic-user",
                "ssh_private_key_secret_name": "synthetic-secret-name",
            }
            for index in range(4)
        ]
        base = {
            "MATCH_CURRENT_GATEWAY": "true",
            "INSPECT_CONNECTIONS": "false",
            "INSPECT_SSH_POLICY": "true",
            "INSPECT_SSH_KEY_BINDING": "true",
            "MATCH_TARGETS_JSON": json.dumps(targets),
            "MATCHED_INDEX": '{"target_index":1}',
        }
        valid = self._run_resolve(base)
        self.assertIsNone(valid["failure"])
        self.assertEqual(json.loads(valid["outputs"]["matrix"])["include"][0]["target_index"], 1)

        no_policy = self._run_resolve({**base, "INSPECT_SSH_POLICY": "false"})
        self.assertEqual(no_policy["failure"], "SSH key binding requires SSH policy inspection")
        no_match = self._run_resolve({**base, "MATCH_CURRENT_GATEWAY": "false"})
        self.assertEqual(no_match["failure"], "Passive inspection requires protected current-gateway matching")
        with_connections = self._run_resolve({**base, "INSPECT_CONNECTIONS": "true"})
        self.assertEqual(
            with_connections["failure"],
            "SSH policy inspection cannot be combined with connection inspection",
        )

        policy_only_inventory = [
            {key: value for key, value in target.items() if key not in {"gcp_secret_project_id", "gce_user", "ssh_private_key_secret_name"}}
            for target in targets
        ]
        policy_only = self._run_resolve({
            **base, "INSPECT_SSH_KEY_BINDING": "false", "MATCH_TARGETS_JSON": json.dumps(policy_only_inventory)
        })
        self.assertIsNone(policy_only["failure"])

    @staticmethod
    def _embedded_policy_step() -> str:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        match = re.search(
            r"(?ms)^      - id: ssh_policy\n.*?^        run: \|\n(.*?)(?=^      - |\Z)",
            workflow,
        )
        if match is None:
            raise AssertionError("SSH policy step not found")
        return textwrap.dedent(match.group(1))

    def _run_embedded_policy_step(
        self, *, response_ip: str = "10.20.30.40", project_failure: bool = False,
        secret_failure: bool = False, crlf_key: bool = False, eol_check_failure: bool = False
    ) -> tuple[subprocess.CompletedProcess[str], list[str], list[str]]:
        workspace = Path(tempfile.mkdtemp(dir=self.root))
        bin_dir = workspace / "bin"
        runner_temp = workspace / "runner-temp"
        bin_dir.mkdir()
        runner_temp.mkdir()
        call_log = workspace / "gcloud.calls"
        fake_gcloud = bin_dir / "gcloud"
        instance_document = {
            "networkInterfaces": [{"networkIP": response_ip}],
            "metadata": {"items": [{"key": "ssh-keys", "value": self.key_entry()}]},
        }
        project_document = {"commonInstanceMetadata": {"items": []}}
        fake_gcloud.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys\n"
            "args=sys.argv[1:]\n"
            "with open(os.environ['FAKE_GCLOUD_LOG'], 'a', encoding='utf-8') as f: f.write(' '.join(args[:3])+'\\n')\n"
            "if args[:3] == ['compute','instances','describe']:\n"
            f" print(json.dumps({json.dumps(instance_document)}))\n"
            "elif args[:3] == ['compute','project-info','describe']:\n"
            " if os.environ.get('FAKE_PROJECT_FAIL') == 'true':\n"
            "  sys.stderr.write('synthetic-project-error-marker'); sys.exit(13)\n"
            f" print(json.dumps({json.dumps(project_document)}))\n"
            "elif args[:3] == ['secrets','versions','access']:\n"
            " if os.environ.get('FAKE_SECRET_FAIL') == 'true':\n"
            "  sys.stderr.write('synthetic-secret-error-marker'); sys.exit(13)\n"
            " sys.stdout.buffer.write(pathlib.Path(os.environ['FAKE_KEY_FILE']).read_bytes())\n"
            "else:\n"
            " sys.stderr.write('unexpected synthetic command'); sys.exit(90)\n",
            encoding="utf-8",
        )
        fake_gcloud.chmod(0o700)
        if eol_check_failure:
            fake_python = bin_dir / "python3"
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"${1:-}\" = \"-\" ]; then\n"
                "  printf 'synthetic-eol-output-marker\\n'\n"
                "  printf 'synthetic-eol-error-marker\\n' >&2\n"
                "  exit 31\n"
                "fi\n"
                f"exec {shlex.quote(sys.executable)} \"$@\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o700)
        fake_key = workspace / "synthetic-source-key"
        key_bytes = self.key_path.read_bytes()
        fake_key.write_bytes(
            key_bytes.replace(b"\n", b"\r\n").rstrip(b"\r\n") if crlf_key else key_bytes
        )
        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "RUNNER_TEMP": str(runner_temp),
            "GCP_PROJECT_ID": "mock-project",
            "GCP_SECRET_PROJECT_ID": "mock-secret-project",
            "GCE_INSTANCE_NAME": "mock-instance",
            "GCE_ZONE": "us-central1-a",
            "TARGET_INDEX": "1",
            "IB_GATEWAY_EXPECTED_HOST": "10.20.30.40",
            "INSPECT_SSH_KEY_BINDING": "true",
            "SSH_PRIVATE_KEY_SECRET_NAME": "synthetic-secret-name",
            "GCE_USER": "synthetic-user",
            "FAKE_GCLOUD_LOG": str(call_log),
            "FAKE_KEY_FILE": str(fake_key),
            "FAKE_SECRET_FAIL": "true" if secret_failure else "false",
            "FAKE_PROJECT_FAIL": "true" if project_failure else "false",
        }
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", self._embedded_policy_step()],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        calls = call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []
        leftovers = [path.name for path in runner_temp.iterdir()]
        return result, calls, leftovers

    def test_embedded_policy_step_fetches_one_secret_only_after_host_binding_and_cleans_up(self) -> None:
        result, calls, leftovers = self._run_embedded_policy_step(crlf_key=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SSH_KEY_INPUT_EOL=missing", result.stdout)
        self.assertIn("SSH_KEY_BINDING=match\nSSH_KEY_BINDING_SOURCE=instance\nSSH_KEY_BINDING_REASON=matched", result.stdout)
        self.assertEqual(calls, ["compute instances describe", "compute project-info describe", "secrets versions access"])
        self.assertEqual(leftovers, [])
        self.assertNotIn(self.public_fields[1], result.stdout + result.stderr)
        self.assertNotIn("synthetic-user", result.stdout + result.stderr)
        self.assertNotIn("synthetic-secret-name", result.stdout + result.stderr)
        self.assertFalse(any("ssh " in call or "start-iap-tunnel" in call for call in calls))

    def test_embedded_policy_step_reports_present_eof_newline(self) -> None:
        result, calls, leftovers = self._run_embedded_policy_step()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SSH_KEY_INPUT_EOL=present", result.stdout)
        self.assertEqual(calls, ["compute instances describe", "compute project-info describe", "secrets versions access"])
        self.assertEqual(leftovers, [])

    def test_eof_diagnostic_failure_is_fixed_and_stops_before_key_preparation(self) -> None:
        result, calls, leftovers = self._run_embedded_policy_step(eol_check_failure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SSH_KEY_INPUT_EOL=unknown", result.stdout)
        self.assertIn("SSH_KEY_BINDING=unknown", result.stdout)
        self.assertIn("SSH_KEY_BINDING_REASON=inspection_failed", result.stdout)
        self.assertNotIn("synthetic-eol-output-marker", result.stdout + result.stderr)
        self.assertNotIn("synthetic-eol-error-marker", result.stdout + result.stderr)
        self.assertEqual(calls, ["compute instances describe", "compute project-info describe", "secrets versions access"])
        self.assertEqual(leftovers, [])

    def test_secret_failure_is_single_attempt_redacted_and_cleans_up(self) -> None:
        result, calls, leftovers = self._run_embedded_policy_step(secret_failure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "SSH_KEY_BINDING=unknown\nSSH_KEY_BINDING_SOURCE=unknown\nSSH_KEY_BINDING_REASON=key_unavailable",
            result.stdout,
        )
        self.assertNotIn("synthetic-secret-error-marker", result.stdout + result.stderr)
        self.assertEqual(calls, ["compute instances describe", "compute project-info describe", "secrets versions access"])
        self.assertEqual(leftovers, [])

    def test_project_metadata_failure_stops_before_secret_fetch_and_cleans_up(self) -> None:
        result, calls, leftovers = self._run_embedded_policy_step(project_failure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SSH_POLICY=blocked reason=project_metadata_unavailable", result.stdout)
        self.assertNotIn("synthetic-project-error-marker", result.stdout + result.stderr)
        self.assertEqual(calls, ["compute instances describe", "compute project-info describe"])
        self.assertEqual(leftovers, [])

    def test_changed_instance_host_stops_before_project_or_key_secret_read(self) -> None:
        result, calls, leftovers = self._run_embedded_policy_step(response_ip="10.20.30.41")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SSH_POLICY=blocked reason=instance_host_unverified", result.stdout)
        self.assertEqual(calls, ["compute instances describe"])
        self.assertEqual(leftovers, [])
        self.assertNotIn(self.public_fields[1], result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
