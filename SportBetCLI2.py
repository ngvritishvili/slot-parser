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
STATE_FILE = "state.json"

USER_LOGIN = os.getenv('CASINO_USER')
USER_PASS = os.getenv('CASINO_PASS')

VOLATILITY_MAP = {
    "casino.volatility_1": 1,
    "casino.volatility_2": 2,
    "casino.volatility_3": 3,
    "casino.volatility_4": 4,
    "casino.volatility_5": 5
}


def human_click(page, selector):
    """Calculates element position and moves mouse naturally to click it."""
    try:
        element = page.wait_for_selector(selector, timeout=10000)
        box = element.bounding_box()
        if box:
            # Target the center of the element with a slight random offset
            x = box['x'] + box['width'] / 2 + random.randint(-5, 5)
            y = box['y'] + box['height'] / 2 + random.randint(-5, 5)

            # Move mouse in small steps to simulate human movement
            page.mouse.move(x, y, steps=random.randint(5, 10))
            page.mouse.click(x, y)
            return True
    except:
        return False
    return False


def perform_login(p):
    print(f"[Login] Initializing fresh login...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(viewport={'width': 1920, 'height': 1080})
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        page.goto("https://sportsbet.io/auth/login", wait_until="networkidle")
        time.sleep(2)

        # Human typing simulation
        page.locator('input[name="username"]').type(str(USER_LOGIN), delay=random.randint(50, 150))
        page.locator('input[name="password"]').type(str(USER_PASS), delay=random.randint(50, 150))

        # Click the Sign In button using human coordinates
        human_click(page, 'button[type="submit"]')

        page.wait_for_url(lambda url: "/auth/login" not in url, timeout=30000)
        time.sleep(10)  # Post-login rest

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

    print(f"\n[Scraper] Navigating to: {slot.get('title')}")
    try:
        # Instead of goto, we can try clicking a link if we were on a list,
        # but for now, we use goto with a slow 'commit'
        page.goto(url, wait_until="commit", timeout=60000)

        # Long wait to let the 'Human Verify' pass or fail
        time.sleep(random.randint(15, 20))

        if "Verify you are human" in page.content():
            print("    [!] Blocked by Cloudflare. Attempting mouse 'wiggle'...")
            # Move mouse randomly to see if it triggers the checkbox automatically
            page.mouse.move(random.randint(100, 500), random.randint(100, 500), steps=20)
            time.sleep(5)
            if "Verify you are human" in page.content():
                return None

        # Human-like scroll
        for _ in range(3):
            page.mouse.wheel(0, random.randint(200, 400))
            time.sleep(1)

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}

        # Targeted extraction
        rtp_el = page.locator('div:has(> p > span[data-translation="casino.rtp"]) >> p.text-bulma').first
        if rtp_el.is_visible():
            extracted["theoretical_rtp"] = rtp_el.inner_text().replace('%', '').strip()

        vol_el = page.locator('span[data-translation*="casino.volatility_"]').first
        if vol_el.is_visible():
            key = vol_el.get_attribute('data-translation')
            extracted["volatility_level"] = VOLATILITY_MAP.get(key)

        print(f"    [Data] {extracted}")
        return extracted
    except Exception as e:
        print(f"    [Error] {str(e)[:50]}")
        return None


def run():
    print(f"[Start] Casino ID: {CASINO_ID}")
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

        # WARM UP
        print("[Session] Warming up on dashboard...")
        page.goto("https://sportsbet.io/", wait_until="domcontentloaded")
        time.sleep(15)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                requests.post(API_UPDATE_SLOT, json={"slot_id": slot['id'], **data})

            # Massive cooldown
            sleep_gap = random.randint(30, 60)
            print(f"[Cooldown] Resting for {sleep_gap}s...")
            time.sleep(sleep_gap)

        browser.close()


if __name__ == "__main__":
    run()