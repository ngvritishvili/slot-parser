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

    # FIXED LOGGER: Prevents the AttributeError that crashed your last run
    def handle_request_fail(request):
        # Only log significant failures, ignore minor tracker blocks
        if "sportsbet" in request.url:
            print(f"    [Network Info] Failed to load: {request.url}")

    page.on("requestfailed", handle_request_fail)

    try:
        print(f"    [Navigation] Opening login page...")
        # Use domcontentloaded for speed; we will wait for the specific form element next
        page.goto("https://sportsbet.io/auth/login", wait_until="domcontentloaded", timeout=60000)

        print("    [Navigation] Waiting for login form fields...")
        # We use a robust selector to ensure the React app has rendered the inputs
        page.wait_for_selector('input[name="username"]', timeout=30000)

        print("    [Action] Entering credentials...")
        page.type('input[name="username"]', USER_LOGIN, delay=100)
        page.type('input[name="password"]', USER_PASS, delay=100)

        time.sleep(1)  # Human-like pause

        print("    [Action] Clicking Sign In button...")
        # Targeting the submit button from your HTML snippet
        page.click('button[type="submit"]')

        print("    [Verification] Waiting for authentication to complete...")
        # Wait for the URL to change (away from /auth/login) or for a specific post-login element
        page.wait_for_timeout(10000)

        if "/auth/login" in page.url:
            print(f"    [!] Still on login page. Current URL: {page.url}")
            page.screenshot(path="login_failed_final.png")
            return False

        # Save session
        context.storage_state(path=STATE_FILE)
        print("[Login] SUCCESS! Authentication state saved.")
        browser.close()
        return True

    except Exception as e:
        print(f"[CRITICAL ERROR] {e}")
        try:
            page.screenshot(path="crash_debug.png")
        except:
            pass
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if not url or "sportsbet.io" not in url:
        return None

    print(f"\n[Scraper] Processing: {slot.get('title')}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # Give content time to load (SportBet uses heavy JS)
        page.wait_for_timeout(7000)

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}

        # Scrape stats from the specific flex layout
        blocks = page.query_selector_all('div.flex-col.justify-between.md\\:items-center')
        for block in blocks:
            label_el = block.query_selector('span.text-secondary')
            value_el = block.query_selector('span.truncate')

            if label_el and value_el:
                label = label_el.inner_text().lower()
                val = value_el.inner_text().strip()
                if "rtp" in label:
                    extracted["theoretical_rtp"] = val.replace('%', '')
                elif "volatility" in label:
                    extracted["volatility_level"] = VOLATILITY_MAP.get(val.lower())
                elif "max win" in label:
                    extracted["max_win_multiplier"] = val.upper().replace('X', '').replace(',', '')

        print(f"    [Result] {extracted}")
        return extracted
    except Exception as e:
        print(f"    [Skip] {slot.get('title')} error: {str(e)[:50]}")
        return None


def run():
    print(f"[Start] Casino ID: {CASINO_ID}")
    try:
        res = requests.post(API_GET_SLOTS, timeout=20)
        slots = res.json() if res.status_code == 200 else []
    except:
        print("[Error] DB API unavailable.")
        return

    if not slots:
        print("[Finish] No slots in queue.")
        return

    with sync_playwright() as p:
        # Step 1: Handle Login
        if not os.path.exists(STATE_FILE):
            if not perform_login(p):
                print("[Abort] Could not establish session.")
                return

        # Step 2: Main Scraper Loop
        browser = p.chromium.launch(headless=IS_HEADLESS)
        # Load the saved session to bypass login for every slot
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                try:
                    requests.post(API_UPDATE_SLOT, json={"slot_id": slot['id'], **data}, timeout=10)
                except:
                    print("    [DB Error] Update failed.")

            time.sleep(3)  # Throttle to prevent detection

        browser.close()


if __name__ == "__main__":
    run()