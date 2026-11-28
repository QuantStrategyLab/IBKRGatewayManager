import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "main.yml"


def _extract_select_code(workflow_text: str) -> str:
    start = "          python3 - <<'PY'\n"
    code = workflow_text.split(start, 1)[1].split("          PY\n", 1)[0]
    return "\n".join(line.removeprefix("          ") for line in code.splitlines())


def _extract_resolve_code(workflow_text: str) -> str:
    resolve_step = workflow_text.split("      - name: Resolve gateway target config\n", 1)[1].split(
        "          PY\n", 1
    )[0]
    code = resolve_step.split("          python3 - <<'PY'\n", 1)[1]
    return "\n".join(line.removeprefix("          ") for line in code.splitlines())


class IsolatedPaperTargetsJsonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.select_code = _extract_select_code(workflow_text)
        cls.resolve_code = _extract_resolve_code(workflow_text)

    def _run_select(
        self,
        targets_json: str,
        paper_targets_json: str = "",
        *,
        selected_target: str = "all",
        deploy_mode: str = "keepalive",
        event_name: str = "workflow_dispatch",
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output"
            summary = Path(tmp) / "summary"
            env = os.environ | {
                "TARGETS_JSON": targets_json,
                "PAPER_TARGETS_JSON": paper_targets_json,
                "SELECTED_TARGET": selected_target,
                "SELECTED_DEPLOY_MODE": deploy_mode,
                "GITHUB_EVENT_NAME": event_name,
                "EVENT_SCHEDULE_CRON": "",
                "SCHEDULE_NOW_UTC": "",
                "GITHUB_OUTPUT": str(out),
                "GITHUB_STEP_SUMMARY": str(summary),
            }
            res = subprocess.run([sys.executable, "-c", self.select_code], env=env, text=True, capture_output=True)
            parsed = dict(line.split("=", 1) for line in out.read_text().splitlines()) if out.exists() else {}
            return res, parsed

    def _run_resolve(
        self,
        targets_json: str,
        paper_targets_json: str,
        *,
        target_index: int,
        target_digest: str,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "env"
            env = os.environ | {
                "TARGETS_JSON": targets_json,
                "PAPER_TARGETS_JSON": paper_targets_json,
                "TARGET_INDEX": str(target_index),
                "TARGET_DIGEST": target_digest,
                "GITHUB_ENV": str(env_file),
            }
            res = subprocess.run([sys.executable, "-c", self.resolve_code], env=env, text=True, capture_output=True)
            parsed = dict(line.split("=", 1) for line in env_file.read_text().splitlines()) if env_file.exists() else {}
            return res, parsed

    def test_appends_paper_target_and_resolves_after_live_targets(self) -> None:
        live_json = '{"live-gw":{"mode":"live","gcp_project_id":"mock-live"}}'
        paper_json = '{"paper-policy-v0":{"mode":"paper","gcp_project_id":"mock-paper","gce_user":"ibkrpaper"}}'
        sel_res, outputs = self._run_select(
            live_json,
            paper_json,
            selected_target="paper-policy-v0",
            deploy_mode="full",
        )
        self.assertEqual(sel_res.returncode, 0, sel_res.stderr)
        matrix = json.loads(outputs["matrix"])["include"]
        self.assertEqual(len(matrix), 1)
        self.assertEqual(matrix[0]["target_index"], 1)

        res_res, resolved_env = self._run_resolve(
            live_json,
            paper_json,
            target_index=matrix[0]["target_index"],
            target_digest=matrix[0]["target_digest"],
        )
        self.assertEqual(res_res.returncode, 0, res_res.stderr)
        self.assertEqual(resolved_env["TARGET_NAME"], "paper-policy-v0")
        self.assertEqual(resolved_env["IB_GATEWAY_MODE"], "paper")
        self.assertEqual(resolved_env["GCP_PROJECT_ID"], "mock-paper")
        self.assertEqual(resolved_env["GCE_USER"], "ibkrpaper")

    def test_rejects_non_paper_mode_in_paper_secret(self) -> None:
        live_json = '{"live-gw":{"mode":"live"}}'
        bad_paper = '{"oops":{"mode":"live"}}'
        res, _ = self._run_select(live_json, bad_paper)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("IB_GATEWAY_PAPER_TARGETS_JSON entries must set mode='paper'", res.stderr)

    def test_rejects_multiline_paper_secret(self) -> None:
        live_json = '{"live-gw":{"mode":"live"}}'
        multiline_paper = '{\n  "paper-gw": {"mode": "paper"}\n}'
        res, _ = self._run_select(live_json, multiline_paper)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("IB_GATEWAY_PAPER_TARGETS_JSON must be stored as single-line JSON", res.stderr)

    def test_rejects_duplicate_name_between_live_and_paper(self) -> None:
        live_json = '{"gw-a":{"mode":"live"}}'
        dup_paper = '{"gw-a":{"mode":"paper"}}'
        res, _ = self._run_select(live_json, dup_paper)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Duplicate gateway target: gw-a", res.stderr)

    def test_resolve_rejects_non_paper_mode_independently(self) -> None:
        live_json = '{"live-gw":{"mode":"live"}}'
        bad_paper = '{"oops":{"mode":"live"}}'
        digest = hashlib.sha256(b'{"mode":"live","name":"oops"}').hexdigest()
        res, _ = self._run_resolve(live_json, bad_paper, target_index=1, target_digest=digest)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("IB_GATEWAY_PAPER_TARGETS_JSON entries must set mode='paper'", res.stderr)


if __name__ == "__main__":
    unittest.main()
