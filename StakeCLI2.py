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

# Using CASINO_USER as per your instruction
USER_LOGIN = os.getenv('CASINO_USER')
USER_PASS = os.getenv('CASINO_PASS')

VOLATILITY_MAP = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "very high": 4,
    "extreme": 5
}


def perform_login(p):
    if not USER_LOGIN or not USER_PASS:
        print("[ERROR] CASINO_USER or CASINO_PASS missing in .env file")
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
        # 1. Navigate to login modal
        print("    [Navigation] Loading login page...")
        page.goto("https://stake.com/?tab=login&modal=auth", wait_until="commit", timeout=60000)

        # 2. Wait for the specific data-testid elements you provided
        page.wait_for_selector('[data-testid="login-name"]', timeout=30000)
        page.screenshot(path="debug_login_loaded.png")

        print("    [Action] Filling credentials...")
        # Stake uses 'emailOrName' internally but data-testid is the safest bet
        page.locator('[data-testid="login-name"]').fill(str(USER_LOGIN))
        page.wait_for_timeout(random.randint(400, 800))
        page.locator('[data-testid="login-password"]').fill(str(USER_PASS))

        page.screenshot(path="debug_login_filled.png")

        print("    [Action] Clicking Sign In...")
        # Targeted the Sign In button using its testid
        page.locator('[data-testid="button-login"]').click()

        # 3. Verification
        print("    [Verification] Waiting for session to establish...")
        # Wait for the modal to close (it removes modal=auth from URL)
        page.wait_for_url(lambda url: "modal=auth" not in url, timeout=45000)

        print("    [Login] SUCCESS. Saving state...")
        time.sleep(5)
        context.storage_state(path=STATE_FILE)
        page.screenshot(path="debug_login_success.png")

        browser.close()
        return True
    except Exception as e:
        print(f"[CRITICAL LOGIN ERROR] {e}")
        page.screenshot(path="debug_stake_login_crash.png")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if not url: return None

    print(f"\n[Scraper] Visiting: {slot.get('title')}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # Stake slots take time to render the 'Game Info' button
        time.sleep(6)

        # Look for the "Game info" button (common on Stake slots)
        # Based on Svelte structure, we try the text selector first
        info_btn = page.get_by_role("button", name="Game info")
        if info_btn.is_visible():
            info_btn.click()
            time.sleep(2)
        else:
            # Try to find any button that might open description
            page.mouse.wheel(0, 500)
            time.sleep(1)

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}

        # Parsing the Svelte table
        rows = page.query_selector_all('tbody tr')
        if not rows:
            print("    [!] Table not found. Capturing screen.")
            page.screenshot(path=f"fail_table_{slot.get('id')}.png")

        for row in rows:
            cells = row.query_selector_all('td')
            if len(cells) >= 2:
                label = cells[0].inner_text().strip().lower()
                value = cells[1].inner_text().strip()

                if "rtp" in label:
                    extracted["theoretical_rtp"] = value.replace('%', '').strip()
                elif "volatility" in label:
                    # Clean 'Very High' -> 'very high'
                    extracted["volatility_level"] = VOLATILITY_MAP.get(value.lower())
                elif "max win" in label:
                    extracted["max_win_multiplier"] = value.lower().replace('x', '').replace(',', '').strip()

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
    except Exception as e:
        print(f"[Error] API connection failed: {e}")
        return

    if not slots:
        print("[Finish] No slots to process.")
        return

    with sync_playwright() as p:
        if not os.path.exists(STATE_FILE):
            if not perform_login(p): return

        # Load session
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        # Initial rest on dashboard
        page.goto("https://stake.com/casino/slots", wait_until="domcontentloaded")
        time.sleep(10)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                try:
                    requests.post(API_UPDATE_SLOT, json={"slot_id": slot['id'], **data}, timeout=10)
                    print(f"    [DB] {slot['title']} updated.")
                except:
                    print("    [DB Error] Update failed.")

            # Human-like delay between items
            time.sleep(random.randint(10, 20))

        browser.close()


if __name__ == "__main__":
    run()