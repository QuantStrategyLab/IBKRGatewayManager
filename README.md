# IBKR Gateway Manager

An automated deployment solution for IBKR Gateway on Google Compute Engine (GCE), with automated 2FA and daily reconnect.

> ✅ Current target architecture: **Cloud Run → VPC private IP → GCE host port 4001/4002**.

## Features

- **Containerized Deployment**: Docker-based setup.
- **Automated 2FA**: Python bot (`pyotp` + `xdotool`) auto-fills TOTP.
- **Daily Auto-Reconnect**: restart policy for long-running reliability.
- **API Handshake Recovery**: systemd health check validates the IB API handshake and restarts/recreates the container if the API is not ready.
- **Private Network API Access**: IBKR API exposed on GCE private network for Cloud Run.

---

## Architecture (Updated)

```text
Cloud Run service
   │
   ├─(egress: all-traffic/private-ranges-only)
   ▼
Direct VPC egress or Serverless VPC Access connector
   ▼
VPC (same region/network path)
   ▼
GCE VM (private IP, host port 4001/4002)
   ▼
Docker: ib-gateway container (relay on 4003/4004)
```

For this architecture to work:

1. The base image must expose remote API access through host ports `4001`/`4002`.
2. Host ports `4001` and `4002` must be published on the VM.
3. VPC firewall must allow source = Cloud Run/VPC connector CIDR to destination VM TCP `4001` or `4002`.
4. `ALLOW_CONNECTIONS_FROM_LOCALHOST_ONLY=no` must be set so the image enables remote access relay.

---

## Quick Start

### 1. Prerequisites

- A Linux GCE VM with Docker + Docker Compose.
- IBKR account with TOTP 2FA enabled.
- Cloud Run service and GCE VM attached to reachable VPC network path.

### 2. Configure `.env`

Create `.env` beside `docker-compose.yml`:

```bash
TWS_USERID=your_ibkr_username
TWS_PASSWORD=your_ibkr_password
TOTP_SECRET=your_base32_totp_secret
VNC_SERVER_PASSWORD=your_vnc_password
TRADING_MODE=live
TWS_ACCEPT_INCOMING=accept
READ_ONLY_API=no
TWOFA_TIMEOUT_ACTION=restart
RELOGIN_AFTER_TWOFA_TIMEOUT=yes
EXISTING_SESSION_DETECTED_ACTION=primary
JAVA_HEAP_SIZE=512

# Recommended: use the exact CIDR used by your Cloud Run egress path
# Direct VPC egress: use the subnet CIDR
# VPC connector: use the connector CIDR
ACCEPT_API_FROM_IP=10.8.0.0/26

# Must be 'no' for Cloud Run private IP access
ALLOW_CONNECTIONS_FROM_LOCALHOST_ONLY=no
```

### Shared GitHub Config (Recommended)

If `InteractiveBrokersPlatform` and `IBKRGatewayManager` share one GitHub-managed config, keep these non-secret values in GitHub Variables:

```bash
IB_GATEWAY_INSTANCE_NAME=interactive-brokers-quant-instance
IB_GATEWAY_ZONE=us-central1-c
IB_GATEWAY_MODE=paper
IB_GATEWAY_CLOUD_RUN_EGRESS_CIDR=10.128.0.0/20
IB_GATEWAY_GCE_USER=zwlddx0815
IB_GATEWAY_DEPLOY_PATH=/home/zwlddx0815/ib-docker
IB_GATEWAY_ALLOW_CONNECTIONS_FROM_LOCALHOST_ONLY=no
IB_GATEWAY_TWS_ACCEPT_INCOMING=accept
IB_GATEWAY_READ_ONLY_API=no
```

The workflow maps these shared values to the gateway container's `.env`:

- `IB_GATEWAY_MODE` -> `TRADING_MODE`
- `IB_GATEWAY_CLOUD_RUN_EGRESS_CIDR` -> `ACCEPT_API_FROM_IP`
- `IB_GATEWAY_INSTANCE_NAME` -> `GCE_INSTANCE_NAME`
- `IB_GATEWAY_ZONE` -> `GCE_ZONE`
- `IB_GATEWAY_GCE_USER` -> `GCE_USER`
- `IB_GATEWAY_DEPLOY_PATH` -> `DEPLOY_PATH`

`ACCEPT_API_FROM_IP` is intentionally treated as required now. For manual `docker compose` usage, if you forget to set it, Compose will fail fast instead of starting a gateway that Cloud Run can never reach.

This shared GitHub config is scoped to the **IBKR deployment pair only** (`InteractiveBrokersPlatform` + `IBKRGatewayManager`). It should not be treated as a platform-wide secret set for unrelated quant projects. The gateway workflow now authenticates to GCP with **GitHub OIDC + Workload Identity Federation** instead of a long-lived `GCP_SA_KEY`.

