import pyotp
import time
import subprocess
import os
import sys

# ================= Configuration =================
# Read secret key from environment variables
SECRET_KEY = os.environ.get("TOTP_SECRET")

# Check interval (seconds)
CHECK_INTERVAL = 3 
# =================================================

def get_totp():
    """Calculate 6-digit dynamic verification code using pyotp"""
    if not SECRET_KEY:
        print("❌ Error: TOTP_SECRET not found in environment variables!")
        sys.exit(1)
    totp = pyotp.TOTP(SECRET_KEY)
    return totp.now()

def run_xdotool(command):
    """Execute simulated commands on the X11 display inside the Docker container"""
    env = os.environ.copy()
    # The default X display number for the image is usually :1
    env["DISPLAY"] = ":1" 
    return subprocess.run(command, shell=True, env=env, capture_output=True, text=True)

def find_and_fill():
    """Search for the IBKR Gateway login window and auto-fill the code"""
    # Match various possible 2FA window titles
    search_titles = ["'Challenge'", "'Second Factor'", "'Security Code'", "'Enter Code'"]
    
    for title in search_titles:
        res = run_xdotool(f"xdotool search --name {title}")
        window_id = res.stdout.strip()
        
        if window_id:
            # If multiple windows exist, take the latest ID
            window_id = window_id.split('\n')[-1]
            print(f"🎯 Verification window found (ID: {window_id}), filling code...")
            
            # 1. Force activate and focus the window to ensure input doesn't shift
            run_xdotool(f"xdotool windowactivate --sync {window_id}")
            run_xdotool(f"xdotool windowfocus --sync {window_id}")
            
            # 2. Generate verification code
            code = get_totp()
            
            # 3. Simulate keyboard: Clear input box -> Type code -> Press Enter
            run_xdotool(f"xdotool key --window {window_id} ctrl+a BackSpace")
            run_xdotool(f"xdotool type --delay 100 '{code}'")
            time.sleep(1)
            run_xdotool(f"xdotool key --window {window_id} Return")
            
            print(f"✅ Auto-fill successful: {code}, waiting for gateway response...")
            return True
    return False

def main():
    print("🤖 IBKR 2FA Bot has started...")
    print(f"📡 Monitoring login window on display :1 ...")
    
    while True:
        try:
            if find_and_fill():
                # Cool down for 60 seconds after success to avoid duplicate input in the same window
                time.sleep(60) 
        except Exception as e:
            print(f"⚠️ Runtime exception: {e}")
        
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
