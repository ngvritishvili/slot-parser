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

# Mapping updated to match the translation keys in your HTML
VOLATILITY_MAP = {
    "casino.volatility_1": 1,  # Low
    "casino.volatility_2": 2,  # Low-Medium
    "casino.volatility_3": 3,  # Medium
    "casino.volatility_4": 4,  # Medium-High
    "casino.volatility_5": 5  # High
}


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
        page.wait_for_selector('input[name="username"]', timeout=30000)

        print("    [Action] Entering credentials...")
        page.locator('input[name="username"]').fill(str(USER_LOGIN))
        page.locator('input[name="password"]').fill(str(USER_PASS))
        page.locator('button[type="submit"]').click()

        print("    [Verification] Waiting for redirect...")
        page.wait_for_url(lambda url: "/auth/login" not in url, timeout=25000)
        page.wait_for_timeout(5000)

        context.storage_state(path=STATE_FILE)
        print(f"[Login] SUCCESS! Session saved.")
        browser.close()
        return True
    except Exception as e:
        print(f"[CRITICAL LOGIN ERROR] {e}")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if not url or "sportsbet.io" not in url: return None

    print(f"\n[Scraper] Visiting Slot: {slot.get('title')}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # Increased wait because "Game Stats" often load via a separate API call
        print("    Waiting for Game Stats grid...")
        page.wait_for_selector('span[data-translation="casino.game_stats"]', timeout=15000)
        page.wait_for_timeout(2000)  # Small buffer for numbers to tick up

        extracted = {
            "theoretical_rtp": None,
            "volatility_level": None,
            "max_win_multiplier": None
        }

        # 1. Get RTP (the one next to 'casino.rtp')
        rtp_label = page.query_selector('span[data-translation="casino.rtp"]')
        if rtp_label:
            # The value is usually the next paragraph/span in the sibling container
            # Based on your HTML: <p>RTP</p> <p>96.5%</p>
            parent = rtp_label.evaluate_handle("el => el.closest('div')")
            val_el = parent.query_selector('p.text-bulma, span.text-bulma')
            if val_el:
                extracted["theoretical_rtp"] = val_el.inner_text().replace('%', '').strip()

        # 2. Get Volatility
        vol_label = page.query_selector('span[data-translation="casino.volatility"]')
        if vol_label:
            parent = vol_label.evaluate_handle("el => el.closest('div')")
            # Volatility value is inside another span with a translation key
            val_span = parent.query_selector('span[data-translation*="casino.volatility_"]')
            if val_span:
                key = val_span.get_attribute('data-translation')
                extracted["volatility_level"] = VOLATILITY_MAP.get(key)

        # 3. Get Max Win (Sportbet often shows this in 'Min - Max bet' or 'Max win' labels)
        # Note: If Max Win is not in the Game Stats grid, we might need a backup selector.
        max_win_label = page.query_selector('span[data-translation="casino.max_win"]')
        if max_win_label:
            parent = max_win_label.evaluate_handle("el => el.closest('div')")
            val_el = parent.query_selector('p.text-bulma, span.text-bulma')
            if val_el:
                extracted["max_win_multiplier"] = val_el.inner_text().lower().replace('x', '').replace(',', '').strip()

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
    except Exception as e:
        print(f"[Error] API Connection failed: {e}")
        return

    if not slots:
        print("[Finish] No slots found.")
        return

    with sync_playwright() as p:
        if not os.path.exists(STATE_FILE):
            if not perform_login(p): return

        print("[Session] Resuming with saved authentication state...")
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                try:
                    requests.post(API_UPDATE_SLOT, json={"slot_id": slot['id'], **data}, timeout=10)
                    print(f"    [DB] Updated {slot['title']}")
                except:
                    print("    [DB Error] Update failed.")

            time.sleep(4)

        browser.close()


if __name__ == "__main__":
    run()