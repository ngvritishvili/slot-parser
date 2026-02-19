import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import stealth_sync  # ✅ correct import for playwright-stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "https://roobet.com"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://roobet.com/casino/category/slots?sort=pop_desc"
BASE_URL = "https://roobet.com"

GAME_LINK_SELECTOR = 'a[href^="/casino/game/"]'


def sync_to_laravel(slots_data):
    if not slots_data:
        return False
    print(f"   [API] Syncing {len(slots_data)} new slots...")
    try:
        response = requests.post(API_ENDPOINT, json=slots_data, timeout=120)
        if response.status_code == 200:
            details = response.json().get('details', {})
            print(f"   [SUCCESS] New: {details.get('new_slots_added')}, Skipped: {details.get('existing_slots_skipped')}")
            return True
        else:
            print(f"   [API ERROR] Status {response.status_code}: {response.text}")
    except Exception as e:
        print(f"   [API ERROR] {e}")
    return False


def looks_like_cloudflare(page) -> bool:
    # Very simple “are we stuck on a challenge page?” signals
    title = (page.title() or "").lower()
    url = (page.url or "").lower()
    content = (page.content() or "").lower()

    if "just a moment" in title:
        return True
    if "cdn-cgi" in url:
        return True
    if "checking your browser" in content:
        return True
    return False


def safe_goto(page, url, tries=3):
    last_err = None
    for attempt in range(1, tries + 1):
        try:
            print(f"   [NAV] goto attempt {attempt}/{tries} ...")
            # ✅ use domcontentloaded instead of networkidle
            page.goto(url, wait_until="domcontentloaded", timeout=120_000)

            # give JS a moment to hydrate
            page.wait_for_timeout(2500)

            # if site is chatty, don't block on networkidle; just wait for what we need
            page.wait_for_selector(GAME_LINK_SELECTOR, timeout=60_000)

            if looks_like_cloudflare(page):
                raise RuntimeError("Cloudflare challenge page detected")

            return True

        except (PlaywrightTimeoutError, RuntimeError) as e:
            last_err = e
            print(f"   [NAV WARN] {e}")
            try:
                # sometimes a hard reload helps
                page.reload(wait_until="domcontentloaded", timeout=120_000)
                page.wait_for_timeout(2000)
            except Exception:
                pass

            time.sleep(2)

    raise last_err


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=IS_HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()
        stealth_sync(page)  # ✅ apply stealth correctly

        print(f">>> Opening {TARGET_URL} for {CASINO_NAME}")
        safe_goto(page, TARGET_URL)

        synced_slugs = set()

        while True:
            page.wait_for_selector(GAME_LINK_SELECTOR, timeout=60_000)

            items = page.query_selector_all(GAME_LINK_SELECTOR)
            new_batch = []

            for item in items:
                try:
                    url_path = item.get_attribute('href') or ""
                    slug = url_path.split('/')[-1] if url_path else ""

                    if not slug or slug in synced_slugs:
                        continue

                    title = item.get_attribute('aria-label') or "Unknown"

                    provider = "Unknown"
                    parts = slug.split('-')
                    if parts:
                        provider = parts[0].title()

                    img_el = item.query_selector('img')
                    avatar = ""
                    if img_el:
                        raw_src = img_el.get_attribute('src') or ""
                        if raw_src.startswith("cdn-cgi"):
                            avatar = f"{BASE_URL}/{raw_src}"
                        elif raw_src.startswith("/"):
                            avatar = f"{BASE_URL}{raw_src}"
                        else:
                            avatar = raw_src

                    new_batch.append({
                        "title": title,
                        "provider": provider,
                        "url": f"{BASE_URL}{url_path}",
                        "avatar": avatar,
                        "casino_name": CASINO_NAME
                    })
                    synced_slugs.add(slug)
                except Exception:
                    continue

            if new_batch:
                sync_to_laravel(new_batch)

            load_more = page.locator('button:has-text("Load More Games")')
            if load_more.count() > 0 and load_more.first.is_visible():
                print(f"--- Clicking 'Load More' (Total seen: {len(synced_slugs)}) ---")
                load_more.first.scroll_into_view_if_needed()
                load_more.first.click()

                # wait for new content to appear (don’t trust sleep only)
                page.wait_for_timeout(1500)
                # small “settle” time
                time.sleep(2)
            else:
                print(">>> No more 'Load More' button found.")
                break

            if len(synced_slugs) > 5000:
                break

        browser.close()
        print(f"\n>>> Scrape Complete for Roobet. Total synced: {len(synced_slugs)}")


if __name__ == "__main__":
    run()
