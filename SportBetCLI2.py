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
    print(f"[Login] Using direct form element mapping for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        # Step 1: Go to login page
        print("    Navigating to https://sportsbet.io/auth/login")
        page.goto("https://sportsbet.io/auth/login", wait_until="networkidle", timeout=60000)

        # Step 2: Fill inputs using the specific names from your HTML
        print("    Waiting for form elements...")
        # Target: name="username" and name="password"
        page.wait_for_selector('input[name="username"]', timeout=20000)

        print("    Filling Username and Password...")
        page.fill('input[name="username"]', USER_LOGIN)
        page.fill('input[name="password"]', USER_PASS)

        # Step 3: Click the Submit button
        # Target: type="submit" with class "bg-piccolo" as seen in your code
        print("    Clicking 'Sign In' button...")
        page.click('button[type="submit"]')

        # Step 4: Verification
        print("    Waiting for redirect...")
        page.wait_for_timeout(10000)

        # If the URL still contains 'auth/login', it failed
        if "/auth/login" in page.url:
            print(f"    [!] Login failed. Current URL: {page.url}")
            page.screenshot(path="login_failed_check.png")
            return False

        # Save session
        context.storage_state(path=STATE_FILE)
        print("[Login] Success! State saved.")
        browser.close()
        return True

    except Exception as e:
        print(f"[Login Error] {e}")
        page.screenshot(path="login_crash.png")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if "sportsbet.io" not in url:
        return None

    print(f"\n[Scraping] {slot.get('title')}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}

        # Select the stat blocks (flex layout)
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

        print(f"    Data: {extracted}")
        return extracted
    except Exception as e:
        print(f"    Page Error: {str(e)[:50]}")
        return None


def run():
    print(f"[DB] Fetching slots for casino {CASINO_ID}...")
    try:
        response = requests.post(API_GET_SLOTS, timeout=30)
        slots = response.json() if response.status_code == 200 else []
    except Exception as e:
        print(f"API Error: {e}")
        return

    if not slots:
        print("No slots to process.")
        return

    with sync_playwright() as p:
        if not os.path.exists(STATE_FILE):
            if not perform_login(p):
                return

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