### 3. Start IBKR Gateway

```bash
docker compose up -d --build
sudo bash ./scripts/install_2fa_bot_watcher.sh
sudo bash ./scripts/install_gateway_health_watcher.sh
```

> If you use this repository's GitHub Actions workflow, pushing deploy-related changes to `main` triggers a full deployment to GCE. The daily scheduled run only does a lightweight keepalive start and watcher check; it does not rebuild the Docker image.

> Manual `workflow_dispatch` defaults to `keepalive`. If you really need to rebuild the image, choose `deploy_mode=full` when dispatching it.

### 4. Verify on GCE VM

```bash
docker compose ps
ss -lntp | grep -E '4001|4002'
```

Expected: host is listening on `0.0.0.0:4001` and/or `0.0.0.0:4002` (or VM private interface) and container is healthy.

The readiness script checks the actual IB API handshake, not just TCP connectivity:

```bash
sudo bash ./scripts/wait_for_ib_gateway_ready.sh paper
```

It opens an IB protocol session, waits for the Gateway handshake, sends `StartApi`,
and only succeeds after `nextValidId` plus `managedAccounts` have arrived. This
catches the common failure mode where the Docker port is listening but Gateway is
blocked by a login/API prompt.

---

## Cloud Run Connectivity Checklist

1. Cloud Run service uses **Direct VPC egress** or **Serverless VPC Access connector**.
2. Cloud Run egress is configured correctly (`all-traffic` or `private-ranges-only`, depending on your route design).
3. Firewall rule allows the Direct VPC subnet CIDR or connector CIDR to VM TCP `4001` for `live` or `4002` for `paper`.
4. Application uses `GCE_PRIVATE_IP:4001` for `live` or `GCE_PRIVATE_IP:4002` for `paper`.

---

## Recreate GCE and Deploy (Recommended Flow)

When recreating your VM, use this order:

1. **Create GCE VM** (Ubuntu recommended) in the same VPC/region path reachable from Cloud Run.
2. **Install Docker + Docker Compose plugin** on the VM.
3. **Clone this repo** to your target path (for example `/home/<user>/ib-docker`).
4. **Set GitHub Secrets** so Action can redeploy automatically.
5. **Push deploy-related changes to `main`** to trigger a full deployment workflow.

### GitHub Config for Auto Deploy

**GitHub Authentication**

This workflow now uses **GitHub OIDC + Workload Identity Federation** for Google Cloud auth. You do **not** need `GCP_SA_KEY` anymore.

**GitHub Secrets**

| Secret | Purpose |
| :--- | :--- |
| `SSH_PRIVATE_KEY` | SSH private key for VM login |
| `TWS_USERID` | IBKR username |
| `TWS_PASSWORD` | IBKR password |
| `TOTP_SECRET` | IBKR TOTP secret |
| `VNC_SERVER_PASSWORD` | VNC password |

**Optional GitHub Variables for Secret Manager**

If you want to stop storing the gateway credentials in GitHub Secrets, set these variables to Secret Manager secret names in project `interactivebrokersquant`. When a `*_SECRET_NAME` variable is present, the workflow reads the latest secret version from Secret Manager; otherwise it falls back to the matching GitHub secret.

If you temporarily keep the values in GitHub Secrets during migration, you can run the workflow manually with `sync_github_secrets_to_secret_manager=true` once, then delete the GitHub Secrets after verification.

| Variable | Reads secret value for |
| :--- | :--- |
| `IB_GATEWAY_SSH_PRIVATE_KEY_SECRET_NAME` | `SSH_PRIVATE_KEY` |
| `IB_GATEWAY_TWS_USERID_SECRET_NAME` | `TWS_USERID` |
| `IB_GATEWAY_TWS_PASSWORD_SECRET_NAME` | `TWS_PASSWORD` |
| `IB_GATEWAY_TOTP_SECRET_SECRET_NAME` | `TOTP_SECRET` |
| `IB_GATEWAY_VNC_SERVER_PASSWORD_SECRET_NAME` | `VNC_SERVER_PASSWORD` |

**GitHub Variables (recommended shared config)**

