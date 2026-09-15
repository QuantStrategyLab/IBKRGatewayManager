#!/usr/bin/env python3
"""Offline safety checks for the restore-env workflow step."""

import os
import subprocess
import tempfile
from pathlib import Path

WORKFLOW = Path(__file__).parents[1] / ".github/workflows/main.yml"
workflow_text = WORKFLOW.read_text(encoding="utf-8")
step_text = workflow_text.split("      - name: Restore missing gateway runtime environment\n", 1)[1]
step_text = step_text.split("      - name: Deploy and Log Setup\n", 1)[0]
run = "\n".join(line[10:] for line in step_text.splitlines()[1:] if line.startswith("          "))


def exercise(kind: str) -> subprocess.CompletedProcess[str]:
    root = Path(tempfile.mkdtemp(prefix="restore-env-workflow-"))
    deploy = root / "deploy"
    deploy.mkdir()
    candidate = root / "candidate.env"
    candidate.write_text("TRADING_MODE='paper'\nREAD_ONLY_API='yes'\n", encoding="utf-8")
    if kind == "existing":
        (deploy / ".env").write_bytes(b"keep-me")
    elif kind == "symlink":
        sentinel = root / "sentinel"
        sentinel.write_bytes(b"keep-me")
        (deploy / ".env").symlink_to(sentinel)
    running_env = 'TRADING_MODE=paper","READ_ONLY_API=yes'
    host_port = "4001"
    host_ip = "0.0.0.0"
    if kind == "env-mismatch":
        running_env = 'TRADING_MODE=live","READ_ONLY_API=yes'
    elif kind == "port-mismatch":
        host_port = "9999"
    elif kind == "host-ip-mismatch":
        host_ip = "127.0.0.1"
    fake = root / "fake"
    fake.mkdir()
    (fake / "gcloud").write_text(
        '#!/usr/bin/env bash\nset -e\n'
        'if [ "$1" = compute ] && [ "$2" = scp ]; then '
        'src="$3"; dest="${4#*:}"; cp "$src" "$dest"; exit 0; fi\n'
        'if [ "$1" = compute ] && [ "$2" = ssh ]; then shift 2; '
        'while [ "$#" -gt 0 ]; do if [ "$1" = --command ]; then shift; '
        'bash -c "$1"; exit $?; fi; shift; done; fi\n',
        encoding="utf-8",
    )
    (fake / "sudo").write_text('#!/usr/bin/env bash\nexec "$@"\n', encoding="utf-8")
    (fake / "docker").write_text(
        f'''#!/usr/bin/env bash
set -e
if [ "$1" = inspect ] && [ "$2" = --format ]; then
  if [[ "$3" == *State.Running* ]]; then echo true; exit 0; fi
  exit 1
fi
if [ "$1" = inspect ]; then
  cat <<'JSON'
[{{"Name":"/ib-gateway","Config":{{"Labels":{{"com.docker.compose.project":"app","com.docker.compose.service":"ib-gateway","com.docker.compose.project.working_dir":"{deploy}"}},"Env":["{running_env}"],"WorkingDir":"/"}},"NetworkSettings":{{"Ports":{{"4001/tcp":[{{"HostPort":"{host_port}","HostIp":"{host_ip}"}}]}}}}}}]
JSON
  exit 0
fi
if [ "$1" = compose ]; then
  cat <<'JSON'
{{"services":{{"ib-gateway":{{"environment":{{"TRADING_MODE":"paper","READ_ONLY_API":"yes"}},"ports":[{{"target":4001,"published":4001,"protocol":"tcp"}}]}}}}}}
JSON
  exit 0
fi
exit 1
''',
        encoding="utf-8",
    )
    for executable in fake.iterdir():
        executable.chmod(0o755)
    script = root / "run.sh"
    script.write_text("#!/usr/bin/env bash\n" + run + "\n", encoding="utf-8")
    script.chmod(0o755)
    env = os.environ | {
        "PATH": f"{fake}:{os.environ['PATH']}",
        "WORKFLOW_DISPATCH_TARGET": "gateway-a",
        "GCE_USER": os.environ.get("USER", "root"),
        "GCE_INSTANCE_NAME": "vm",
        "GCP_PROJECT_ID": "project",
        "GCE_ZONE": "zone",
        "SSH_KEY_FILE": "/tmp/key",
        "TARGET_NAME": "gateway-a",
        "GITHUB_RUN_ID": f"{kind}-{root.name}",
        "DEPLOY_PATH": str(deploy),
        "IB_GATEWAY_CONTAINER_NAME": "ib-gateway",
        "IB_GATEWAY_COMPOSE_SERVICE_NAME": "ib-gateway",
        "IB_GATEWAY_COMPOSE_PROJECT_NAME": "app",
        "ENV_FILE": str(candidate),
    }
    result = subprocess.run(["bash", str(script)], env=env, text=True, capture_output=True)
    destination = deploy / ".env"
    if kind == "positive":
        assert destination.read_bytes() == candidate.read_bytes()
        assert destination.stat().st_mode & 0o777 == 0o600
    elif kind in {"env-mismatch", "port-mismatch", "host-ip-mismatch"}:
        assert not destination.exists()
    elif kind == "existing":
        assert destination.read_bytes() == b"keep-me"
    elif kind == "symlink":
        assert destination.is_symlink()
    return result


for case in ("positive", "existing", "symlink", "env-mismatch", "port-mismatch", "host-ip-mismatch"):
    result = exercise(case)
    assert (result.returncode == 0) == (case == "positive"), (case, result.stderr)
    print(f"{case}: ok")
