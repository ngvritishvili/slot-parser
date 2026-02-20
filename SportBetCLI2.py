import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIG ---
CASINO_ID = 1
API_BASE = os.getenv('API_ENDPOINT_BASE', 'http://checkthisone.online')
API_GET_SLOTS = f"{API_BASE}/api/casinos/{CASINO_ID}/slots"
API_UPDATE_SLOT = f"{API_BASE}/api/slots/update-details"
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
STATE_FILE = "state.json"

USER_LOGIN = os.getenv('CASINO_USER')
USER_PASS = os.getenv('CASINO_PASS')

VOLATILITY_MAP = {"low": 1, "medium": 2, "high": 3, "very high": 4}


def perform_login(p):
    print(f"[Login] Initializing browser for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)

    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        print(f"    [Navigation] Opening login page...")
        page.goto("https://sportsbet.io/auth/login", wait_until="domcontentloaded", timeout=60000)

        print("    [Navigation] Waiting for form fields...")
        # Waiting for the specific input name from your HTML snippet
        page.wait_for_selector('input[name="username"]', timeout=30000)

        print("    [Action] Entering credentials...")
        # Using the locator pattern to ensure 'value' argument is correctly mapped
        page.locator('input[name="username"]').fill(str(USER_LOGIN))
        page.locator('input[name="password"]').fill(str(USER_PASS))

        time.sleep(1)

        print("    [Action] Clicking Sign In button...")
        # Use the submit type button found in your HTML snippet
        page.locator('button[type="submit"]').click()

        print("    [Verification] Waiting for dashboard redirect...")
        # We wait for the URL to change, indicating a successful login redirect
        page.wait_for_url(lambda url: "/auth/login" not in url, timeout=25000)

        # Give the session a moment to settle
        page.wait_for_timeout(5000)

        # Save cookies/session for the main scraper loop
        context.storage_state(path=STATE_FILE)
        print(f"[Login] SUCCESS! Currently at: {page.url}")
        browser.close()
        return True

    except Exception as e:
        print(f"[CRITICAL LOGIN ERROR] {e}")
        try:
            page.screenshot(path="login_error_debug.png")
            print("    [Debug] Screenshot saved to login_error_debug.png")
        except:
            pass
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if not url or "sportsbet.io" not in url:
        return None

    print(f"\n[Scraper] Visiting Slot: {slot.get('title')}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # SportBet is heavy on JS, so we wait for the stats to actually render
        print("    Waiting for game information to load...")
        page.wait_for_timeout(8000)

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}

        # Targeted selectors based on the SportBet UI layout
        blocks = page.query_selector_all('div.flex-col.justify-between.md\\:items-center')

        for block in blocks:
            label_el = block.query_selector('span.text-secondary')
            value_el = block.query_selector('span.truncate')

            if label_el and value_el:
                label = label_el.inner_text().lower()
                val = value_el.inner_text().strip()
                if "rtp" in label:
                    # Extracts '96.5' from '96.5%'
                    extracted["theoretical_rtp"] = val.replace('%', '').strip()
                elif "volatility" in label:
                    extracted["volatility_level"] = VOLATILITY_MAP.get(val.lower())
                elif "max win" in label:
                    # Clean up '5,000x' -> '5000'
                    extracted["max_win_multiplier"] = val.lower().replace('x', '').replace(',', '').strip()

        print(f"    [Result] {extracted}")
        return extracted
    except Exception as e:
        print(f"    [Skip] {slot.get('title')} error: {str(e)[:50]}")
        return None


def run():
    print(f"[Start] Casino ID: {CASINO_ID}")
    try:
        # Fetch slots from your internal API
        res = requests.post(API_GET_SLOTS, timeout=20)
        slots = res.json() if res.status_code == 200 else []
    except Exception as e:
        print(f"[Error] API Connection failed: {e}")
        return

    if not slots:
        print("[Finish] No slots found.")
        return

    with sync_playwright() as p:
        # Check if we have a valid session, otherwise login
        if not os.path.exists(STATE_FILE):
            if not perform_login(p):
                return

        print("[Session] Resuming with saved authentication state...")
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                try:
                    update_resp = requests.post(API_UPDATE_SLOT, json={"slot_id": slot['id'], **data}, timeout=10)
                    if update_resp.status_code == 200:
                        print(f"    [DB] Updated {slot['title']} successfully.")
                except:
                    print("    [DB Error] Could not reach update API.")

            # Throttle requests to avoid rate limiting
            time.sleep(4)

        browser.close()


if __name__ == "__main__":
    run()