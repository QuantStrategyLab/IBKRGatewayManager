import pyotp
import base64
import logging
import time
import subprocess
import os
import sys
from dataclasses import dataclass
from typing import Optional

# ================= Configuration =================
SECRET_KEY = os.environ.get("TOTP_SECRET")
X11_DISPLAY = os.environ.get("DISPLAY_NUM", ":1")
AUTOFILL_ENABLED = os.environ.get("IBKR_2FA_AUTOFILL", "yes").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

# Timing constants (seconds)
CHECK_INTERVAL = 3
FILL_COOLDOWN = 60
TYPE_DELAY_MS = 100
PRE_ENTER_DELAY = 1
XDOTOOL_TIMEOUT = 10
MIN_TOTP_SECONDS_REMAINING = 8
MAX_AUTOFILL_SUBMISSIONS_RAW = os.environ.get("IBKR_2FA_MAX_SUBMISSIONS", "1")

# Window titles to search for 2FA prompts. Live IBKR accounts can show mobile
# push / IB Key wording instead of the shorter TOTP-oriented prompts.
SEARCH_PATTERNS = [
    "Second Factor",
    "Challenge",
    "Security Code",
    "Enter Code",
    "IBKR Mobile",
    "IB Key",
    "Two-Factor",
    "Two Factor",
    "Verification",
    "Verify",
    "Authentication",
]
AUTH_TITLE_KEYWORDS = (
    "second factor",
    "challenge",
    "security code",
    "enter code",
    "ibkr mobile",
    "ib key",
    "two-factor",
    "two factor",
    "verification",
    "verify",
    "authentication",
)
IGNORED_TITLE_KEYWORDS = (
    "authenticating",
)
INPUT_CLICK_POSITION = (0.50, 0.62)
# =================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("2fa_bot")
try:
    MAX_AUTOFILL_SUBMISSIONS = int(MAX_AUTOFILL_SUBMISSIONS_RAW)
except ValueError:
    log.error("IBKR_2FA_MAX_SUBMISSIONS must be an integer")
    sys.exit(1)
autofill_submission_count = 0
autofill_limit_warned = False


@dataclass(frozen=True)
class WindowCandidate:
    window_id: str
    title: str
    width: Optional[int] = None
    height: Optional[int] = None


def validate_config():
    """Validate required config at startup; exit immediately if invalid."""
    if not AUTOFILL_ENABLED:
        log.info("TOTP auto-fill is disabled; bot will only log auth popup detection")
        return
    if MAX_AUTOFILL_SUBMISSIONS < 1:
        log.error("IBKR_2FA_MAX_SUBMISSIONS must be at least 1")
        sys.exit(1)
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


def totp_seconds_remaining():
    return 30 - (int(time.time()) % 30)


def run_xdotool(args, sensitive=False):
    """Execute xdotool command on the X11 display with timeout protection."""
    env = os.environ.copy()
    env["DISPLAY"] = X11_DISPLAY
    command = ["xdotool", *args]
    try:
        return subprocess.run(
            command, env=env,
            capture_output=True, text=True,
            timeout=XDOTOOL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        display_command = "xdotool <redacted>" if sensitive else " ".join(command)
        log.warning("xdotool command timed out: %s", display_command)
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="timeout")


def get_window_title(window_id):
    res = run_xdotool(["getwindowname", window_id])
    return res.stdout.strip()


def get_window_geometry(window_id):
    res = run_xdotool(["getwindowgeometry", "--shell", window_id])
    if res.returncode != 0:
        return None, None

    values = {}
    for line in res.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value

    try:
        return int(values.get("WIDTH", "")), int(values.get("HEIGHT", ""))
    except ValueError:
        return None, None


def is_auth_candidate(title):
    normalized_title = title.lower()
    if any(keyword in normalized_title for keyword in IGNORED_TITLE_KEYWORDS):
        return False
    return any(keyword in normalized_title for keyword in AUTH_TITLE_KEYWORDS)


def find_auth_windows():
    """Find visible IBKR authentication windows without relying on focus state."""
    window_ids = []
    for pattern in SEARCH_PATTERNS:
        res = run_xdotool(["search", "--name", pattern])
        if res.returncode != 0:
            continue
        for window_id in res.stdout.splitlines():
            if window_id and window_id not in window_ids:
                window_ids.append(window_id)

    candidates = []
    for window_id in reversed(window_ids):
        title = get_window_title(window_id)
        if not is_auth_candidate(title):
            continue
        width, height = get_window_geometry(window_id)
        candidates.append(WindowCandidate(window_id, title, width, height))
    return candidates


def wait_for_fresh_totp_window():
    seconds_remaining = totp_seconds_remaining()
    if seconds_remaining > MIN_TOTP_SECONDS_REMAINING:
        return seconds_remaining

    wait_seconds = seconds_remaining + 1
    log.info(
        "TOTP period has %ss remaining; waiting %ss before submitting a fresh code",
        seconds_remaining,
        wait_seconds,
    )
    time.sleep(wait_seconds)
    return totp_seconds_remaining()


def focus_input_area(candidate):
    if not candidate.width or not candidate.height:
        return

    x = max(1, int(candidate.width * INPUT_CLICK_POSITION[0]))
    y = max(1, int(candidate.height * INPUT_CLICK_POSITION[1]))
    run_xdotool(["windowactivate", "--sync", candidate.window_id])
    run_xdotool(["windowfocus", "--sync", candidate.window_id])
    run_xdotool(["mousemove", "--window", candidate.window_id, str(x), str(y)])
    run_xdotool(["click", "1"])


def submit_totp(candidate):
    """Submit a TOTP code to the selected authentication popup."""
    global autofill_limit_warned
    global autofill_submission_count

    if not AUTOFILL_ENABLED:
        log.info(
            "Authentication window found (id=%s, title=%r, size=%sx%s); auto-fill disabled",
            candidate.window_id,
            candidate.title,
            candidate.width or "?",
            candidate.height or "?",
        )
        return

    if autofill_submission_count >= MAX_AUTOFILL_SUBMISSIONS:
        if not autofill_limit_warned:
            log.warning(
                "Authentication window found but auto-fill submission limit reached "
                "(limit=%s); leaving window for manual handling",
                MAX_AUTOFILL_SUBMISSIONS,
            )
            autofill_limit_warned = True
        return

    seconds_remaining = wait_for_fresh_totp_window()
    log.info(
        "Authentication window found (id=%s, title=%r, size=%sx%s); submitting code with %ss remaining",
        candidate.window_id,
        candidate.title,
        candidate.width or "?",
        candidate.height or "?",
        seconds_remaining,
    )

    focus_input_area(candidate)
    code = get_totp()

    run_xdotool(["key", "--window", candidate.window_id, "ctrl+a", "BackSpace"])
    run_xdotool(
        ["type", "--window", candidate.window_id, "--delay", str(TYPE_DELAY_MS), code],
        sensitive=True,
    )
    time.sleep(PRE_ENTER_DELAY)
    run_xdotool(["key", "--window", candidate.window_id, "Return"])

    autofill_submission_count += 1
    log.info("Auto-fill submitted, waiting for gateway response...")


def find_and_fill():
    """Search for the IBKR Gateway authentication window and auto-fill the code."""
    candidates = find_auth_windows()
    for candidate in candidates:
        submit_totp(candidate)
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
