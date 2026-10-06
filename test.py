import os
import json
import time
import re
import pandas as pd
from dotenv import load_dotenv
import google.generativeai as genai
from imap_tools import MailBox, AND
from bs4 import BeautifulSoup

# Load environment variables
load_dotenv()

# Configuration
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
API_KEY = os.getenv("GEMINI_API_KEY")
EXCEL_FILE = "order_summary.xlsx"
MODEL_NAME = "models/gemini-2.5-flash"  # Use specific model ID to avoid 404s

# Validate credentials
if not all([EMAIL_USER, EMAIL_PASS, API_KEY]):
    raise ValueError("Missing credentials. Please check your .env file.")

# Initialize API
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel(MODEL_NAME)

def clean_html(html_content):
    """Normalizes HTML content for token efficiency."""
    if not html_content: 
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style", "head", "title", "meta"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())[:10000]

def extract_order_details(body, subject):
    """Extracts order items using the AI model."""
    text = clean_html(body)
    if len(text) < 50: 
        return []

    prompt = f"""
    Extract a list of purchased items from this email.
    Return ONLY a raw JSON list of dictionaries.
    Schema: [{{"Item": "Product Name", "Qty": 1, "Price": 0.0}}]
    
    Subject: {subject}
    Body: {text[:4000]}
    """

    try:
        response = model.generate_content(prompt)
        # Regex to find JSON array within the response
        match = re.search(r"\[.*\]", response.text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception as e:
        print(f"[Error] Extraction failed: {e}")
    
    return []

def save_to_excel(data):
    """Saves data to Excel using a robust read-concat-write approach."""
    if not data: 
        return
    
    new_df = pd.DataFrame(data)
    
    # Standardize Date format
    if "Date" in new_df.columns:
        new_df["Date"] = pd.to_datetime(new_df["Date"], errors="coerce").dt.tz_localize(None)

    try:
        if os.path.exists(EXCEL_FILE):
            existing_df = pd.read_excel(EXCEL_FILE)
            combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            combined_df.to_excel(EXCEL_FILE, index=False)
        else:
            new_df.to_excel(EXCEL_FILE, index=False)
            
        print(f"[Info] Saved {len(data)} rows to {EXCEL_FILE}")
        
    except PermissionError:
        print(f"[Error] Permission denied. Please close '{EXCEL_FILE}' and try again.")
    except Exception as e:
        print(f"[Error] Excel write failed: {e}")

def main():
    print(f"[Info] Starting scraper using {MODEL_NAME}...")

    try:
        with MailBox('imap.gmail.com').login(EMAIL_USER, EMAIL_PASS) as mailbox:
            # Fetch recent 'Order' emails
            criteria = AND(subject="Order")
            for msg in mailbox.fetch(criteria, limit=3, reverse=True):
                print(f"Processing: {msg.subject}")
                
                items = extract_order_details(msg.html or msg.text, msg.subject)
                
                if items:
                    # Validate and tag data
                    valid_items = []
                    for item in items:
                        if isinstance(item, dict):
                            item["Source"] = msg.subject
                            item["Date"] = msg.date_str
                            valid_items.append(item)
                    
                    if valid_items:
                        save_to_excel(valid_items)
                    else:
                        print("  No valid items extracted.")
                else:
                    print("  No data found.")
                
                # Rate limit to prevent 429 errors
                time.sleep(2)

    except Exception as e:
        print(f"[Critical] Connection error: {e}")

    print("[Info] Process complete.")

if __name__ == "__main__":
    main()