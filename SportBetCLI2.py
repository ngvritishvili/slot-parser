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
    print(f"[Login] Starting process for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    # Use a high-quality User Agent to avoid bot detection
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        print("    Navigating to home page...")
        page.goto("https://sportsbet.io/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)  # Wait for animations/modals

        # 1. Check if login fields are ALREADY visible (sometimes happens on direct redirect)
        user_input = page.query_selector('input[placeholder*="Username"]')

        if not user_input:
            print("    Login fields not found. Looking for 'Sign in' button...")
            # Try multiple selector types for the Sign In button
            signin_button = page.locator('button:has-text("Sign in"), .button-brand, button:text("Log in")').first

            if signin_button.is_visible():
                signin_button.click()
                print("    Clicked Sign In button.")
            else:
                print("    [!] 'Sign in' button not visible. Saving debug_pre_fail.png")
                page.screenshot(path="debug_pre_fail.png")
                # If we get here, it's likely a Cloudflare challenge or a regional block.
                return False

        # 2. Fill the form using the HTML structure you provided
        print("    Filling form...")
        page.wait_for_selector('input[placeholder*="Username"]', timeout=10000)
        page.fill('input[placeholder*="Username"]', USER_LOGIN)
        page.fill('input[placeholder="Password"]', USER_PASS)

        # 3. Submit using the specific class from your snippet
        print("    Submitting...")
        page.click('button[type="submit"].button-brand')

        # 4. Wait for session
        page.wait_for_timeout(10000)

        if page.query_selector('button[type="submit"]'):
            print("    [!] Still on login page. Check login_failed.png")
            page.screenshot(path="login_failed.png")
            return False

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

        # Select blocks based on layout
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
        print(f"    Error: {str(e)[:50]}")
        return None


def run():
    print("[DB] Fetching slots...")
    try:
        # Fetching slots from your API
        response = requests.post(f"{API_BASE}/api/casinos/{CASINO_ID}/slots", timeout=30)
        slots = response.json() if response.status_code == 200 else []
    except:
        print("Failed to fetch slots.")
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
                requests.post(f"{API_BASE}/api/slots/update-details", json={"slot_id": slot['id'], **data})
            time.sleep(2)
        browser.close()


if __name__ == "__main__":
    run()