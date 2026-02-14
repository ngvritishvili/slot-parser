import mysql.connector
import time
import re
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# Database Configuration
DB_CONFIG = {
    'user': 'me',
    'password': 'Cracket1!',
    'host': '127.0.0.1',
    'database': 'slot'
}

def get_volatility_level(text):
    if not text: return 1
    text = text.lower()
    if 'very high' in text: return 4
    if 'high' in text: return 3
    if 'medium' in text: return 2
    return 1


def update_slot_in_db(slot_id, data):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        query = """
            UPDATE slots 
            SET `theoretical_rtp` = %s, 
                `volatility_level` = %s,
                `max_win_multiplier` = %s,
                `reels` = %s,
                `rows` = %s
            WHERE `id` = %s
        """
        values = (data.get('rtp'), data.get('volatility'), data.get('max_win'),
                  data.get('reels'), data.get('rows'), slot_id)
        cursor.execute(query, values)
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"   [DB ERROR] ID {slot_id}: {e}")
        return False


def scrape_slot_details(p, slot_id, url):
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(viewport={'width': 1920, 'height': 1080})
    page = context.new_page()

    stealth = Stealth()
    stealth.apply_stealth_sync(page)

    print(f"\n--- Processing ID {slot_id} ---")
    print(f"Target: {url}")

    extracted = {'rtp': 0.0, 'volatility': 1, 'max_win': None, 'reels': None, 'rows': None}

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # Wait for the "Game Stats" section to appear
        try:
            page.wait_for_selector('span[data-translation="casino.game_stats"]', timeout=15000)
            print(" + Section 'Game Stats' found.")
        except:
            print(" - TIMEOUT: Could not find 'Game Stats' section.")
            return

        # Give the JS extra time to populate the specific numbers
        page.wait_for_timeout(4000)

        def get_value_by_label(label_key):
            try:
                # Find the span that has the translation attribute
                label_span = page.locator(f"span[data-translation='{label_key}']").first

                # Go up to the parent div and find the first 'p' tag that follows it
                # This is the most reliable way based on the Blade template structure
                val_loc = label_span.locator(
                    "xpath=./ancestor::div[1]//following-sibling::p | ./parent::div/following-sibling::p").first

                # If that fails, try looking for the text-bulma class in the same container
                if val_loc.count() == 0:
                    val_loc = label_span.locator("xpath=./ancestor::div[contains(@class, 'flex')]//p").last

                for _ in range(15):  # Retry loop to wait for JS hydration
                    raw_text = val_loc.inner_text().strip()
                    # Log the raw text so we can see what's happening
                    print(f"   [LOG] Label '{label_key}' raw text: '{raw_text}'")

                    # Check if it's a real value (contains a number) and NOT just a label like 'Casino'
                    if raw_text and any(char.isdigit() for char in raw_text):
                        return raw_text

                    page.wait_for_timeout(500)  # Wait 0.5s before retrying

                return None
            except Exception as e:
                print(f"   [LOG] Error parsing label '{label_key}': {e}")
                return None

        # --- Extract RTP ---
        rtp_raw = get_value_by_label("casino.rtp")
        if rtp_raw:
            clean_rtp = re.sub(r'[^\d.]', '', rtp_raw)
            if clean_rtp:
                extracted['rtp'] = float(clean_rtp)
                print(f" + Parsed RTP: {extracted['rtp']}")
        else:
            print(" - Failed to extract RTP.")

        # --- Extract Volatility ---
        vol_raw = get_value_by_label("casino.volatility")
        if vol_raw:
            extracted['volatility'] = get_volatility_level(vol_raw)
            print(f" + Parsed Volatility: {vol_raw} (Mapped to {extracted['volatility']})")

        # Only update if we found something useful
        if extracted['rtp'] > 0:
            if update_slot_in_db(slot_id, extracted):
                print(f"✅ SUCCESS: ID {slot_id} updated in database.")
        else:
            print(f"⚠️ SKIPPED: No valid RTP found for ID {slot_id}, skipping DB update.")

    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")
    finally:
        browser.close()


def run():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, url FROM slots WHERE url IS NOT NULL AND theoretical_rtp = 0 LIMIT 100")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"DB Connection Error: {e}")
        return

    if not rows:
        print("No slots need updating.")
        return

    with sync_playwright() as p:
        for row in rows:
            scrape_slot_details(p, row['id'], row['url'])
            time.sleep(3)


if __name__ == "__main__":
    run()