| Variable | Purpose |
| :--- | :--- |
| `IB_GATEWAY_GCE_USER` | VM SSH username (for example `zwlddx0815`) |
| `IB_GATEWAY_DEPLOY_PATH` | Repo path on VM (for example `/home/zwlddx0815/ib-docker`) |
| `IB_GATEWAY_INSTANCE_NAME` | VM instance name |
| `IB_GATEWAY_ZONE` | VM zone |
| `IB_GATEWAY_MODE` | `paper` or `live` |
| `IB_GATEWAY_CLOUD_RUN_EGRESS_CIDR` | Cloud Run Direct VPC egress or connector CIDR (example `10.8.0.0/26`) |
| `IB_GATEWAY_ALLOW_CONNECTIONS_FROM_LOCALHOST_ONLY` | Set to `no` for Cloud Run private IP access |
| `IB_GATEWAY_TWS_ACCEPT_INCOMING` | Optional. Recommended `accept`. |
| `IB_GATEWAY_READ_ONLY_API` | Optional. Recommended `no` if this service places trades. |

The current VM is an `e2-micro`, so the deployment intentionally sets `JAVA_HEAP_SIZE=512`
by default and enables a 2 GiB host swap file during keepalive/deploy. Without this,
the upstream gateway image's default `-Xmx768m` can leave too little memory for sshd,
Docker, and the GCE guest agent. For better long-running stability, use at least
`e2-small` / `e2-medium` instead of relying only on swap.

This repository also overrides the upstream headless startup script so Gateway runs with
`Xvfb :1 -screen 0 1024x768x24` and `x11vnc -noxdamage`. On the current GCE target, the
upstream `16bpp` display frequently led to black VNC output and intermittent IBC window
detection failures before login completed.

The image also raises `LoginDialogDisplayTimeout` from `60` to `180` seconds in both
`/home/ibgateway/ibc/config.ini` and `config.ini.tmpl`. Keepalive recovery on the current
GCE target has occasionally needed longer than the upstream default before IBC can detect
the login/config dialog and drive Gateway back to an API-ready state.

For direct `docker compose` usage outside GitHub Actions, `ACCEPT_API_FROM_IP` must still be set explicitly in `.env`; there is no longer a silent default CIDR.

These GitHub secrets are specific to this repository's deployment flow. They are not intended to be global secrets shared by every quant repository.

---

## Operational Commands

### View 2FA Bot Logs

```bash
docker exec ib-gateway tail -f /home/ibgateway/2fa.log
```

### Check Bot Process

```bash
docker exec ib-gateway pgrep -f 2fa_bot.py
```

### Check Watcher Timer

```bash
systemctl status ibkr-2fa-bot.timer --no-pager
```

### Check Gateway API Health Timers

```bash
systemctl status ibkr-gateway-healthcheck.timer --no-pager
systemctl status ibkr-gateway-daily-restart.timer --no-pager
```

`ibkr-gateway-healthcheck.timer` runs every 5 minutes by default. It calls
`recover_ib_gateway_ready.sh`, which first checks IB API handshake readiness,
then restarts and finally recreates the container if the API does not recover.

`ibkr-gateway-daily-restart.timer` restarts the Gateway once per day at
`10:30 UTC` by default, then waits for the same API handshake readiness. Override
the schedule during install with:

```bash
IB_GATEWAY_DAILY_RESTART_ON_CALENDAR='Mon..Fri 10:30:00 UTC' sudo bash ./scripts/install_gateway_health_watcher.sh
```

### Check API Port in Container

```bash
docker exec ib-gateway sh -lc 'command -v ss >/dev/null && ss -lntp | grep -E "4003|4004" || netstat -lntp | grep -E "4003|4004"'
```

---

## Security Notes

- Do **not** set `ACCEPT_API_FROM_IP=0.0.0.0/0` in production.
- Restrict firewall source to only your Cloud Run/VPC connector CIDR.
- Keep VNC (`5900`) localhost-bound or tunnel-only.

---

## Troubleshooting

### Cloud Run cannot connect to `GCE_PRIVATE_IP:4001` or `GCE_PRIVATE_IP:4002`

- Confirm VM firewall rule exists for source connector CIDR -> TCP 4001 (`live`) or TCP 4002 (`paper`).
- Confirm `ALLOW_CONNECTIONS_FROM_LOCALHOST_ONLY=no`. This is equivalent to disabling the IB Gateway GUI option that only accepts localhost API clients.
- Confirm `TWS_ACCEPT_INCOMING=accept` so incoming API sessions are auto-accepted.
- Confirm `READ_ONLY_API=no` if the strategy must place live or paper orders.
- Confirm Docker published ports are `4001:4003` and `4002:4004`.
- Confirm the application uses `4001` for `live` and `4002` for `paper`.
- Confirm service and connector are in compatible region/network routing setup.

### 2FA bot not filling code

- Check logs: `docker exec ib-gateway tail -f /home/ibgateway/2fa.log`
- Verify `TOTP_SECRET` is valid Base32 secret.
- Confirm watcher timer is active: `systemctl status ibkr-2fa-bot.timer --no-pager`

---

## License

MIT
