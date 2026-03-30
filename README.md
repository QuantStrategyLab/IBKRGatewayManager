# IBKR Gateway Manager

An automated deployment solution for IBKR Gateway on Google Compute Engine (GCE), with automated 2FA and daily reconnect.

> ✅ Current target architecture: **Cloud Run → VPC private IP → GCE host port 4001/4002**.

## Features

- **Containerized Deployment**: Docker-based setup.
- **Automated 2FA**: Python bot (`pyotp` + `xdotool`) auto-fills TOTP.
- **Daily Auto-Reconnect**: restart policy for long-running reliability.
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

This shared GitHub config is scoped to the **IBKR deployment pair only** (`InteractiveBrokersPlatform` + `IBKRGatewayManager`). It should not be treated as a platform-wide secret set for unrelated quant projects. Secrets such as `GCP_SA_KEY`, `SSH_PRIVATE_KEY`, `TWS_USERID`, and `TWS_PASSWORD` remain repository-specific deployment credentials for this gateway module.

### 3. Start IBKR Gateway

```bash
docker compose up -d --build
sudo bash ./scripts/install_2fa_bot_watcher.sh
```

> If you use this repository's GitHub Actions workflow, pushing to `main` also triggers automatic deployment to GCE.

### 4. Verify on GCE VM

```bash
docker compose ps
ss -lntp | grep -E '4001|4002'
```

Expected: host is listening on `0.0.0.0:4001` and/or `0.0.0.0:4002` (or VM private interface) and container is healthy.

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
5. **Push to `main`** to trigger deployment workflow.

### GitHub Config for Auto Deploy

**GitHub Secrets**

| Secret | Purpose |
| :--- | :--- |
| `GCP_SA_KEY` | GCP service account JSON key |
| `SSH_PRIVATE_KEY` | SSH private key for VM login |
| `TWS_USERID` | IBKR username |
| `TWS_PASSWORD` | IBKR password |
| `TOTP_SECRET` | IBKR TOTP secret |
| `VNC_SERVER_PASSWORD` | VNC password |

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
