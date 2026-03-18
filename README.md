# IBKR Gateway Manager

An automated deployment solution for IBKR Gateway on Google Compute Engine (GCE). Solves two major pain points for cloud-based quant trading: **automated 2FA login** and **daily auto-reconnect**.

## Features

- **Containerized Deployment**: Docker-based setup, one-click spin-up.
- **Automated 2FA**: Python bot using `pyotp` + `xdotool` auto-fills the 6-digit TOTP code.
- **GCP-Native CI/CD**: Deploys via GitHub Actions using IAP tunnel — no IP whitelisting needed, survives VM IP changes.
- **Daily Auto-Reconnect**: Restarts every day at 00:00 UTC (08:00 Beijing Time) to keep the session fresh.
- **Secure Credential Management**: All secrets managed via GitHub Secrets, nothing hardcoded.

## Project Structure

```
.
├── .github/workflows/
│   └── main.yml          # GitHub Actions CI/CD workflow
├── 2fa_bot.py            # 2FA auto-fill bot
├── Dockerfile            # Extends base image with pre-installed dependencies
├── docker-compose.yml    # Container orchestration
└── requirements.txt      # Python dependencies
```

---

## Quick Start

### 1. Prerequisites

- A **Google Compute Engine** VM running Linux with Docker and Docker Compose installed.
- The project cloned to `/home/<your_username>/ib-docker` on the VM.
- An Interactive Brokers account with **TOTP (Google Authenticator)** 2FA enabled.

### 2. GCP Setup

**Create a Service Account** (IAM & Admin → Service Accounts → Create):
- Grant the following roles:
  - `Compute OS Admin Login`
  - `Service Account User`
  - `IAP-secured Tunnel User`
  - `Compute Instance Admin (v1)`
- Generate a **JSON key** and download it.

**Add IAP Firewall Rule** (VPC Network → Firewall → Create):
- Direction: Ingress
- Source IPv4: `35.235.240.0/20`
- Protocol/Port: TCP `22`
- Target: All instances (or your VM's network tag)

**Generate an SSH Key Pair** on your VM:
```bash
ssh-keygen -t rsa -b 4096 -m PEM -f ~/.ssh/github_actions_rsa -N ""
cat ~/.ssh/github_actions_rsa.pub >> ~/.ssh/authorized_keys
```

### 3. Configure GitHub Secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Description |
| :--- | :--- |
| `GCP_SA_KEY` | Full contents of the service account JSON key file |
| `SSH_PRIVATE_KEY` | Contents of `~/.ssh/github_actions_rsa` (RSA PEM format) |
| `TWS_USERID` | IBKR account username |
| `TWS_PASSWORD` | IBKR account password |
| `TOTP_SECRET` | Base32 TOTP secret key (from Google Authenticator setup) |
| `VNC_SERVER_PASSWORD` | Password for VNC desktop access |
| `TRADING_MODE` | `paper` for paper trading, `live` for live trading |

### 4. Update Deployment Path

In [`.github/workflows/main.yml`](.github/workflows/main.yml), update the path to match your VM username:
```yaml
cd /home/<your_username>/ib-docker
```

### 5. Deploy

Push to the `main` branch. GitHub Actions will:
1. Authenticate to GCP via the service account.
2. Connect to the VM via IAP tunnel (no public IP needed).
3. Pull the latest code, write the `.env` file, and rebuild the Docker image.
4. Restart the container and launch the 2FA bot as a daemon.

The workflow also runs automatically every day at **00:00 UTC (08:00 Beijing Time)**.

---

## Operational Commands

Run these on your VM via SSH.

### View 2FA Bot Logs
```bash
docker exec ib-gateway tail -f /home/ibgateway/2fa.log
```

### Check Bot Status
```bash
docker exec ib-gateway pgrep -f 2fa_bot.py
```

### Access Gateway UI via VNC

VNC is bound to localhost for security. Use an SSH tunnel to connect:
```bash
ssh -L 5900:localhost:5900 <your_username>@<vm_external_ip>
```
Then open a VNC client and connect to `localhost:5900`.

On macOS, you can use Finder → Go → Connect to Server:
```
vnc://localhost:5900
```

### Connect via API

| Trading Mode | Port |
| :--- | :--- |
| Paper Trading | `4002` |
| Live Trading | `4001` |

API ports are also bound to `127.0.0.1`. Use an SSH tunnel the same way as VNC.

---

## Troubleshooting

**Workflow fails with `dial tcp: i/o timeout`**
- Verify the IAP firewall rule (`35.235.240.0/20`, TCP 22) exists.
- Verify the service account has all four required roles.

**Workflow fails with `Could not add SSH key to instance metadata`**
- Add the `Compute Instance Admin (v1)` role to the service account.

**2FA bot not filling the code**
- Check logs: `docker exec ib-gateway tail -f /home/ibgateway/2fa.log`
- Verify `TOTP_SECRET` is the correct base32 key from your authenticator setup.

**SSH into VM stops working after restart**
- Enable SSH to auto-start: `sudo systemctl enable ssh && sudo systemctl enable ssh.socket`

---

## License

MIT
