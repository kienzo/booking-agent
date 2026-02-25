"""
The Lakes Golf Club - Automated Tee Time Booker (MiClub React/API Version)
===========================================================================
The booking page uses a React frontend backed by a REST API authenticated
with a JWT token stored in localStorage after login. This script:
  1. Logs in via Playwright to obtain the JWT token
  2. Calls the MiClub API directly to find and book tee times
  3. Falls back to UI interaction if API endpoints change

SETUP:
  pip install playwright python-dotenv requests
  playwright install chromium

CREDENTIALS:
  Create a .env file in the same folder:
    GOLF_USERNAME=35          (member number, no leading zeros)
    GOLF_PASSWORD=yourpassword

SCHEDULING (Mac - crontab):
  crontab -e
  Add: 0 11 * * 4 /usr/bin/python3 /path/to/lakes_golf_booker.py >> /path/to/booker.log 2>&1
  (Runs every Thursday at 11:00am)
  Find your python path with: which python3
"""

import os
import sys
import re
import json
import logging
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ─────────────────────────────────────────────
#  USER CONFIGURATION — edit these values
# ─────────────────────────────────────────────
load_dotenv()

CONFIG = {
    # Credentials (from .env file)
    "username": os.getenv("GOLF_USERNAME", ""),
    "password": os.getenv("GOLF_PASSWORD", ""),

    # Playing preferences
    "num_players":    4,              # Players in your group (2, 3, or 4)
    "preferred_day":  "Saturday",     # Day of week you want to play
    "days_ahead":     7,              # How many days ahead to book

    # Tee time window (24hr format) — mid-morning
    "earliest_time":  "08:00",
    "latest_time":    "10:00",

    # Show browser window during run (set True for testing, False for silent running)
    "headless":       True,

    # Club-specific URLs
    "login_url":      "https://www.thelakesgolfclub.com.au/security/login.msp",
    "booking_url":    "https://www.thelakesgolfclub.com.au/members/bookings/index.xsp?booking_resource_id=3000000",
    "api_base":       "https://thelakesgolfclub.com.au",
    "booking_resource_id": "3000000",
}

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("golf_booker")


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
def get_target_date() -> datetime:
    """Calculate the next occurrence of the preferred playing day."""
    today = datetime.today()
    target = today + timedelta(days=CONFIG["days_ahead"])
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    desired_wd = day_names.index(CONFIG["preferred_day"])
    delta = (desired_wd - target.weekday()) % 7
    return target + timedelta(days=delta)


def time_in_window(time_str: str) -> bool:
    """Return True if a time string (HH:MM or H:MM) is within the preferred window."""
    try:
        # Handle both "8:00" and "08:00" formats
        t  = datetime.strptime(time_str.strip().zfill(5), "%H:%M").time()
        lo = datetime.strptime(CONFIG["earliest_time"], "%H:%M").time()
        hi = datetime.strptime(CONFIG["latest_time"],   "%H:%M").time()
        return lo <= t <= hi
    except ValueError:
        return False


def extract_jwt_from_page(page):
    """Extract the JWT token that MiClub stores in localStorage after login."""
    try:
        token = page.evaluate("() => localStorage.getItem('token')")
        if token:
            log.info("JWT token extracted from localStorage.")
            return token
    except Exception as e:
        log.warning(f"Could not extract JWT from localStorage: {e}")
    return None


# ─────────────────────────────────────────────
#  API CALLS
# ─────────────────────────────────────────────
def api_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }


