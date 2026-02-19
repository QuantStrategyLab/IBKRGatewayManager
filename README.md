# 🚀 IBKR Gateway Manager

This is an **automated deployment solution for IBKR Gateway**, designed specifically for quantitative trading developers. It solves two major pain points when running the Interactive Brokers gateway in the cloud (e.g., GCE): **tedious 2FA logins** and **periodic connection refreshes**.

## 🌟 Core Features

- **Containerized Deployment**: Spin up the IBKR Gateway environment with one click using Docker.
- **Automated 2FA Bypass**: Integrated Python bot using `pyotp` and `xdotool` to automatically calculate and fill the 6-digit TOTP code.
- **Robust CI/CD**: Remote deployment to Google Compute Engine (GCE) via GitHub Actions with built-in retry logic for stable installation.
- **Daily Auto-Reconnect**: Automatically restarts every day at 00:00 UTC (08:00 Beijing Time) to ensure the gateway is fresh for the US market session.
- **Maximum Security**: Sensitive credentials (account, 2FA secret) are managed via GitHub Secrets—no hardcoded passwords in the repository.

## 🏗️ Project Structure

```text
.
├── .github/workflows/
│   └── deploy.yml          # GitHub Actions CI/CD script
├── 2fa_bot.py              # 2FA auto-fill bot (Python)
├── docker-compose.yml      # Docker container orchestration
├── requirements.txt        # Python dependencies
└── .gitignore              # Git ignore rules
```

---

## 🚀 Getting Started

### 1. Prerequisites
- A remote Linux server (e.g., **Google Compute Engine**).
- **Docker** and **Docker Compose** installed on the server.
- Interactive Brokers account with **TOTP (Google Authenticator)** enabled.

### 2. Configure GitHub Secrets
To enable automated deployment, add the following secrets to the GitHub repository (**Settings > Secrets and variables > Actions**):

| Secret Name | Description |
| :--- | :--- |
| `GCE_HOST` | server's public IP address |
| `GCE_USERNAME` | SSH username |
| `SSH_PRIVATE_KEY` | private SSH key for server access |
| `TWS_USERID` | IBKR account username |
| `TWS_PASSWORD` | IBKR account password |
| `TOTP_SECRET` | The base32 secret key for 2FA (TOTP) |
| `VNC_SERVER_PASSWORD` | Password to access the gateway's visual desktop via VNC |
| `TRADING_MODE` | Set to paper for simulated trading or live for real trading |

### 3. Deployment
Simply push the code to the `main` branch. GitHub Actions will:
1. SSH into the server.
2. Pull the latest code and environment variables.
3. Restart the Docker container.
4. Auto-install dependencies and launch the `2fa_bot.py` as a daemon.

---

## 🛠️ Operational Commands

### View Bot Status
Check if the 2FA bot is successfully filling in the code:
```bash
docker exec ib-gateway tail -f /home/ibgateway/2fa.log
```

### Access Gateway UI
You can view the IBKR Gateway GUI by connecting to your server's IP on port `5900` using a VNC viewer (e.g., RealVNC, TigerVNC).

### Connect via API

The port depends on your `TRADING_MODE` setting in GitHub Secrets:

| Trading Mode | Port (Default) |
| :--- | :--- |
| **Paper Trading** | `4002` |
| **Live Trading** | `4001` |

**Configuration:**
To switch between modes, update the `TRADING_MODE` variable in your `docker-compose.yml` or GitHub Secrets:
- For Paper Trading: `- TRADING_MODE=paper`
- For Live Trading: `- TRADING_MODE=live`

---

## ⚠️ Troubleshooting
- **Apt Lock Issues**: The deployment script includes a 5-time retry loop to handle cases where the system is running background updates.
- **VNC Black Screen**: This is usually a screen-saver or the window-focusing logic. The bot will automatically attempt to focus and activate the login window when it appears.

---

## 📜 License
This project is licensed under the MIT License.
