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

# Ensure these keys are in your .env file
USER_LOGIN = os.getenv('CASINO_USER')
USER_PASS = os.getenv('CASINO_PASS')

VOLATILITY_MAP = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "very high": 4
}


def perform_login(p):
    if not USER_LOGIN or not USER_PASS:
        print("[ERROR] STAKE_USER or STAKE_PASS missing in .env file")
        return False

    print(f"[Login] Opening Stake for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        # Use domcontentloaded to avoid networkidle timeouts
        page.goto("https://stake.com/?modal=auth&tab=login", wait_until="domcontentloaded", timeout=60000)

        print("    [Action] Filling credentials...")
        page.wait_for_selector('input[name="username"]', timeout=20000)
        page.locator('input[name="username"]').fill(str(USER_LOGIN))
        page.wait_for_timeout(random.randint(500, 1000))
        page.locator('input[name="password"]').fill(str(USER_PASS))

        print("    [Action] Clicking Login...")
        # Stake's login button is often a submit type inside the form
        page.get_by_role("button", name="Login").click()

        # Wait for the modal to disappear or URL to change
        page.wait_for_url(lambda url: "modal=auth" not in url, timeout=40000)
        print(f"    [Login] Success. Session active.")

        time.sleep(5)  # Let session settle
        context.storage_state(path=STATE_FILE)
        browser.close()
        return True
    except Exception as e:
        print(f"[CRITICAL LOGIN ERROR] {e}")
        page.screenshot(path="stake_login_error.png")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if not url: return None

    print(f"\n[Scraper] Visiting: {slot.get('title')}")
    try:
        # Navigate to the specific slot page
        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # Stake often has an 'i' icon or a 'Game Info' button
        # We try to click the button that contains "Game Info" or "Description"
        print("    Searching for 'Game Info' toggle...")
        time.sleep(4)  # Wait for Svelte to mount

        # Target the button to open the info table
        # Common selectors: get_by_role("button", name="Game Info")
        # or clicking the info icon
        info_toggle = page.get_by_role("button", name="Game info")
        if info_toggle.is_visible():
            info_toggle.click()
            time.sleep(2)
        else:
            # Fallback: look for the text directly if already visible
            if not page.query_selector('tbody.svelte-1ezffp0'):
                print("    [!] Info table not visible, trying alternative click...")
                page.keyboard.press("PageDown")  # Sometimes triggers visibility
                time.sleep(1)

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}

        # Parsing the Svelte table provided in your HTML
        rows = page.query_selector_all('tbody tr')
        for row in rows:
            label_cell = row.query_selector('td:first-child')
            value_cell = row.query_selector('td:last-child')

            if label_cell and value_cell:
                label = label_cell.inner_text().strip().lower()
                value = value_cell.inner_text().strip()

                if "rtp" == label:
                    extracted["theoretical_rtp"] = value.replace('%', '').strip()
                elif "volatility" == label:
                    extracted["volatility_level"] = VOLATILITY_MAP.get(value.lower())
                elif "max win" == label:
                    # '50,000x' -> '50000'
                    extracted["max_win_multiplier"] = value.lower().replace('x', '').replace(',', '').strip()

        print(f"    [Result] {extracted}")
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

        # Start scraping with saved session
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        # Initial landing to verify session
        page.goto("https://stake.com/casino/slots", wait_until="domcontentloaded")
        time.sleep(5)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                try:
                    requests.post(API_UPDATE_SLOT, json={"slot_id": slot['id'], **data}, timeout=10)
                    print(f"    [DB] {slot['title']} updated.")
                except:
                    print("    [DB Error] API Update failed.")

            time.sleep(random.randint(4, 7))

        browser.close()


if __name__ == "__main__":
    run()