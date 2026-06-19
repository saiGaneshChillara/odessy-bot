"""
BookMyShow Showtime Monitor
----------------------------
Watches a BookMyShow buy-tickets page and notifies you (Email / WhatsApp / SMS / Call)
whenever the showtimes/availability section changes.

Run with:
    python3 bms_monitor.py

Configure via a `.env` file in the same folder (see .env.example).
"""

import os
import time
import hashlib
import logging
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

# ---------- CONFIG ----------
URL = os.getenv("TARGET_URL", "https://in.bookmyshow.com/movies/hyderabad/the-odyssey/buytickets/ET00452034/20260717")
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))
STATE_FILE = "last_snapshot.txt"

# The container that holds theatre + showtime listings.
# BookMyShow's class names change often, so we fall back to a broad selector
# and just grab visible text from the main content area. You can narrow this
# down later if you want (e.g. to a specific theatre's row) -- see NOTES at bottom.
CONTENT_SELECTOR = os.getenv("CONTENT_SELECTOR", "body")

# Email config
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
EMAIL_TO = os.getenv("EMAIL_TO")

# Twilio config (optional)
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_SMS = os.getenv("TWILIO_FROM_SMS")          # Twilio phone number
TWILIO_FROM_WHATSAPP = os.getenv("TWILIO_FROM_WHATSAPP")  # e.g. whatsapp:+14155238886 (sandbox)
TWILIO_FROM_CALL = os.getenv("TWILIO_FROM_CALL")        # Twilio phone number for calls
MY_PHONE = os.getenv("MY_PHONE")                        # e.g. +91XXXXXXXXXX
MY_WHATSAPP = os.getenv("MY_WHATSAPP")                  # e.g. whatsapp:+91XXXXXXXXXX

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("bms_monitor")


def fetch_rendered_content():
    """Load the page with a real browser and return the text we care about."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ))
        page.goto(URL, timeout=30000, wait_until="networkidle")
        # give any lazy-loaded showtime widgets a moment to render
        page.wait_for_timeout(3000)
        content = page.locator(CONTENT_SELECTOR).inner_text()
        browser.close()
        return content


def hash_content(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_last_snapshot():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return None


def save_snapshot(text: str):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(text)


def send_email(subject: str, body: str):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and EMAIL_TO):
        log.info("Email not configured, skipping.")
        return
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = EMAIL_TO
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [EMAIL_TO], msg.as_string())
        log.info("Email sent.")
    except Exception as e:
        log.error(f"Email failed: {e}")


def get_twilio_client():
    if not (TWILIO_SID and TWILIO_AUTH_TOKEN):
        return None
    try:
        from twilio.rest import Client
        return Client(TWILIO_SID, TWILIO_AUTH_TOKEN)
    except ImportError:
        log.error("twilio package not installed (pip install twilio).")
        return None


def send_sms(body: str):
    client = get_twilio_client()
    if not client or not (TWILIO_FROM_SMS and MY_PHONE):
        log.info("SMS not configured, skipping.")
        return
    try:
        client.messages.create(body=body, from_=TWILIO_FROM_SMS, to=MY_PHONE)
        log.info("SMS sent.")
    except Exception as e:
        log.error(f"SMS failed: {e}")


def send_whatsapp(body: str):
    client = get_twilio_client()
    if not client or not (TWILIO_FROM_WHATSAPP and MY_WHATSAPP):
        log.info("WhatsApp not configured, skipping.")
        return
    try:
        client.messages.create(body=body, from_=TWILIO_FROM_WHATSAPP, to=MY_WHATSAPP)
        log.info("WhatsApp message sent.")
    except Exception as e:
        log.error(f"WhatsApp failed: {e}")


def send_call(message: str):
    client = get_twilio_client()
    if not client or not (TWILIO_FROM_CALL and MY_PHONE):
        log.info("Call not configured, skipping.")
        return
    try:
        twiml = f"<Response><Say>{message}</Say></Response>"
        client.calls.create(twiml=twiml, from_=TWILIO_FROM_CALL, to=MY_PHONE)
        log.info("Call placed.")
    except Exception as e:
        log.error(f"Call failed: {e}")


def notify_all(reason: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = "BookMyShow page changed!"
    body = f"[{timestamp}] Change detected on the page:\n{URL}\n\n{reason}\n\nGo check it now!"
    short_msg = "BookMyShow alert: showtimes page changed. Check it now."

    send_email(subject, body)
    send_sms(short_msg)
    send_whatsapp(short_msg)
    send_call("Alert. Book my show ticket page has changed. Please check it now.")


def main():
    log.info(f"Starting monitor for: {URL}")
    log.info(f"Checking every {CHECK_INTERVAL_SECONDS} seconds.")

    last_snapshot = load_last_snapshot()
    last_hash = hash_content(last_snapshot) if last_snapshot else None

    while True:
        try:
            content = fetch_rendered_content()
            current_hash = hash_content(content)

            if last_hash is None:
                log.info("First run -- saving baseline snapshot.")
                save_snapshot(content)
                last_hash = current_hash
            elif current_hash != last_hash:
                log.info("CHANGE DETECTED!")
                notify_all("The page content changed since the last check.")
                save_snapshot(content)
                last_hash = current_hash
            else:
                log.info("No change.")

        except Exception as e:
            log.error(f"Error during check: {e}")

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

# NOTES:
# - CONTENT_SELECTOR defaults to "body" (whole page text). This will also catch
#   irrelevant changes (ads, banners, etc). To narrow it down to just the
#   showtimes area, open the page in Chrome, right-click the theatre listing
#   section -> Inspect -> copy a stable class/id, then set CONTENT_SELECTOR
#   in .env, e.g. CONTENT_SELECTOR=".venue-list" (exact class will vary).
# - First run just saves a baseline -- you won't get a notification until the
#   *second* check shows a difference.
