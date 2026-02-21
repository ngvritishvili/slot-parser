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
        print("[ERROR] CASINO_USER or CASINO_PASS missing in .env file")
        return False

    print(f"[Login] Opening Stake for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(
        viewport={'width': 1280, 'height': 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        print("    [Navigation] Loading login page...")
        # Start with a direct hit to the login modal
        page.goto("https://stake.com/?tab=login&modal=auth", wait_until="commit", timeout=60000)

        # Wait for the form to actually appear
        page.wait_for_selector('[data-testid="login-name"]', timeout=30000)

        print("    [Action] Filling credentials...")
        page.locator('[data-testid="login-name"]').fill(str(USER_LOGIN))
        page.wait_for_timeout(random.randint(500, 1000))
        page.locator('[data-testid="login-password"]').fill(str(USER_PASS))

        print("    [Action] Clicking Sign In...")
        page.locator('[data-testid="button-login"]').click()

        # --- IMPROVED VERIFICATION ---
        print("    [Verification] Monitoring login progress...")

        # We wait for either the modal to close OR a 2FA field to appear
        for _ in range(20):  # 20 seconds total check
            current_url = page.url
            content = page.content()

            if "modal=auth" not in current_url:
                print("    [Login] Success! Redirected to dashboard.")
                break

            if "two factor" in content.lower() or "2fa" in content.lower():
                print("    [!] STOP: 2FA Required. Manual intervention needed.")
                page.screenshot(path="login_2fa_required.png")
                return False

            if "verify you are human" in content.lower():
                print("    [!] STOP: Cloudflare Turnstile detected.")
                page.screenshot(path="login_cloudflare_detected.png")
                # Optional: try a tiny mouse move to trigger it
                page.mouse.move(random.randint(100, 300), random.randint(100, 300))

            time.sleep(1)

        # Final check
        if "modal=auth" in page.url:
            print("    [Error] Login timed out or stuck on modal.")
            page.screenshot(path="debug_login_stuck.png")
            return False

        time.sleep(5)
        context.storage_state(path=STATE_FILE)
        browser.close()
        return True

    except Exception as e:
        print(f"[CRITICAL LOGIN ERROR] {e}")
        page.screenshot(path="debug_stake_crash.png")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if not url: return None

    print(f"\n[Scraper] Visiting: {slot.get('title')}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(6)

        # Scroll down to ensure Svelte components trigger
        page.mouse.wheel(0, 500)
        time.sleep(2)

        # Look for the "Game info" button
        info_btn = page.get_by_role("button", name="Game info")
        if info_btn.is_visible():
            info_btn.click()
            time.sleep(2)

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}

        # Parsing logic for the <tbody> rows
        rows = page.query_selector_all('tbody tr')
        for row in rows:
            cells = row.query_selector_all('td')
            if len(cells) >= 2:
                label = cells[0].inner_text().strip().lower()
                value = cells[1].inner_text().strip()

                if "rtp" == label:
                    # Clean "96.50%" -> "96.50"
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

    with sync_playwright() as p:
        if not os.path.exists(STATE_FILE):
            if not perform_login(p): return

        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        # Warmup
        page.goto("https://stake.com/casino/slots", wait_until="domcontentloaded")
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