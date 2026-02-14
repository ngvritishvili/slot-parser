import requests
import time
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

# Configuration
BASE_URL = "https://sportsbet.io"
CATEGORY_URL = "https://sportsbet.io/casino/categories/video-slots"
API_ENDPOINT = "http://127.0.0.1:8000/api/slots/sync"
MAX_PAGES = 160


def extract_slots(page):
    """Extracts slot data from the current page state."""
    slot_divs = page.query_selector_all('div.relative.flex.cursor-pointer.flex-col')
    data = []
    for div in slot_divs:
        try:
            link_el = div.query_selector('a[href*="/play/"]')
            if not link_el: continue

            img_el = link_el.query_selector('img')
            name = img_el.get_attribute('alt') if img_el else "N/A"
            avatar = img_el.get_attribute('src') if img_el else "N/A"

            provider_el = div.query_selector('p.text-moon-12')
            provider = provider_el.inner_text().strip() if provider_el else "Unknown"
            url = f"{BASE_URL}{link_el.get_attribute('href')}"

            # Filter out UI icons like 'play game'
            if name != "N/A" and "play game" not in name.lower():
                data.append({
                    "title": name,
                    "provider": provider,
                    "url": url,
                    "avatar": avatar
                })
        except Exception:
            continue
    return data


def scrape_page(p, page_number):
    """Opens a fresh browser context for a specific page number."""
    # args=["--window-position=1920,0"] opens it on the second monitor
    browser = p.chromium.launch(
        headless=False,
        args=["--window-position=1920,0"]
    )

    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = context.new_page()

    # Apply stealth to hide bot fingerprints
    stealth_sync(page)

    target_url = f"{CATEGORY_URL}?page={page_number}"
    print(f"\n--- Processing Page {page_number} ---")
    print(f"URL: {target_url}")

    try:
        page.goto(target_url, wait_until="domcontentloaded")

        # Buffer for manual Turnstile solve or slow JS hydration
        print("Waiting 15s for stability/manual solve...")
        page.wait_for_timeout(15000)

        # Scroll to ensure images and lazy elements are rendered
        page.evaluate("window.scrollTo(0, 1200)")
        page.wait_for_timeout(2000)

        slots = extract_slots(page)

        if slots:
            print(f"Found {len(slots)} slots. Syncing to Laravel...")
            try:
                response = requests.post(API_ENDPOINT, json=slots, timeout=30)
                if response.status_code == 200:
                    print(f"Laravel Success: {response.json().get('details')}")
                else:
                    print(f"Laravel Error: {response.status_code}")
            except Exception as e:
                print(f"Connection to Laravel failed: {e}")
            return True
        else:
            print(f"No slots detected on Page {page_number}. Finishing.")
            return False

    except Exception as e:
        print(f"Critical error on Page {page_number}: {e}")
        return False
    finally:
        browser.close()


def run():
    with sync_playwright() as p:
        current_page = 73
        while current_page <= MAX_PAGES:
            success = scrape_page(p, current_page)
            if not success:
                break

            print(f"Page {current_page} complete. Cleaning session...")
            current_page += 1
            # Polite delay between fresh browser launches
            time.sleep(3)


if __name__ == "__main__":
    run()