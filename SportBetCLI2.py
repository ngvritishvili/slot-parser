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

    # Using a very specific, modern User Agent
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    # Debugging: Log all console messages from the browser
    page.on("console", lambda msg: print(f"    [Browser Console] {msg.text}"))
    page.on("requestfailed",
            lambda request: print(f"    [Request Failed] {request.url} - {request.failure.error_text}"))

    try:
        print(f"    [Navigation] Attempting to reach login page...")
        # Switch to 'commit' or 'domcontentloaded' to avoid hanging on background analytics
        response = page.goto("https://sportsbet.io/auth/login", wait_until="domcontentloaded", timeout=60000)

        if response:
            print(f"    [Navigation] Response Status: {response.status}")

        print("    [Navigation] Waiting for form container (class: bg-goku)...")
        # Instead of waiting for network, we wait for the specific container in your HTML
        page.wait_for_selector('form.flex-col', timeout=20000)

        print("    [Action] Filling credentials...")
        page.fill('input[name="username"]', USER_LOGIN)
        page.fill('input[name="password"]', USER_PASS)

        # Adding a tiny human-like delay
        time.sleep(1)

        print("    [Action] Clicking Submit...")
        page.click('button[type="submit"]')

        print("    [Verification] Waiting 15s for redirect/session...")
        page.wait_for_timeout(15000)

        if "/auth/login" in page.url:
            print(f"    [!] Failed: Still on login page. URL: {page.url}")
            page.screenshot(path="debug_login_failed.png")
            return False

        context.storage_state(path=STATE_FILE)
        print("[Login] SUCCESS. State saved.")
        browser.close()
        return True

    except Exception as e:
        print(f"[CRITICAL ERROR] {str(e)}")
        page.screenshot(path="debug_crash.png")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if "sportsbet.io" not in url: return None

    print(f"\n[Scraper] Processing: {slot.get('title')}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        # Give React time to render the stats
        page.wait_for_timeout(6000)

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}

        # Scrape logic
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
                    extracted["max_win_multiplier"] = val.upper().replace('X', '')

        print(f"    [Data Found] {extracted}")
        return extracted
    except Exception as e:
        print(f"    [Scrape Error] {str(e)[:100]}")
        return None


def run():
    print(f"[Start] Casino {CASINO_ID}")
    try:
        res = requests.post(API_GET_SLOTS, timeout=20)
        slots = res.json() if res.status_code == 200 else []
    except:
        print("[DB Error] Could not connect to API.")
        return

    if not slots:
        print("[End] No slots found.")
        return

    with sync_playwright() as p:
        if not os.path.exists(STATE_FILE):
            if not perform_login(p): return

        print("[Scraper] Resuming session from state.json...")
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                requests.post(API_UPDATE_SLOT, json={"slot_id": slot['id'], **data})
            time.sleep(2)

        browser.close()


if __name__ == "__main__":
    run()