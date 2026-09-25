# IBKRGatewayManager


## QSL architecture role

- **Layer**: `runtime-ops`.
- **Responsibility**: IBKR gateway VM lifecycle and 2FA operations utility.
- **Owns**: gateway deployment, remote sync, Docker rollout, watcher setup.
- **Consumes**: InteractiveBrokersPlatform operational requirements.
- **Must not**: decide strategy eligibility or submit trading orders.

[Chinese README](README.zh-CN.md)

> Investing involves risk. This project does not provide investment advice and is for education, research, and engineering review only.

## What this repository is

IBKRGatewayManager is a QuantStrategyLab IBKR gateway operations utility. It manages deployment, remote sync, Docker rollout, and 2FA watcher setup for the IBKR gateway VM.

It supports the system but does not decide which strategy should be live. Strategy eligibility remains in the strategy and snapshot repositories; broker execution remains in the platform repositories.

## Design boundary

- Keep contracts stable and versioned where downstream repositories depend on them.
- Prefer backward-compatible changes unless a coordinated migration is planned.
- Keep secrets and environment-specific settings outside the shared library code.
- Document changes that affect multiple platforms or strategy packages.
- A compact, generic Gateway dialog never causes a click-through. If the API is unavailable, the watcher may perform one bounded container restart without acknowledging the dialog; an unresolved dialog still fails closed for operator review.

## Gateway target configuration

Deployment workflows require the repository-level Actions variable `IB_GATEWAY_TARGETS_JSON`. It is a JSON object keyed by a non-sensitive target label (or a list whose entries include `name`). Every target supplies its own GCP project, Workload Identity provider, service account, VM location, and deployment settings. The repository has no default gateway or cloud account.

Setting `maintenance_enabled=false` for a target pauses scheduled redeployment only; it does not disable the Gateway health and 2FA timers already installed on the VM. A scheduled workflow can succeed when every target was skipped, so its result does not verify the Gateway API, login, or account identity. Use the read-only diagnostics and separate account-level evidence; do not enable scheduled redeployment just to obtain a green workflow.

```json
{
  "gateway-a": {
    "gcp_project_id": "<gcp-project-id>",
    "gcp_workload_identity_provider": "projects/<number>/locations/global/workloadIdentityPools/<pool>/providers/<provider>",
    "gcp_workload_identity_service_account": "<service-account>@<gcp-project-id>.iam.gserviceaccount.com",
    "gce_user": "<vm-user>",
    "gce_instance_name": "<vm-name>",
    "gce_zone": "<gcp-zone>",
    "deploy_path": "/opt/ibkr-gateway",
    "mode": "paper",
    "container_name": "<container-name>",
    "compose_project_name": "<compose-project>",
    "compose_service_name": "<compose-service>",
    "cloud_run_egress_cidr": "<trusted-egress-cidr>",
    "allow_connections_from_localhost_only": "no",
    "ssh_private_key_secret_name": "<secret-manager-secret-name>"
  }
}
```

Use Secret Manager secret *names* rather than secret values. Full deployments require target-specific names for the SSH key and Gateway username and password. VNC is optional: omit `vnc_server_password_secret_name` to leave the VNC server disabled. TOTP auto-fill is off by default; an explicit opt-in also requires a target-specific TOTP secret name. When auto-fill is off, the workflow does not fetch or send the TOTP seed to the VM. Do not commit target JSON, credentials, account identifiers, addresses, or private keys. A missing required target configuration fails before any cloud authentication or remote operation.

Optional `ib_gateway_base_version` selects the Gateway base image version for one target. The default is `10.50.1e`; change it only after checking that target's compatibility. Other targets keep their configured version.

Full deployments install the VM runtime `.env` with mode `0600`. The Gateway uses the configured username and password; when `ibkr_2fa_autofill` is explicitly enabled, the 2FA bot also reads the target-specific TOTP seed and fills a compatible challenge. This path does not use VNC. Verify API and account identity before enabling platform traffic. The VM stores the Gateway password and, when enabled, the TOTP seed; restrict access to that host and its deployment identity.

When moving a VM to another project, optional `gcp_secret_project_id` keeps Secret Manager reads in the existing project; otherwise secrets come from `gcp_project_id`. The configured deployment service account needs access to both the VM and those specific secrets. Change the target only after the new VM is ready and the old Gateway has stopped.

Project and instance names work for IAP administration, and a platform service can reach the Gateway over the VPC's internal address. The Gateway VM still needs a separate route to IBKR on the public internet. Removing its external IP requires another outbound route, such as Cloud NAT, with its own charges.

## Repository layout

- `tests/`: unit, contract, and regression tests.
- `.github/workflows/`: CI, scheduled jobs, release, or deployment workflows.
- `scripts/`: operator scripts and local helpers.

## Quick start

```bash
python -m pip install -r requirements.txt
python -m pytest -q
```

## Useful docs

- No separate `docs/` directory yet; start with this README and the workflow files.

## QSL Compatibility Metadata

- Added `qsl.toml` to participate in the runtime compatibility matrix with `tier = "runtime-ops"`, `ring = 4`, and `compat.bundle = "2026.07.0"`.
- This repository is an IBKR operations utility (deployment/watchdog/tooling) and is intentionally not converted to a standard runtime `pyproject` package flow in this phase.
- No runtime business dependency contract changes are included in this PR; only metadata-only compatibility scaffolding is added.


## Community and security

- See [CONTRIBUTING.md](CONTRIBUTING.md) for pull request scope, local verification, and documentation expectations.
- Follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for maintainer and contributor conduct.
- Report credential, automation, broker, exchange, or cloud-resource vulnerabilities through [SECURITY.md](SECURITY.md); do not open public issues for secrets or live-execution risk.

## License

See [LICENSE](LICENSE).
