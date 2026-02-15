import os
import mysql.connector
import time
import re
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# 1. Load the .env file
load_dotenv()

# 2. Access variables
DB_CONFIG = {
    'host': os.getenv('DB_HOST', '127.0.0.1'),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASS')
}

MAX_PAGES = int(os.getenv('MAX_PAGES', 160))
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'

BASE_URL = "https://sportsbet.io"
CATEGORY_URL = "https://sportsbet.io/casino/categories/video-slots"


def slugify(text):
    """Creates a URL-friendly slug for titles and providers."""
    text = text.lower()
    # Replace non-alphanumeric with hyphens
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')


def save_to_db(slots_data):
    """Saves slots directly to MySQL, handling Provider relationships."""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        print(f"   [DB] Connecting to {DB_CONFIG['database']}...")

        for item in slots_data:
            # --- Handle Provider ---
            provider_name = item['provider']
            cursor.execute("SELECT id FROM providers WHERE name = %s", (provider_name,))
            provider_row = cursor.fetchone()

            if not provider_row:
                p_slug = slugify(provider_name)
                cursor.execute(
                    "INSERT INTO providers (name, slug, created_at, updated_at) VALUES (%s, %s, NOW(), NOW())",
                    (provider_name, p_slug)
                )
                provider_id = cursor.lastrowid
            else:
                provider_id = provider_row[0]

            # --- Handle Slot ---
            # Using INSERT IGNORE based on unique slug/url to prevent duplicates
            query = """
                INSERT IGNORE INTO slots (provider_id, title, url, avatar, slug, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            """
            slot_slug = slugify(item['title'])
            values = (provider_id, item['title'], item['url'], item['avatar'], slot_slug)
            cursor.execute(query, values)

        conn.commit()
        print(f"   [DB] Success: {len(slots_data)} items processed.")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"   [DB ERROR] Connection or Query failed: {e}")


def extract_slots(page):
    """Scrapes the slot cards from the current page."""
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
                data.append({
                    "title": name,
                    "provider": provider,
                    "url": url,
                    "avatar": avatar
                })
        except:
            continue
    return data


def scrape_page(p, page_number):
    """Logic for handling a single browser session for one page."""
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(viewport={'width': 1920, 'height': 1080})
    page = context.new_page()

    # Apply Stealth
    stealth = Stealth()
    stealth.apply_stealth_sync(page)

    target_url = f"{CATEGORY_URL}?page={page_number}"
    print(f"\n--- Processing Page {page_number} ---")
    print(f"URL: {target_url}")

    try:
        page.goto(target_url, wait_until="domcontentloaded", timeout=60000)

        # Wait for content to load
        page.wait_for_timeout(10000)

        # Scroll to trigger lazy loading
        page.evaluate("window.scrollTo(0, 1000)")
        page.wait_for_timeout(2000)

        slots = extract_slots(page)

        if slots:
            print(f"Found {len(slots)} slots. Syncing to Database...")
            save_to_db(slots)
            return True
        else:
            print(f"No slots detected on Page {page_number}.")
            return False

    except Exception as e:
        print(f"Error on Page {page_number}: {e}")
        return False
    finally:
        browser.close()


def run():
    with sync_playwright() as p:
        # Start at 73 (based on your previous log)
        current_page = 73
        while current_page <= MAX_PAGES:
            success = scrape_page(p, current_page)
            # We don't necessarily break on fail here to allow it to try next page
            current_page += 1
            time.sleep(3)  # Polite delay


if __name__ == "__main__":
    run()