"""
The Lakes Golf Club - Automated Tee Time Booker
Generated: 27/02/2026 | Mode: Book Group
================================================
Runs via GitHub Actions automatically
"""

import os, sys, re, logging
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

CONFIG = {
    "username":      os.getenv("GOLF_USERNAME"),  # Set GOLF_USERNAME in GitHub Secrets
    "password":      os.getenv("GOLF_PASSWORD"),  # Set GOLF_PASSWORD in GitHub Secrets
    "booking_date":  "2026-03-06",   # Friday 6 March 2026
    "book_mode":     "group",  # Clicks "BOOK GROUP" — books the whole tee time
    "tee":           "1ST TEE",       # Only book slots starting from this tee
    "earliest_time": "13:30",
    "latest_time":   "14:00",
    "headless":      False,              # Change to True to run silently
    "login_url":     "https://www.thelakesgolfclub.com.au/security/login.msp",
    "booking_url":   "https://www.thelakesgolfclub.com.au/members/bookings/index.xsp?booking_resource_id=3000000",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("golf_booker")

def time_in_window(t_str):
    try:
        t  = datetime.strptime(t_str.strip().zfill(5), "%H:%M").time()
        lo = datetime.strptime(CONFIG["earliest_time"], "%H:%M").time()
        hi = datetime.strptime(CONFIG["latest_time"],   "%H:%M").time()
        return lo <= t <= hi
    except ValueError:
        return False

def row_has_players(tee_row):
    # Returns True if any cell has class cell-taken (player already booked)
    return tee_row.locator("div.cell-taken").count() > 0

def run():
    target_date = datetime.strptime(CONFIG["booking_date"], "%Y-%m-%d")
    book_mode   = CONFIG["book_mode"]
    tee_filter  = CONFIG["tee"]
    btn_label   = "Book Group" if book_mode == "group" else "Book Me"
    # strftime "%-d" removes leading zero on Linux; "%#d" on Windows
    import platform
    fmt = "%#d %b" if platform.system() == "Windows" else "%-d %b"
    date_label = target_date.strftime(fmt)
    log.info("=" * 50)
    log.info(f"Target:  {target_date.strftime('%A %d %B %Y')}")
    log.info(f"Mode:    {btn_label}  |  Tee: {tee_filter}")
    log.info(f"Window:  {CONFIG['earliest_time']}–{CONFIG['latest_time']}")
    log.info("=" * 50)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=CONFIG["headless"])
        page    = browser.new_context().new_page()

        # ── LOGIN ───────────────────────────────────────────
        log.info("Logging in...")
        page.goto(CONFIG["login_url"], wait_until="networkidle")
        for sel in ['input[name="memberLogin"]', 'input[name="username"]', 'input[type="text"]:visible']:
            if page.locator(sel).count() > 0:
                page.fill(sel, CONFIG["username"]); break
        for sel in ['input[name="memberPassword"]', 'input[name="password"]', 'input[type="password"]']:
            if page.locator(sel).count() > 0:
                page.fill(sel, CONFIG["password"]); break
        for sel in ['input[type="submit"]', 'button[type="submit"]', 'button:has-text("Login")']:
            if page.locator(sel).count() > 0:
                page.click(sel); break
        page.wait_for_load_state("networkidle")
        if any(x in page.inner_text("body").lower() for x in ["invalid password", "login failed"]):
            log.error("Login failed."); page.screenshot(path="login_failed.png"); browser.close(); sys.exit(1)
        log.info("Logged in successfully.")

        # ── NAVIGATE TO BOOKING PAGE ─────────────────────────
        page.goto(CONFIG["booking_url"], wait_until="networkidle")
        page.wait_for_timeout(4000)

        # ── FIND TARGET DATE ────────────────────────────────
        log.info(f"Looking for date: {date_label}")
        booked = False
        try:
            page.wait_for_selector(".full", timeout=10000)
            event_blocks = page.locator(".full").all()
            log.info(f"Found {len(event_blocks)} event blocks on page")
            found = False
            for block in event_blocks:
                try:
                    block_text = block.inner_text(timeout=500)
                    if date_label not in block_text:
                        continue
                    log.info(f"Found block containing {date_label}")
                    open_link = block.locator("a.eventStatusOpen").first
                    if open_link.count() == 0:
                        log.warning("Date found but not OPEN (may be LOCKED or VIEW ONLY)")
                        page.screenshot(path="not_open.png")
                        browser.close(); sys.exit(1)
                    href = open_link.get_attribute("href")
                    log.info(f"Navigating to: {href}")
                    page.goto(f"https://www.thelakesgolfclub.com.au{href}", wait_until="networkidle")
                    page.wait_for_timeout(3000)
                    found = True
                    break
                except Exception as e:
                    log.debug(f"Block error: {e}")
                    continue
            if not found:
                log.warning(f"Date {date_label} not found on page")
                page.screenshot(path="date_not_found.png")
                browser.close(); sys.exit(1)

            # ── SCAN TEE SHEET ──────────────────────────────────
            page.wait_for_selector("div.row-time", timeout=10000)
            page.wait_for_timeout(2000)
            tee_rows = page.locator("div.row-time").all()
            log.info(f"Found {len(tee_rows)} tee time rows")

            for tee_row in tee_rows:
                try:
                    row_text = tee_row.inner_text(timeout=500)

                    if tee_filter == "1ST TEE" and "1st Tee" not in row_text:
                        continue
                    if tee_filter == "10TH TEE" and "10th Tee" not in row_text:
                        continue

                    times = re.findall(r'\b(\d{1,2}:\d{2})\s*(am|pm)\b', row_text, re.IGNORECASE)
                    if not times:
                        continue
                    raw_time = times[0][0] + " " + times[0][1].upper()
                    try:
                        t24 = datetime.strptime(raw_time, "%I:%M %p").strftime("%H:%M")
                    except Exception:
                        t24 = times[0][0].zfill(5)

                    if not time_in_window(t24):
                        continue

                    cells = tee_row.locator("[data-rowid]").all()
                    if not cells:
                        continue

                    has_players  = row_has_players(tee_row)
                    free_spots   = tee_row.locator("span.btn-label").count()
                    log.info(f"  {raw_time} ({tee_filter}): has_players={has_players}, free_spots={free_spots}")

                    if book_mode == "new" and has_players:
                        log.info(f"  Skipping {raw_time} — row has existing players (mode=new)")
                        continue
                    if book_mode == "join" and not has_players:
                        log.info(f"  Skipping {raw_time} — no existing players (mode=join)")
                        continue

                    if book_mode == "group":
                        btn = tee_row.locator("button.btn-book-group:not(.hide)").first
                    else:
                        btn = tee_row.locator("button.btn-book-me:not(.hide)").first

                    if btn.count() == 0:
                        log.debug("  Button not available, skipping")
                        continue

                    log.info(f"  Clicking '{btn_label}' at {raw_time}...")
                    btn.click()
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(2000)

                    for cs in ['button:has-text("Confirm")', 'button:has-text("OK")', 'button:has-text("Yes")', 'button:has-text("Submit")']:
                        try:
                            cb = page.locator(cs).first
                            if cb.is_visible(timeout=2000):
                                cb.click(); page.wait_for_load_state("networkidle")
                                log.info("  Confirmation clicked"); break
                        except Exception: continue

                    booked = True
                    log.info(f"  ✅ Booked '{btn_label}' at {raw_time}!")
                    break

                except Exception as e:
                    log.debug(f"  Row error: {e}")
                    continue

        except Exception as e:
            log.warning(f"Booking error: {e}")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fn = f"booking_{'success' if booked else 'failed'}_{ts}.png"
        page.screenshot(path=fn, full_page=True)
        log.info(f"Screenshot saved: {fn}")
        browser.close()

    if booked:
        log.info("✅ Tee time booked successfully!")
    else:
        log.warning("❌ No booking made — check screenshot for details.")

if __name__ == "__main__":
    run()
