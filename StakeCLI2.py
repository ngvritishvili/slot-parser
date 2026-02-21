import os
import time
import random
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIG ---
CASINO_ID = 2  # Updated for Stake
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

    print(f"[Login] Opening Stake for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(
        viewport={'width': 1280, 'height': 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        # 1. Navigate to Stake Login Modal directly
        print("    [Navigation] Loading Stake Login...")
        page.goto("https://stake.com/?modal=auth&tab=login", wait_until="domcontentloaded", timeout=60000)

        # 2. Wait for the form to appear (Using the data-testid from your previous HTML)
        page.wait_for_selector('[data-testid="login-name"]', timeout=30000)
        page.screenshot(path="stake_01_form_visible.png")

        # Clear cookie banner if it exists
        try:
            page.get_by_role("button", name="Accept").click(timeout=5000)
        except:
            pass

        print("    [Action] Filling credentials...")
        page.locator('[data-testid="login-name"]').fill(str(USER_LOGIN))
        page.wait_for_timeout(random.randint(400, 800))
        page.locator('[data-testid="login-password"]').fill(str(USER_PASS))

        print("    [Action] Clicking Sign In...")
        page.locator('[data-testid="button-login"]').click()
        page.screenshot(path="stake_02_clicked.png")

        # 3. Wait for post-login state
        print("    [Verification] Waiting for session stabilization (45s)...")
        # Wait for the wallet to appear (shows we are logged in)
        try:
            page.wait_for_selector('[data-testid="wallet-selector"]', timeout=45000)
            print("    [Login] Success! Wallet detected.")

            # Critical: Wait for Svelte to finish writing session data to storage
            time.sleep(10)

            context.storage_state(path=STATE_FILE)
            page.screenshot(path="stake_03_logged_in.png")
            browser.close()
            return True
        except Exception:
            print("    [Error] Timed out waiting for dashboard.")
            page.screenshot(path="stake_error_login_stuck.png")
            browser.close()
            return False

    except Exception as e:
        print(f"[CRITICAL LOGIN ERROR] {e}")
        page.screenshot(path="stake_critical_crash.png")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if not url: return None

    print(f"\n[Scraper] Visiting: {slot.get('title')}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(10)  # Heavy Svelte components need time

        # Open "Game info" table
        info_btn = page.get_by_role("button", name="Game info", exact=False)
        if info_btn.is_visible():
            info_btn.click()
            time.sleep(2)

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}
        rows = page.query_selector_all('tbody tr')

        for row in rows:
            cells = row.query_selector_all('td')
            if len(cells) >= 2:
                label = cells[0].inner_text().strip().lower()
                val = cells[1].inner_text().strip()
                if "rtp" == label:
                    extracted["theoretical_rtp"] = val.replace('%', '').strip()
                elif "volatility" in label:
                    extracted["volatility_level"] = VOLATILITY_MAP.get(val.lower())
                elif "max win" in label:
                    extracted["max_win_multiplier"] = val.lower().replace('x', '').replace(',', '').strip()

        print(f"    [Data] {extracted}")
        return extracted
    except Exception as e:
        print(f"    [Skip] {slot.get('title')} error: {str(e)[:30]}")
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

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                try:
                    requests.post(API_UPDATE_SLOT, json={"slot_id": slot['id'], **data}, timeout=10)
                    print(f"    [DB] {slot['title']} updated.")
                except:
                    pass
            time.sleep(random.randint(5, 12))
        browser.close()


if __name__ == "__main__":
    run()