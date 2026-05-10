import pyotp
import base64
import logging
import time
import subprocess
import os
import sys

# ================= Configuration =================
SECRET_KEY = os.environ.get("TOTP_SECRET")
X11_DISPLAY = os.environ.get("DISPLAY_NUM", ":1")

# Timing constants (seconds)
CHECK_INTERVAL = 3
FILL_COOLDOWN = 60
TYPE_DELAY_MS = 100
PRE_ENTER_DELAY = 1
XDOTOOL_TIMEOUT = 10

# Window titles to search for 2FA prompt
SEARCH_TITLES = ["'Challenge'", "'Second Factor'", "'Security Code'", "'Enter Code'"]
# =================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("2fa_bot")


def validate_config():
    """Validate required config at startup; exit immediately if invalid."""
    if not SECRET_KEY:
        log.error("TOTP_SECRET not found in environment variables")
        sys.exit(1)
    try:
        base64.b32decode(SECRET_KEY.upper().replace(" ", ""), casefold=True)
    except Exception:
        log.error("TOTP_SECRET is not valid base32")
        sys.exit(1)


def get_totp():
    """Calculate 6-digit dynamic verification code using pyotp."""
    return pyotp.TOTP(SECRET_KEY).now()


def run_xdotool(command):
    """Execute xdotool command on the X11 display with timeout protection."""
    env = os.environ.copy()
    env["DISPLAY"] = X11_DISPLAY
    try:
        return subprocess.run(
            command, shell=True, env=env,
            capture_output=True, text=True,
            timeout=XDOTOOL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.warning("xdotool command timed out: %s", command)
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="timeout")


def find_and_fill():
    """Search for the IBKR Gateway login window and auto-fill the code."""
    for title in SEARCH_TITLES:
        res = run_xdotool(f"xdotool search --name {title}")
        window_id = res.stdout.strip()

        if window_id:
            window_id = window_id.split('\n')[-1]
            log.info("Verification window found (ID: %s), filling code...", window_id)

            run_xdotool(f"xdotool windowactivate --sync {window_id}")
            run_xdotool(f"xdotool windowfocus --sync {window_id}")

            code = get_totp()

            run_xdotool(f"xdotool key --window {window_id} ctrl+a BackSpace")
            run_xdotool(f"xdotool type --delay {TYPE_DELAY_MS} '{code}'")
            time.sleep(PRE_ENTER_DELAY)
            run_xdotool(f"xdotool key --window {window_id} Return")

            log.info("Auto-fill submitted, waiting for gateway response...")
            return True
    return False


def main():
    validate_config()
    log.info("IBKR 2FA Bot started, monitoring display %s", X11_DISPLAY)

    while True:
        try:
            if find_and_fill():
                time.sleep(FILL_COOLDOWN)
        except Exception as e:
            log.exception("Runtime exception: %s", e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
