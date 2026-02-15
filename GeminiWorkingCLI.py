import os
import mysql.connector
import time
import re
from dotenv import load_dotenv  # New Import
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# 1. Load the .env file
load_dotenv()

# 2. Access variables using os.getenv()
DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASS')
}

MAX_PAGES = int(os.getenv('MAX_PAGES', 160))
# Convert string 'True'/'False' from .env to actual Boolean
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'

BASE_URL = "https://sportsbet.io"
CATEGORY_URL = "https://sportsbet.io/casino/categories/video-slots"


def slugify(text):
    text = text.lower()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')


def save_to_db(slots_data):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        for item in slots_data:
            # Sync Provider
            provider_name = item['provider']
            cursor.execute("SELECT id FROM providers WHERE name = %s", (provider_name,))
            provider_row = cursor.fetchone()

            if not provider_row:
                cursor.execute(
                    "INSERT INTO providers (name, slug, created_at, updated_at) VALUES (%s, %s, NOW(), NOW())",
                    (provider_name, slugify(provider_name))
                )
                provider_id = cursor.lastrowid
            else:
                provider_id = provider_row[0]

            # Sync Slot
            query = """
                INSERT IGNORE INTO slots (provider_id, title, url, avatar, slug, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            """
            slot_slug = slugify(item['title'])
            values = (provider_id, item['title'], item['url'], item['avatar'], slot_slug)
            cursor.execute(query, values)

        conn.commit()
        print(f"   [DB] Batch of {len(slots_data)} slots saved.")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"   [DB ERROR] {e}")


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
    # Use IS_HEADLESS from .env
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36..."
    )
    page = context.new_page()

    stealth = Stealth()
    stealth.apply_stealth_sync(page)

    target_url = f"{CATEGORY_URL}?page={page_number}"
    print(f"\n--- Processing Page {page_number} ---")

    try:
        page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(10000)
        page.evaluate("window.scrollTo(0, 1000)")

        slots = extract_slots(page)
        if slots:
            save_to_db(slots)
            return True
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False
    finally:
        browser.close()


def run():
    with sync_playwright() as p:
        current_page = 1  # Or wherever you want to start
        while current_page <= MAX_PAGES:
            success = scrape_page(p, current_page)
            if not success: break
            current_page += 1
            time.sleep(2)


if __name__ == "__main__":
    run()