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

# --- 1. NEW GOOGLE LIBRARY (Removes the Warning) ---
from google import genai
from google.genai import types

# --- SELENIUM IMPORTS ---
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

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

# Initialize New Client
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
        msg['Subject'] = f"Re: {subject}" 
        msg['In-Reply-To'] = message_id
        msg['References'] = message_id
        body = f"Hello,\n\nMissing details: {', '.join(missing_fields)}.\nPlease reply."
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)
        server.quit()
        print(f"   ↩️ REJECTION SENT to {to_email}")
        return True
    except: return False

# --- 2. UPDATED SELENIUM LOGIC (The Real Fix) ---
def fill_form_live_with_selenium(data):
    print(f"   🤖 Launching Chrome for: {data['Item']}...")
    
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    # This prevents the browser from closing instantly if script crashes
    options.add_experimental_option("detach", True) 
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        driver.get(FORM_URL)
        
        # INCREASED WAIT: Gives you 15 seconds to see if a Login Screen appears
        wait = WebDriverWait(driver, 15)

        field_mapping = {
            "Order ID": data.get("OrderID"),
            "Item": data.get("Item"),
            "Quantity": data.get("Qty"),
            "Price": data.get("Price"),
            "Date": data.get("Date")
        }

        for question_title, answer in field_mapping.items():
            try:
                # --- FUZZY MATCH XPATH ---
                # Checks if the text CONTAINS the word (ignores " *" or spaces)
                xpath = f"//div[contains(@role, 'listitem')]//span[contains(text(), '{question_title}')]"
                
                # 1. Find the Question Title Label
                label_element = wait.until(EC.visibility_of_element_located((By.XPATH, xpath)))
                
                # 2. Find the Input box strictly associated with that label's container
                # This looks for an 'input' or 'textarea' inside the same container as the label
                input_box = label_element.find_element(By.XPATH, "./../../../../..//input | ./../../../../..//textarea")
                
                # 3. Type
                input_box.clear()
                input_box.send_keys(str(answer))
                print(f"      Typing '{answer}' into '{question_title}'...")
                time.sleep(0.5) 
                
            except Exception:
                print(f"      ⚠️ Skipped field '{question_title}' (Not found or obscured). Check if Login is required!")

        # Submit
        try:
            submit_button = driver.find_element(By.XPATH, "//span[text()='Submit']")
            submit_button.click()
            print("      ✅ Submitted!")
            time.sleep(3)
            driver.quit() # Only close if successful
            print("   📂 Opening Results Sheet...")
            webbrowser.open(RESULTS_SHEET_URL)
        except:
            print("      ⚠️ Could not find Submit button.")

    except Exception as e:
        print(f"   ❌ Browser Error: {e}")
        # Driver will NOT quit here automatically so you can see what went wrong

def extract_order_details(body, subject):
    text = clean_html(body)
    prompt = f"""
    Extract purchase details. Subject: {subject}. Body: {text[:4000]}
    Return JSON list. Schema: [{{"OrderID": "id", "Item": "name", "Qty": 0, "Price": 0}}]
    Rules: If Qty or Price is missing, set to 0.
    """
    try:
        # UPDATED FOR NEW GOOGLE LIBRARY
        response = client.models.generate_content(
            model="gemini-2.5-flash", # Using the newer, faster model
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
                    if not item.get("OrderID"): item["OrderID"] = "AUTO"
                    valid_items.append(item)

                if error:
                    print(f"   ⚠️ Validation Failed! Missing: {missing}")
                    if send_rejection_mail(msg.from_, msg.subject, list(missing), msg_id):
                        log_email_id(msg_id)
                elif valid_items:
                    for v_item in valid_items:
                        fill_form_live_with_selenium(v_item)
                    
                    log_email_id(msg_id)
            else:
                log_email_id(msg_id)
            
            time.sleep(2)

if __name__ == "__main__":
    main()