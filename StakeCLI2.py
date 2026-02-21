import os
import time
import random
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIG ---
CASINO_ID = 2  # Assuming ID 2 for Stake
API_BASE = os.getenv('API_ENDPOINT_BASE', 'http://checkthisone.online')
API_GET_SLOTS = f"{API_BASE}/api/casinos/{CASINO_ID}/slots"
API_UPDATE_SLOT = f"{API_BASE}/api/slots/update-details"
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
STATE_FILE = "stake_state.json"

USER_LOGIN = os.getenv('STAKE_USER')
USER_PASS = os.getenv('STAKE_PASS')

# Mapping for the text values found in the svelte table
VOLATILITY_MAP = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "very high": 4
}


def perform_login(p):
    print(f"[Login] Opening Stake for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(viewport={'width': 1920, 'height': 1080})
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        page.goto("https://stake.com/?modal=auth&tab=login", wait_until="networkidle")

        # Human-like typing
        page.locator('input[name="username"]').type(USER_LOGIN, delay=random.randint(50, 150))
        page.locator('input[name="password"]').type(USER_PASS, delay=random.randint(50, 150))

        # Click login button (using the data-test attribute if available, or text)
        page.get_by_role("button", name="Login").click()

        print("    Waiting for dashboard...")
        page.wait_for_url(lambda url: "modal=auth" not in url, timeout=30000)
        time.sleep(5)

        context.storage_state(path=STATE_FILE)
        browser.close()
        return True
    except Exception as e:
        print(f"[CRITICAL LOGIN ERROR] {e}")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if not url: return None

    print(f"\n[Scraper] Slot: {slot.get('title')}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(random.randint(3, 5))

        # 1. Click the 'Description' or 'Game Info' button to reveal the table
        # We look for common labels on Stake
        info_button = page.get_by_text("Description", exact=True)
        if info_button.is_visible():
            info_button.click()
            time.sleep(1)

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}

        # 2. Parse the table rows
        rows = page.query_selector_all('tbody tr')
        for row in rows:
            cells = row.query_selector_all('td')
            if len(cells) >= 2:
                label = cells[0].inner_text().strip().lower()
                value = cells[1].inner_text().strip()

                if "rtp" in label:
                    extracted["theoretical_rtp"] = value.replace('%', '').strip()
                elif "volatility" in label:
                    extracted["volatility_level"] = VOLATILITY_MAP.get(value.lower())
                elif "max win" in label:
                    extracted["max_win_multiplier"] = value.lower().replace('x', '').replace(',', '').strip()

        print(f"    [Data] {extracted}")
        return extracted
    except Exception as e:
        print(f"    [Error] {str(e)[:50]}")
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

        # Warm up on the main slots page
        page.goto("https://stake.com/casino/slots")
        time.sleep(5)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                requests.post(API_UPDATE_SLOT, json={"slot_id": slot['id'], **data})

            # Stake is faster than Sportsbet, but keep a safety gap
            time.sleep(random.randint(5, 10))

        browser.close()


if __name__ == "__main__":
    run()