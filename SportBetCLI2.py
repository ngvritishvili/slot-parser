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
    print(f"[Login] Directing to login page for {USER_LOGIN}...")
    # Launch with a realistic user agent
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        # GO DIRECTLY TO LOGIN PAGE
        print("    Navigating directly to: https://sportsbet.io/auth/login")
        page.goto("https://sportsbet.io/auth/login", wait_until="networkidle", timeout=60000)

        # Wait for the form fields to be visible
        # We try both name attributes and placeholders as fallbacks
        print("    Waiting for input fields...")
        page.wait_for_selector('input[name="username"], input[placeholder*="Username"]', timeout=30000)

        # Fill credentials
        print("    Filling form...")
        # Locating specifically by name or placeholder to avoid confusion
        page.locator('input[name="username"], input[placeholder*="Username"]').fill(USER_LOGIN)
        page.locator('input[name="password"], input[placeholder*="Password"]').fill(USER_PASS)

        # Click the Sign In button
        # Using the brand button class you provided earlier
        print("    Clicking Sign In...")
        submit_btn = page.locator('button[type="submit"].button-brand, button:has-text("Sign in")').first
        submit_btn.click()

        # Give it time to process and redirect
        print("    Waiting for session verification...")
        page.wait_for_timeout(10000)

        # Verify if we are still on the login page
        if "/auth/login" in page.url:
            print(f"    [!] Still on login page ({page.url}). Check login_error.png")
            page.screenshot(path="login_error.png")
            return False

        # Save the authenticated state (cookies/localstorage)
        context.storage_state(path=STATE_FILE)
        print("[Login] Success! Session saved to state.json.")
        browser.close()
        return True

    except Exception as e:
        print(f"[Login Error] {e}")
        page.screenshot(path="login_crash_debug.png")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if "sportsbet.io" not in url:
        return None

    print(f"\n[Scraping] {slot.get('title')}")
    try:
        # Navigate to the specific slot page
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)  # Wait for details to load

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}

        # Select the stat blocks (RTP, Volatility, etc.)
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
        print(f"    Error on slot {slot.get('title')}: {str(e)[:50]}")
        return None


def run():
    print(f"[DB] Fetching slots for casino_id: {CASINO_ID}...")
    try:
        response = requests.post(API_GET_SLOTS, timeout=30)
        slots = response.json() if response.status_code == 200 else []
    except Exception as e:
        print(f"Failed to fetch slots from DB: {e}")
        return

    if not slots:
        print("No slots found to process.")
        return

    with sync_playwright() as p:
        # Step 1: Login if state doesn't exist
        if not os.path.exists(STATE_FILE):
            if not perform_login(p):
                return

        # Step 2: Run the scraping with the saved session
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                # Send data back to your API
                try:
                    update_resp = requests.post(API_UPDATE_SLOT, json={"slot_id": slot['id'], **data})
                    if update_resp.status_code == 200:
                        print(f"    [DB] Updated {slot['title']} successfully.")
                except Exception as e:
                    print(f"    [DB Error] Failed to update: {e}")

            # Anti-detection delay
            time.sleep(3)

        browser.close()


if __name__ == "__main__":
    run()