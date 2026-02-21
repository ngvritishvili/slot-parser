import os
import time
import random
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIG ---
CASINO_ID = 2
API_BASE = os.getenv('API_ENDPOINT_BASE', 'http://checkthisone.online')
API_GET_SLOTS = f"{API_BASE}/api/casinos/{CASINO_ID}/slots"
API_UPDATE_SLOT = f"{API_BASE}/api/slots/update-details"
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
STATE_FILE = "stake_state.json"

USER_LOGIN = os.getenv('CASINO_USER')
USER_PASS = os.getenv('CASINO_PASS')


def perform_login(p):
    if not USER_LOGIN or not USER_PASS:
        print("[ERROR] CASINO_USER or CASINO_PASS missing in .env")
        return False

    print(f"[Login] Initializing browser for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(
        viewport={'width': 1280, 'height': 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        print("    [Navigation] Loading Stake Login...")
        page.goto("https://stake.com/?modal=auth&tab=login", wait_until="commit", timeout=60000)

        # 1. Clear Cookie Banner (As seen in your screenshots)
        try:
            page.get_by_role("button", name="Accept").click(timeout=5000)
            print("    [Action] Cookies accepted.")
        except:
            pass

        # 2. Wait for form and fill
        page.wait_for_selector('[data-testid="login-name"]', timeout=30000)
        page.locator('[data-testid="login-name"]').fill(str(USER_LOGIN))
        page.wait_for_timeout(random.randint(500, 1000))
        page.locator('[data-testid="login-password"]').fill(str(USER_PASS))

        print("    [Action] Clicking Sign In...")
        page.locator('[data-testid="button-login"]').click()
        page.screenshot(path="stake_03_clicked_loading.png")

        # 3. ROBUST WAIT FOR SESSION
        print("    [Verification] Waiting for login to process (up to 60s)...")

        # We wait for the 'Wallet' button or the 'User Menu' which only exists when logged in.
        # Alternatively, we wait for the login modal to be detached/hidden.
        try:
            # Selector for Stake's wallet/balance display
            page.wait_for_selector('[data-testid="wallet-selector"], .user-menu', timeout=60000)
            print("    [Login] Success! Logged in element detected.")

            # Give it 5 more seconds to let Svelte finish setting local storage/cookies
            time.sleep(5)
            context.storage_state(path=STATE_FILE)
            page.screenshot(path="stake_04_verified_login.png")
            browser.close()
            return True

        except Exception:
            print("    [Error] Login verification failed. Checking for blocks...")
            page.screenshot(path="stake_error_final_state.png")
            # Check for 2FA or Cloudflare
            if "verify you are human" in page.content().lower():
                print("    [!] Stuck on Cloudflare verification.")
            elif "two factor" in page.content().lower():
                print("    [!] Account requires 2FA.")

            browser.close()
            return False

    except Exception as e:
        print(f"[CRITICAL LOGIN ERROR] {e}")
        browser.close()
        return False


# ... (Rest of parse_slot_details and run() remain the same)

if __name__ == "__main__":
    from SportBetCLI2 import run  # Assuming the rest of your logic is here

    run()