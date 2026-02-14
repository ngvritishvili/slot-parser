import requests
import time
from playwright.sync_api import sync_playwright

BASE_URL = "https://sportsbet.io"
CATEGORY_URL = "https://sportsbet.io/casino/categories/video-slots"
API_ENDPOINT = "http://127.0.0.1:8000/api/slots/sync"


def extract_slots(page):
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

            if name != "N/A" and "play game" not in name.lower():
                data.append({"title": name, "provider": provider, "url": url, "avatar": avatar})
        except:
            continue
    return data


def scrape_page(p, page_number):
    """Opens a fresh browser instance for a specific page number"""
    browser = p.chromium.launch(headless=False)
    # Using a fresh context for every page
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = context.new_page()

    target_url = f"{CATEGORY_URL}?page={page_number}"
    print(f"Opening fresh session for: {target_url}")

    try:
        page.goto(target_url, wait_until="domcontentloaded")

        # Give you time to solve Cloudflare if it appears
        print(f"Waiting 15s for Page {page_number} to stabilize...")
        page.wait_for_timeout(15000)

        # Scroll to ensure images load
        page.evaluate("window.scrollTo(0, 1000)")
        page.wait_for_timeout(2000)

        slots = extract_slots(page)

        if slots:
            print(f"Found {len(slots)} slots on Page {page_number}. Syncing...")
            requests.post(API_ENDPOINT, json=slots)
            return True  # Success
        else:
            print(f"No slots found on Page {page_number}.")
            return False  # End of list

    except Exception as e:
        print(f"Error on Page {page_number}: {e}")
        return False
    finally:
        browser.close()


def run():
    with sync_playwright() as p:
        current_page = 29
        max_pages = 160

        while current_page <= max_pages:
            success = scrape_page(p, current_page)

            if not success:
                print("Stopping: Either end of list or blocked.")
                break

            print(f"Finished Page {current_page}. Closing session...")
            current_page += 1
            time.sleep(5)  # Brief pause before opening the next browser


if __name__ == "__main__":
    run()