THE LAKES GOLF CLUB — TEE TIME BOOKER (Mac)
============================================

SETUP (Terminal):

1. Move this folder to your Desktop or Documents

2. Install dependencies (only needed once):
   pip3 install playwright python-dotenv requests
   playwright install chromium

3. Rename .env.template to .env and fill in your details:
   GOLF_USERNAME=35        (no leading zeros)
   GOLF_PASSWORD=yourpassword

4. Run it:
   cd ~/Desktop/golf-mac
   python3 lakes_golf_booker.py

5. Schedule for every Thursday at 11:30am:
   crontab -e
   Add this line (update the path):
   30 11 * * 4 /usr/bin/python3 ~/Desktop/golf-mac/lakes_golf_booker.py >> ~/Desktop/golf-mac/booker.log 2>&1

CONFIGURATION:
   Open lakes_golf_booker.py in TextEdit to change:
   - preferred_day  (e.g. "Saturday")
   - earliest_time  (e.g. "08:00")
   - latest_time    (e.g. "10:00")
   - num_players    (2, 3, or 4)
   - headless       (True = silent, False = show browser)

AFTER EACH RUN:
   A screenshot is saved as proof of booking.
   booking_success_YYYYMMDD.png = worked
   booking_failed_YYYYMMDD.png  = something went wrong