def fetch_available_slots(token: str, target_date: datetime) -> list:
    """
    Call the MiClub API to get available tee times for the target date.
    MiClub's React app uses a REST API at /api/... endpoints.
    """
    date_str = target_date.strftime("%Y-%m-%d")
    base = CONFIG["api_base"]
    resource_id = CONFIG["booking_resource_id"]

    # Common MiClub API endpoint patterns
    endpoints_to_try = [
        f"https://{base}/api/booking/teetimes?date={date_str}&resourceId={resource_id}",
        f"https://{base}/api/teetimes?date={date_str}&bookingResourceId={resource_id}",
        f"https://{base}/api/eventlist?date={date_str}&resourceId={resource_id}",
    ]

    for endpoint in endpoints_to_try:
        try:
            log.info(f"Trying API endpoint: {endpoint}")
            resp = requests.get(endpoint, headers=api_headers(token), timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                log.info(f"Got response from {endpoint}")
                return data
            else:
                log.debug(f"  → {resp.status_code}")
        except Exception as e:
            log.debug(f"  → Error: {e}")

    log.warning("Could not fetch slots via API — will fall back to UI scraping.")
    return []


def book_slot_via_api(token: str, slot: dict) -> bool:
    """Attempt to book a specific tee time slot via the API."""
    base = CONFIG["api_base"]
    resource_id = CONFIG["booking_resource_id"]

    # Extract slot identifiers — field names vary by MiClub version
    slot_id   = slot.get("id") or slot.get("slotId") or slot.get("teeTimeId")
    slot_time = slot.get("time") or slot.get("startTime") or slot.get("teeTime")

    if not slot_id:
        log.warning("Could not identify slot ID from API response.")
        return False

    payload = {
        "bookingResourceId": resource_id,
        "slotId":            slot_id,
        "numberOfPlayers":   CONFIG["num_players"],
    }

    endpoints_to_try = [
        f"https://{base}/api/booking/book",
        f"https://{base}/api/booking/create",
        f"https://{base}/api/teetimes/book",
    ]

    for endpoint in endpoints_to_try:
        try:
            log.info(f"Attempting to book slot {slot_time} via {endpoint}")
            resp = requests.post(endpoint, headers=api_headers(token), json=payload, timeout=15)
            if resp.status_code in (200, 201):
                log.info(f"✓ Booking confirmed via API! Slot: {slot_time}")
                return True
            else:
                log.debug(f"  → {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            log.debug(f"  → Error: {e}")

    return False


# ─────────────────────────────────────────────
#  UI FALLBACK — click through the React app
# ─────────────────────────────────────────────
def book_via_ui(page, target_date: datetime) -> bool:
    """
    Fallback: interact with the React-rendered tee sheet directly.
    Waits for React to render, then finds and clicks the best available slot.
    """
    log.info("Falling back to UI-based booking...")

    # Navigate to booking page and wait for React to render
    page.goto(CONFIG["booking_url"], wait_until="networkidle")
    log.info("Waiting for React tee sheet to render...")

    # Wait up to 15s for tee time slots to appear
    try:
        page.wait_for_selector(
            "[class*='teetime'], [class*='tee-time'], [class*='slot'], "
            "[class*='booking-row'], [data-time], [class*='available']",
            timeout=15000
        )
    except PlaywrightTimeout:
        log.warning("Tee sheet did not render within 15s. Taking debug screenshot.")
        page.screenshot(path=f"debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png", full_page=True)
        return False

    # Look for the target date — the React app may show a week view with day headers
    date_label = target_date.strftime("%-d %b")  # e.g. "12 Apr" — Mac/Linux format
    try:
        page.click(f"text={date_label}", timeout=5000)
        page.wait_for_load_state("networkidle")
        log.info(f"Navigated to date: {date_label}")
    except Exception:
        log.debug("Could not click date label — may already be on correct date.")

    # Find all booking buttons/rows
    page.wait_for_timeout(2000)

    # Try multiple selector patterns that MiClub React uses
    slot_selectors = [
        "button:has-text('Book')",
        "[class*='available'] button",
        "[class*='teetime'][class*='available']",
        "td.open a",
        "[data-available='true'] button",
    ]

    for selector in slot_selectors:
        slots = page.locator(selector).all()
        if slots:
            log.info(f"Found {len(slots)} slots with selector: {selector}")
            for slot in slots:
                try:
                    # Get surrounding text to find the time
                    parent_text = slot.locator("xpath=ancestor::*[3]").first.inner_text()
                    times = re.findall(r'\b([01]?\d|2[0-3]):[0-5]\d\b', parent_text)
                    if not times:
                        continue
                    slot_time = times[0].zfill(5)
                    log.info(f"  Slot time: {slot_time}")
                    if time_in_window(slot_time):
                        log.info(f"  ✓ Within window — clicking to book {slot_time}...")
                        slot.click()
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(1500)

                        # Look for and click any confirmation step
                        for confirm_sel in [
                            "button:has-text('Confirm')",
                            "button:has-text('Submit')",
                            "button:has-text('Book Now')",
                            "input[value='Confirm']",
                        ]:
                            try:
                                btn = page.locator(confirm_sel).first
                                if btn.is_visible(timeout=3000):
                                    btn.click()
                                    page.wait_for_load_state("networkidle")
                                    log.info("  ✓ Confirmation clicked!")
                                    break
                            except Exception:
                                continue

                        return True
                except Exception as e:
                    log.debug(f"  Skipping slot: {e}")
                    continue

    log.warning("No bookable slots found within preferred time window via UI.")
    return False


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
def run():
    if not CONFIG["username"] or not CONFIG["password"]:
        log.error("Credentials missing. Add GOLF_USERNAME and GOLF_PASSWORD to your .env file.")
        sys.exit(1)

    target_date = get_target_date()
    log.info(f"{'='*50}")
    log.info(f"Target date:   {target_date.strftime('%A %d %B %Y')}")
    log.info(f"Players:       {CONFIG['num_players']}")
    log.info(f"Time window:   {CONFIG['earliest_time']} – {CONFIG['latest_time']}")
    log.info(f"{'='*50}")

    booked = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=CONFIG["headless"])
        context = browser.new_context()
        page = context.new_page()

        # ── 1. LOGIN ──────────────────────────────────────────────────────
        log.info("Logging in...")
        page.goto(CONFIG["login_url"], wait_until="networkidle")

        try:
            # Dump the login form to help debug field names
            form_html = page.inner_html("form") if page.locator("form").count() > 0 else page.content()
            log.info("Login page loaded. Saving debug screenshot...")
            page.screenshot(path="login_page_debug.png")

            # Log all input field names found on the page
            inputs = page.locator("input").all()
            for inp in inputs:
                name = inp.get_attribute("name") or ""
                type_ = inp.get_attribute("type") or ""
                log.info(f"  Found input: name='{name}' type='{type_}'")

            # Fill username — try all known MiClub field names
            filled_user = False
            for selector in ['input[name="memberLogin"]', 'input[name="username"]',
                             'input[name="login"]', 'input[name="user"]',
                             'input[type="text"]:visible']:
                try:
                    if page.locator(selector).count() > 0:
                        page.fill(selector, CONFIG["username"])
                        log.info(f"  Filled username with selector: {selector}")
                        filled_user = True
                        break
                except Exception:
                    continue

            # Fill password
            filled_pass = False
            for selector in ['input[name="memberPassword"]', 'input[name="password"]',
                             'input[name="pass"]', 'input[type="password"]']:
                try:
                    if page.locator(selector).count() > 0:
                        page.fill(selector, CONFIG["password"])
                        log.info(f"  Filled password with selector: {selector}")
                        filled_pass = True
                        break
                except Exception:
                    continue

            if not filled_user or not filled_pass:
                log.error("Could not find login form fields. Check login_page_debug.png")
                browser.close()
                sys.exit(1)

            # Submit
            for selector in ['input[type="submit"]', 'button[type="submit"]',
                             'button:has-text("Login")', 'button:has-text("Log In")',
                             'input[value="Login"]', 'input[value="Log In"]']:
                try:
                    if page.locator(selector).count() > 0:
                        page.click(selector)
                        log.info(f"  Clicked submit with selector: {selector}")
                        break
                except Exception:
                    continue

            page.wait_for_load_state("networkidle")
            page.screenshot(path="after_login_debug.png")
            log.info("Post-login screenshot saved: after_login_debug.png")

        except Exception as e:
            log.error(f"Login interaction failed: {e}")
            page.screenshot(path="login_error.png")
            browser.close()
            sys.exit(1)

        # Check for login failure — but be lenient since "error" appears in many page elements
        page_text = page.inner_text("body").lower()
        if any(x in page_text for x in ["invalid password", "incorrect password", "login failed", "invalid username"]):
            log.error("Login appears to have failed. Check your username and password.")
            page.screenshot(path="login_failed.png")
            browser.close()
            sys.exit(1)

        log.info("Login successful.")

        # ── 2. NAVIGATE TO BOOKING PAGE TO GET JWT TOKEN ──────────────────
        log.info("Loading booking page to retrieve auth token...")
        page.goto(CONFIG["booking_url"], wait_until="networkidle")
        page.wait_for_timeout(3000)  # Give React time to initialise and set localStorage

        token = extract_jwt_from_page(page)

        # ── 3. TRY API BOOKING FIRST ──────────────────────────────────────
        if token:
            slots = fetch_available_slots(token, target_date)

            if slots:
                # Flatten response — API may return list directly or nested
                if isinstance(slots, dict):
                    slots = slots.get("teetimes") or slots.get("slots") or slots.get("data") or []

                log.info(f"Found {len(slots)} slots from API.")

                for slot in slots:
                    slot_time = slot.get("time") or slot.get("startTime") or slot.get("teeTime", "")
                    # Normalise time format
                    time_match = re.search(r'(\d{1,2}:\d{2})', str(slot_time))
                    if time_match and time_in_window(time_match.group(1)):
                        log.info(f"Preferred slot found: {slot_time}")
                        booked = book_slot_via_api(token, slot)
                        if booked:
                            break
            else:
                log.info("API returned no slots — trying UI approach.")

        # ── 4. FALLBACK TO UI IF API DIDN'T WORK ─────────────────────────
        if not booked:
            booked = book_via_ui(page, target_date)

        # ── 5. SAVE SCREENSHOT AS RECORD ─────────────────────────────────
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = f"booking_{'success' if booked else 'failed'}_{ts}.png"
        page.screenshot(path=screenshot_path, full_page=True)
        log.info(f"Screenshot saved: {screenshot_path}")

        browser.close()

    if booked:
        log.info("✅ Tee time booked successfully!")
    else:
        log.warning("❌ Could not book a tee time. Check the screenshot and logs.")

    return booked


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
