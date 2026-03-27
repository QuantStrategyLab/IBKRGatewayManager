# IBKR Gateway Manager

An automated deployment solution for IBKR Gateway on Google Compute Engine (GCE), with automated 2FA and daily reconnect.

> ✅ Current target architecture: **Cloud Run → Serverless VPC Access → GCE private IP:4001**.

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
Serverless VPC Access Connector
   ▼
VPC (same region/network)
   ▼
GCE VM (private IP)
   ▼
Docker: ib-gateway container (port 4001)
```

For this architecture to work:

1. `ib-gateway` must listen for remote API clients (not localhost-only).
2. Host port `4001` must be published on the VM.
3. VPC firewall must allow source = Cloud Run/VPC connector CIDR to destination VM TCP `4001`.

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

# Recommended: use the exact CIDR used by your Serverless VPC Access connector
# Example: 10.8.0.0/28
ACCEPT_API_FROM_IP=10.8.0.0/28

# Must be 'no' for Cloud Run private IP access
ALLOW_CONNECTIONS_FROM_LOCALHOST_ONLY=no
```

### 3. Start IBKR Gateway

```bash
docker compose up -d --build
sudo bash ./scripts/install_2fa_bot_watcher.sh
```

> If you use this repository's GitHub Actions workflow, pushing to `main` also triggers automatic deployment to GCE.

### 4. Verify on GCE VM

```bash
docker compose ps
ss -lntp | grep 4001
```

Expected: host is listening on `0.0.0.0:4001` (or VM private interface) and container is healthy.

---

## Cloud Run Connectivity Checklist

1. Cloud Run service uses **Serverless VPC Access connector**.
2. Cloud Run egress is configured correctly (`all-traffic` or `private-ranges-only`, depending on your route design).
3. Firewall rule allows connector CIDR (or Cloud Run egress range) to VM TCP `4001`.
4. Application uses `GCE_PRIVATE_IP:4001` as IBKR endpoint.

---

## Recreate GCE and Deploy (Recommended Flow)

When recreating your VM, use this order:

1. **Create GCE VM** (Ubuntu recommended) in the same VPC/region path reachable from Cloud Run.
2. **Install Docker + Docker Compose plugin** on the VM.
3. **Clone this repo** to your target path (for example `/home/<user>/ib-docker`).
4. **Set GitHub Secrets** so Action can redeploy automatically.
5. **Push to `main`** to trigger deployment workflow.

### Required GitHub Secrets for Auto Deploy

| Secret | Purpose |
| :--- | :--- |
| `GCP_SA_KEY` | GCP service account JSON key |
| `SSH_PRIVATE_KEY` | SSH private key for VM login |
| `GCE_USER` | VM SSH username (optional, default `zwlddx0815`) |
| `GCE_INSTANCE_NAME` | VM instance name (optional, default exists in workflow) |
| `GCE_ZONE` | VM zone (optional, default exists in workflow) |
| `DEPLOY_PATH` | Repo path on VM (optional, default exists in workflow) |
| `TWS_USERID` | IBKR username |
| `TWS_PASSWORD` | IBKR password |
| `TOTP_SECRET` | IBKR TOTP secret |
| `VNC_SERVER_PASSWORD` | VNC password |
| `TRADING_MODE` | `paper` or `live` |
| `ACCEPT_API_FROM_IP` | Cloud Run / VPC connector CIDR (example `10.8.0.0/28`) |
| `ALLOW_CONNECTIONS_FROM_LOCALHOST_ONLY` | Set to `no` for Cloud Run private IP access |

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
docker exec ib-gateway ss -lntp | grep 4001
```

---

## Security Notes

- Do **not** set `ACCEPT_API_FROM_IP=0.0.0.0/0` in production.
- Restrict firewall source to only your Cloud Run/VPC connector CIDR.
- Keep VNC (`5900`) localhost-bound or tunnel-only.

---

## Troubleshooting

### Cloud Run cannot connect to `GCE_PRIVATE_IP:4001`

- Confirm VM firewall rule exists for source connector CIDR -> TCP 4001.
- Confirm `ALLOW_CONNECTIONS_FROM_LOCALHOST_ONLY=no`.
- Confirm Docker published port is `4001:4001`.
- Confirm service and connector are in compatible region/network routing setup.

### 2FA bot not filling code

- Check logs: `docker exec ib-gateway tail -f /home/ibgateway/2fa.log`
- Verify `TOTP_SECRET` is valid Base32 secret.
- Confirm watcher timer is active: `systemctl status ibkr-2fa-bot.timer --no-pager`

---

## License

MIT
