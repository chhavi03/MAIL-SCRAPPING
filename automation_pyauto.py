import os
import json
import time
import re
import smtplib
import webbrowser
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from imap_tools import MailBox, AND
from bs4 import BeautifulSoup
import pyautogui

# --- GOOGLE GEN AI ---
from google import genai

# Load environment variables
load_dotenv()

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
API_KEY = os.getenv("GEMINI_API_KEY")

FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSd2Ja2GrkyzvA87hBX47bLTYZDbS_OmE2UMBNa5sWIwLwbiWw/viewform"
RESULTS_SHEET_URL = "https://docs.google.com/spreadsheets/d/1AQPzZYNeiZsDTSOGHWzhlYWG7cF1jvOix1H8P7pgvsM/edit?resourcekey=&gid=657004549#gid=657004549"
LOG_FILE = "processed_emails.txt"

if not all([EMAIL_USER, EMAIL_PASS, API_KEY]):
    raise ValueError("Missing credentials in .env file.")

# Initialize AI Client
client = genai.Client(api_key=API_KEY)

def get_processed_ids():
    if not os.path.exists(LOG_FILE): return set()
    with open(LOG_FILE, "r") as f: return set(line.strip() for line in f)

def log_email_id(msg_id):
    with open(LOG_FILE, "a") as f: f.write(f"{msg_id}\n")

def clean_html(html_content):
    if not html_content: return ""
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style", "head", "title", "meta"]): tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())[:10000]

def send_rejection_mail(to_email, subject, missing_fields, message_id):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = to_email
        
        # --- THE FIX: Keep the subject exactly the same to maintain the thread! ---
        msg['Subject'] = f"Re: {subject}" 
        msg['In-Reply-To'] = message_id
        msg['References'] = message_id
        
        # Format the missing fields as a clean bulleted list
        fields_bulleted = "\n".join([f"  • {field}" for field in missing_fields])
        
        # Professional, structured body text
        body = (
            f"Hello,\n\n"
            f"Thank you for submitting your order request. Our automated system has received your email.\n\n"
            f"Unfortunately, we cannot process the order right now because the following mandatory details are missing:\n"
            f"{fields_bulleted}\n\n"
            f"To keep your order moving, please reply directly to this email with the missing information.\n\n"
            f"Best regards,\n"
            f"Automated Order Processing Bot\n"
            f"Celebal Technologies"
        )
        
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)
        server.quit()
        print(f"   ↩️ REJECTION SENT to {to_email}")
        return True
    except Exception as e:
        print(f"   ❌ Failed to send reply: {e}")
        return False

# --- LIVE KEYBOARD AUTOMATION (PYAUTOGUI) ---
def fill_form_live_with_pyautogui(data):
    print(f"   🤖 Opening Form for: {data['Item']}...")
    
    # 1. Open the browser
    webbrowser.open(FORM_URL)
    
    # 2. WAIT for the page to load completely
    print("   ⏳ Waiting 7 seconds for page load... DO NOT TOUCH MOUSE OR KEYBOARD!")
    time.sleep(7) 
    
    try:
        # 3. Navigate to the first input field
        # NOTE: On most Google Forms, pressing Tab 1 time brings you to the first text box.
        # If it skips the box, change this to 2 or 0 depending on your browser.
        INITIAL_TABS = 4 
        for _ in range(INITIAL_TABS):
            pyautogui.press('tab')
            time.sleep(0.5)

        # 4. Type Order ID
        print(f"      Typing Order ID: {data.get('OrderID')}")
        pyautogui.write(str(data.get("OrderID", "AUTO")), interval=0.05)
        pyautogui.press('tab')
        time.sleep(0.5)

        # 5. Type Item
        print(f"      Typing Item: {data.get('Item')}")
        pyautogui.write(str(data.get("Item", "")), interval=0.05)
        pyautogui.press('tab')
        time.sleep(0.5)

        # 6. Type Quantity
        print(f"      Typing Qty: {data.get('Qty')}")
        pyautogui.write(str(data.get("Qty", "")), interval=0.05)
        pyautogui.press('tab')
        time.sleep(0.5)

        # 7. Type Price
        print(f"      Typing Price: {data.get('Price')}")
        pyautogui.write(str(data.get("Price", "")), interval=0.05)
        pyautogui.press('tab')
        time.sleep(0.5)

        # 8. Type Date (Since your image shows it as a short text answer)
        print(f"      Typing Date: {data.get('Date')}")
        pyautogui.write(str(data.get("Date", "")), interval=0.05)
        pyautogui.press('tab')
        time.sleep(0.5)

        # 9. Submit! (Usually Tab once more lands on the Submit button)
        pyautogui.press('enter')
        print("      ✅ Submitted!")
        
        # Wait for Google to process the submission
        time.sleep(3)
        
        # 10. Open the Spreadsheet to show the manager
        print("   📂 Opening Results Sheet...")
        webbrowser.open(RESULTS_SHEET_URL)

    except Exception as e:
        print(f"   ❌ PyAutoGUI Error: {e}")

def extract_order_details(body, subject):
    text = clean_html(body)
    prompt = f"""
    Extract purchase details. Subject: {subject}. Body: {text[:4000]}
    Return JSON list. Schema: [{{"OrderID": "id", "Item": "name", "Qty": 0, "Price": 0}}]
    Rules: If Qty or Price is missing, set to 0.
    """
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=prompt
        )
        match = re.search(r"\[.*\]", response.text, re.DOTALL)
        if match: return json.loads(match.group(0))
    except Exception as e:
        print(f"AI Error: {e}")
    return []

def main():
    print("[Info] Bot Active. Waiting for emails...")
    processed_ids = get_processed_ids()

    with MailBox('imap.gmail.com').login(EMAIL_USER, EMAIL_PASS) as mailbox:
        for msg in mailbox.fetch(AND(subject="Order"), limit=5, reverse=True):
            
            if msg.subject.upper().startswith(("RE:", "FWD:")): continue
            msg_id = msg.obj['Message-ID']
            if msg_id.strip() in processed_ids: continue
            
            print(f"\n📧 New Email: {msg.subject}")
            items = extract_order_details(msg.html or msg.text, msg.subject)
            
            if items:
                valid_items = []
                missing = set()
                error = False
                
                for item in items:
                    if not item.get("Price") or item.get("Price") == 0: missing.add("Price")
                    if not item.get("Qty") or item.get("Qty") == 0: missing.add("Quantity")
                    if missing: 
                        error = True 
                        continue
                    
                    item["Date"] = msg.date_str
                    if not item.get("OrderID"): item["OrderID"] = msg.subject
                    valid_items.append(item)

                if error:
                    print(f"   ⚠️ Validation Failed! Missing: {missing}")
                    if send_rejection_mail(msg.from_, msg.subject, list(missing), msg_id):
                        log_email_id(msg_id)
                elif valid_items:
                    for v_item in valid_items:
                        # --- CALLLING PYAUTOGUI ---
                        fill_form_live_with_pyautogui(v_item)
                    
                    log_email_id(msg_id)
            else:
                print("   🚫 No data found in email.")
                log_email_id(msg_id)
            
            time.sleep(2)

if __name__ == "__main__":
    main()