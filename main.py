import os
import json
import time
import re
import requests
import smtplib
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import google.generativeai as genai
from imap_tools import MailBox, AND
from bs4 import BeautifulSoup

# Load environment variables
load_dotenv()

# Configuration and Credentials
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
API_KEY = os.getenv("GEMINI_API_KEY")

FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSd2Ja2GrkyzvA87hBX47bLTYZDbS_OmE2UMBNa5sWIwLwbiWw/formResponse"
LOG_FILE = "processed_emails.txt"
MODEL_NAME = "gemini-2.5-flash"

if not all([EMAIL_USER, EMAIL_PASS, API_KEY]):
    raise ValueError("Missing credentials in .env file.")

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel(MODEL_NAME)

def get_processed_ids():
    """Returns a set of already processed email message IDs."""
    if not os.path.exists(LOG_FILE):
        return set()
    with open(LOG_FILE, "r") as f:
        return set(line.strip() for line in f)

def log_email_id(msg_id):
    """Appends a processed message ID to the log file."""
    with open(LOG_FILE, "a") as f:
        f.write(f"{msg_id}\n")

def clean_html(html_content):
    """Strips HTML tags and returns cleaned text."""
    if not html_content: return ""
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style", "head", "title", "meta"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())[:10000]

def send_rejection_mail(to_email, subject, missing_fields, message_id):
    """Sends an automated reply for orders with missing details."""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = to_email
        msg['Subject'] = f"Re: {subject}" 
        if message_id:
            msg['In-Reply-To'] = message_id
            msg['References'] = message_id

        body = (
            "Hello,\n\n"
            "We received your order request, but the following mandatory details are missing:\n"
            f"- {', '.join(missing_fields)}\n\n"
            "Please reply with the missing information."
        )
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)
        server.quit()
        print(f"Rejection sent to {to_email}")
        return True
    except Exception as e:
        print(f"Failed to send reply: {e}")
        return False

def push_to_google_form(data):
    """Submits order data to the specified Google Form."""
    form_data = {
        "entry.615877759": data.get("OrderID", "N/A"),
        "entry.1585791784": data.get("Item"),
        "entry.1838659577": data.get("Qty"),
        "entry.330026612": data.get("Price"),
        "entry.2119981260": data.get("Date")
    }
    try:
        requests.post(FORM_URL, data=form_data)
        print(f"Form updated for item: {data['Item']}")
    except Exception as e:
        print(f"Form submission failed: {e}")

def extract_order_details(body, subject):
    """Uses Gemini to parse order information from email text."""
    text = clean_html(body)
    if len(text) < 10: return []

    prompt = (
        f"Extract purchase details from the following. Subject: {subject}. Body: {text[:4000]}\n"
        "Return a JSON list with the schema: [{\"OrderID\": \"id\", \"Item\": \"name\", \"Qty\": 0, \"Price\": 0}]\n"
        "Rules: If Qty or Price is missing, set value to 0. Price must be a number."
    )
    
    try:
        response = model.generate_content(prompt)
        match = re.search(r"\[.*\]", response.text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception as e:
        print(f"Extraction error: {e}")
    return []

def main():
    print("Bot starting. Checking inbox...")
    processed_ids = get_processed_ids()

    with MailBox('imap.gmail.com').login(EMAIL_USER, EMAIL_PASS) as mailbox:
        for msg in mailbox.fetch(AND(subject="Order"), limit=5, reverse=True):
            
            # Skip replies and forwards to prevent infinite loops
            subject_clean = msg.subject.strip().upper()
            if subject_clean.startswith(("RE:", "FWD:")):
                continue

            msg_id = msg.obj['Message-ID']
            if msg_id.strip() in processed_ids:
                continue

            print(f"Processing: {msg.subject}")
            items = extract_order_details(msg.html or msg.text, msg.subject)
            
            if items:
                valid_items = []
                missing_fields_set = set()
                email_has_error = False
                
                for item in items:
                    if not item.get("Price") or item.get("Price") == 0:
                        missing_fields_set.add("Price")
                    if not item.get("Qty") or item.get("Qty") == 0:
                        missing_fields_set.add("Quantity")
                    
                    if missing_fields_set:
                        email_has_error = True
                        continue

                    item["Source"] = msg.subject
                    item["Date"] = msg.date_str
                    if not item.get("OrderID"):
                        item["OrderID"] = msg.subject
                    
                    valid_items.append(item)

                if email_has_error:
                    print(f"Validation failed. Missing fields: {list(missing_fields_set)}")
                    if send_rejection_mail(msg.from_, msg.subject, list(missing_fields_set), msg_id):
                        log_email_id(msg_id)
                elif valid_items:
                    for v_item in valid_items:
                        push_to_google_form(v_item)
                    log_email_id(msg_id)
            else:
                print("No order data detected.")
                log_email_id(msg_id)
            
            time.sleep(2)

if __name__ == "__main__":
    main()