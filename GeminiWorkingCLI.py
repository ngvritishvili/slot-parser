import os
import mysql.connector
import time
import re
import sys
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

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
    text = text.lower()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')


def save_to_db(slots_data):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        for item in slots_data:
            # Sync Provider
            cursor.execute("SELECT id FROM providers WHERE name = %s", (item['provider'],))
            provider_row = cursor.fetchone()
            if not provider_row:
                cursor.execute(
                    "INSERT INTO providers (name, slug, created_at, updated_at) VALUES (%s, %s, NOW(), NOW())",
                    (item['provider'], slugify(item['provider'])))
                provider_id = cursor.lastrowid
            else:
                provider_id = provider_row[0]

            # Sync Slot
            query = "INSERT IGNORE INTO slots (provider_id, title, url, avatar, slug, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, NOW(), NOW())"
            cursor.execute(query, (provider_id, item['title'], item['url'], item['avatar'], slugify(item['title'])))
        conn.commit()
        print(f"   [DB] Synced {len(slots_data)} slots.")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"   [DB ERROR] {e}")


def scrape_page(p, page_number):
    browser = p.chromium.launch(headless=IS_HEADLESS)
    # Using a modern User-Agent to help bypass detection
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        viewport={'width': 1920, 'height': 1080}
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    target_url = f"{CATEGORY_URL}?page={page_number}"
    print(f"\n--- Page {page_number} ---")

    try:
        page.goto(target_url, wait_until="networkidle", timeout=90000)

        # 1. Wait for the actual game links to appear in the DOM
        print("   Waiting for slot elements...")
        page.wait_for_selector('a[href*="/play/video-slots/"]', timeout=30000)

        # 2. Slow scroll to ensure all lazy images/containers load
        page.evaluate("""
            async () => {
                for (let i = 0; i < 3; i++) {
                    window.scrollBy(0, 400);
                    await new Promise(r => setTimeout(r, 500));
                }
            }
        """)

        # 3. New Extraction Logic: Find all game links and move up to their shared container
        # This is more stable than class names which change with every site update
        links = page.query_selector_all('a[href*="/play/video-slots/"]')
        slots = []

        for link in links:
            # Navigate to the parent container that holds both image and provider text
            # Usually 2 or 3 levels up from the <a> tag
            container = link.evaluate_handle("el => el.closest('div.flex-col')")
            if not container: continue

            # Use the link itself for title and url
            url = f"{BASE_URL}{link.get_attribute('href')}"
            img = link.query_selector('img')
            title = img.get_attribute('alt') if img else "Unknown"
            avatar = img.get_attribute('src') if img else ""

            # Find provider (usually a small paragraph/span near the title)
            provider_el = page.evaluate('el => el.closest("div").querySelector("p, span").innerText', container)
            provider = provider_el if provider_el else "Unknown"

            if title and "play" not in title.lower():
                slots.append({"title": title, "provider": provider, "url": url, "avatar": avatar})

        if slots:
            save_to_db(slots)
            return True
        return False

    except Exception as e:
        print(f"   [Web ERROR] Page {page_number}: {e}")
        return False
    finally:
        browser.close()


def run():
    with sync_playwright() as p:
        # Start at 1 or wherever you left off
        for page_num in range(1, MAX_PAGES + 1):
            success = scrape_page(p, page_num)
            if not success:
                print("   No data found, retrying once after 10s...")
                time.sleep(10)
                scrape_page(p, page_num)
            time.sleep(5)


if __name__ == "__main__":
    run()