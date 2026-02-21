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

USER_LOGIN = os.getenv('CASINO_USER')
USER_PASS = os.getenv('CASINO_PASS')

VOLATILITY_MAP = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "very high": 4,
    "extreme": 5
}


def perform_login(p):
    if not USER_LOGIN or not USER_PASS:
        print("[ERROR] CASINO_USER or CASINO_PASS missing in .env")
        return False

    print(f"[Login] Initializing browser for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(
        viewport={'width': 1280, 'height': 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        print("    [Navigation] Loading Stake Base...")
        # Step 1: Go to the main site first
        page.goto("https://stake.com/", wait_until="commit", timeout=60000)

        # Step 2: Manually trigger the login modal via URL to ensure it pops up
        print("    [Navigation] Triggering Login Modal...")
        page.goto("https://stake.com/?modal=auth&tab=login", wait_until="domcontentloaded", timeout=60000)

        # Step 3: Wait for the login field with a longer timeout
        print("    [Action] Waiting for login fields...")
        try:
            # We use a combined selector to be safe
            page.wait_for_selector('input[data-testid="login-name"], input[name="emailOrName"]', timeout=45000)
        except Exception:
            print("    [!] Form not found. Saving debug screenshot...")
            page.screenshot(path="debug_no_form.png")
            raise Exception("Login form timeout")

        print("    [Action] Filling credentials...")
        # Use a more flexible selector for the input
        login_input = page.locator('input[data-testid="login-name"], input[name="emailOrName"]').first
        pass_input = page.locator('input[data-testid="login-password"], input[name="password"]').first

        login_input.fill(str(USER_LOGIN))
        page.wait_for_timeout(random.randint(500, 1000))
        pass_input.fill(str(USER_PASS))

        print("    [Action] Clicking Sign In...")
        page.locator('button[data-testid="button-login"], button[type="submit"]').first.click()

        # Verification loop
        print("    [Verification] Waiting for session...")
        success = False
        for _ in range(30):
            if "modal=auth" not in page.url:
                success = True
                break
            # Check for common errors visible on screen
            content = page.content().lower()
            if "invalid" in content and "credentials" in content:
                print("    [Error] Invalid credentials found on page.")
                break
            time.sleep(1)

        if success:
            print("    [Login] Success! Saving state.")
            time.sleep(5)
            context.storage_state(path=STATE_FILE)
            browser.close()
            return True
        else:
            page.screenshot(path="debug_login_failed.png")
            print("    [Error] Could not verify login success.")
            browser.close()
            return False

    except Exception as e:
        print(f"[CRITICAL LOGIN ERROR] {e}")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if not url: return None

    print(f"\n[Scraper] Visiting: {slot.get('title')}")
    try:
        # Stake pages are heavy; wait for commit then manual delay
        page.goto(url, wait_until="commit", timeout=60000)
        time.sleep(8)

        # Scroll to trigger lazy-loaded Svelte elements
        page.mouse.wheel(0, 500)
        time.sleep(2)

        # Attempt to open the info panel
        # Trying different variations of the button name
        for btn_text in ["Game info", "Description", "Game Information"]:
            info_btn = page.get_by_role("button", name=btn_text, exact=False)
            if info_btn.is_visible():
                info_btn.click()
                time.sleep(2)
                break

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}

        # Parsing the specific <tbody> rows from your provided HTML
        rows = page.query_selector_all('tbody tr')
        for row in rows:
            cells = row.query_selector_all('td')
            if len(cells) >= 2:
                label = cells[0].inner_text().strip().lower()
                value = cells[1].inner_text().strip()

                if "rtp" == label:
                    extracted["theoretical_rtp"] = value.replace('%', '').strip()
                elif "volatility" == label:
                    extracted["volatility_level"] = VOLATILITY_MAP.get(value.lower())
                elif "max win" == label:
                    extracted["max_win_multiplier"] = value.lower().replace('x', '').replace(',', '').strip()

        print(f"    [Data] {extracted}")
        return extracted
    except Exception as e:
        print(f"    [Skip] {slot.get('title')} error: {str(e)[:50]}")
        return None


def run():
    print(f"[Start] Stake Scanner (Casino ID: {CASINO_ID})")
    try:
        res = requests.post(API_GET_SLOTS, timeout=20)
        slots = res.json() if res.status_code == 200 else []
    except:
        return

    if not slots:
        print("[Finish] No slots to process.")
        return

    with sync_playwright() as p:
        if not os.path.exists(STATE_FILE):
            if not perform_login(p): return

        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        # Warmup on slots page
        page.goto("https://stake.com/casino/slots", wait_until="commit")
        time.sleep(10)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                try:
                    requests.post(API_UPDATE_SLOT, json={"slot_id": slot['id'], **data}, timeout=10)
                    print(f"    [DB] {slot['title']} updated.")
                except:
                    pass

            time.sleep(random.randint(10, 20))

        browser.close()


if __name__ == "__main__":
    run()