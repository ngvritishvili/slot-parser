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

VOLATILITY_MAP = {
    "low": 1, "medium": 2, "high": 3, "very high": 4, "extreme": 5
}


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
        print("    [Navigation] Loading Stake Base...")
        page.goto("https://stake.com/?modal=auth&tab=login", wait_until="commit", timeout=60000)

        # Wait for the modal to be visible
        page.wait_for_selector('[data-testid="login-name"]', timeout=45000)
        page.screenshot(path="stake_01_modal_open.png")

        # Handle the "Accept Cookies" button if it exists (visible in your screenshots)
        try:
            cookie_btn = page.get_by_role("button", name="Accept")
            if cookie_btn.is_visible():
                print("    [Action] Clearing cookie banner...")
                cookie_btn.click()
                time.sleep(1)
        except:
            pass

        print("    [Action] Filling credentials...")
        page.locator('[data-testid="login-name"]').fill(str(USER_LOGIN))
        page.wait_for_timeout(random.randint(500, 1000))
        page.locator('[data-testid="login-password"]').fill(str(USER_PASS))
        page.screenshot(path="stake_02_filled.png")

        print("    [Action] Clicking Sign In...")
        # Use a force-click and wait for the click to register
        submit_btn = page.locator('[data-testid="button-login"]')
        submit_btn.click()

        # --- LONGER WAIT FOR SESSION ---
        print("    [Verification] Login sent. Waiting 25 seconds for session/redirect...")

        # Instead of just checking URL, we wait for a specific element that exists
        # only when logged in (like the Wallet or Account menu)
        success = False
        for i in range(25):
            # Check if modal is gone OR if user menu is visible
            current_url = page.url
            if "modal=auth" not in current_url:
                print(f"    [Login] URL changed at {i}s. Redirecting...")
                success = True
                break

            # Look for 2FA as a fail state
            if "two factor" in page.content().lower():
                print("    [!] 2FA Screen detected. Saving screenshot.")
                page.screenshot(path="stake_error_2fa_manual.png")
                break

            time.sleep(1)

        if success:
            # Crucial: Give it more time to finish loading the dashboard and set cookies
            print("    [Wait] Stabilizing session (15s extra)...")
            time.sleep(15)

            page.screenshot(path="stake_03_post_login.png")
            context.storage_state(path=STATE_FILE)
            print("    [Login] Success! State saved.")
            browser.close()
            return True
        else:
            page.screenshot(path="stake_error_stuck.png")
            print("    [Error] Login timed out or redirected improperly.")
            browser.close()
            return False

    except Exception as e:
        print(f"[CRITICAL LOGIN ERROR] {e}")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if not url: return None

    print(f"\n[Scraper] Visiting: {slot.get('title')}")
    try:
        page.goto(url, wait_until="commit", timeout=60000)
        # Give Stake slots more time; they have heavy animations
        time.sleep(12)

        page.mouse.wheel(0, 500)
        time.sleep(2)

        # Attempt to open the info panel
        info_btn = page.get_by_role("button", name="Game info", exact=False)
        if info_btn.is_visible():
            info_btn.click()
            time.sleep(3)

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}
        rows = page.query_selector_all('tbody tr')

        for row in rows:
            cells = row.query_selector_all('td')
            if len(cells) >= 2:
                label = cells[0].inner_text().strip().lower()
                val = cells[1].inner_text().strip()
                if "rtp" == label:
                    extracted["theoretical_rtp"] = val.replace('%', '').strip()
                elif "volatility" == label:
                    extracted["volatility_level"] = VOLATILITY_MAP.get(val.lower())
                elif "max win" == label:
                    extracted["max_win_multiplier"] = val.lower().replace('x', '').replace(',', '').strip()

        print(f"    [Data] {extracted}")
        return extracted
    except Exception as e:
        print(f"    [Skip] {slot.get('title')} error: {str(e)[:50]}")
        return None


def run():
    print(f"[Start] Stake Scanner (Casino ID: {CASINO_ID})")
    try:
        res = requests.post(API_GET_SLOTS, timeout=20)
        slots = res.json() if res.status_code == 200 else []
    except:
        return

    with sync_playwright() as p:
        if not os.path.exists(STATE_FILE):
            if not perform_login(p): return

        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        # Verify session is valid by checking dashboard
        page.goto("https://stake.com/casino/slots", wait_until="commit")
        time.sleep(15)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                try:
                    requests.post(API_UPDATE_SLOT, json={"slot_id": slot['id'], **data}, timeout=10)
                    print(f"    [DB] {slot['title']} updated.")
                except:
                    pass

            # Slow down to avoid being flagged after login
            time.sleep(random.randint(15, 25))

        browser.close()


if __name__ == "__main__":
    run()