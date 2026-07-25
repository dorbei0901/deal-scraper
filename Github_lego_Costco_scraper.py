import os
import json
import smtplib
import csv
import requests
from datetime import datetime
from email.message import EmailMessage

# GitHub Secrets
EMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
EMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
TO_EMAIL = os.environ.get("RECIPIENT_EMAIL")

STATE_FILE = "state.json"
CONTROL_FILE = "costco_items.json"
HISTORY_FILE = "price_history.csv"

def log_to_csv(item_number, title, price, availability):
    """Appends a new record to the historical CSV fact table."""
    file_exists = os.path.exists(HISTORY_FILE)
    
    with open(HISTORY_FILE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            # Write headers if the file is being created for the first time
            writer.writerow(['Timestamp', 'Item_Number', 'Title', 'Price', 'Availability'])
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        writer.writerow([timestamp, item_number, title, price, availability])

def fetch_costco_data(session, item_config):
    item_number = item_config['item_number']
    
    # --- 1. FETCH PRICE ---
    price_endpoint = 'https://gdx-api.costco.com/catalog/product/dispprice-api/v2/display-price'
    price_headers = {
        'Accept': '*/*',
        'Connection': 'keep-alive',
        'Origin': 'https://www.costco.ca',
        'Referer': 'https://www.costco.ca/',
        'client-identifier': '6b262714-2ed4-4dcb-a39d-39a4b0357309',
        'sec-ch-ua': '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
    }
    price_params = {
        'whsNumber': '894',
        'clientId': 'e442e6e6-2602-4a39-937b-8b28b4457ed3',
        'item': item_number,
        'country': 'CA',
        'locale': 'en-ca',
        'state': 'BC',
        'zipCode': 'V3E 0T2',
    }
    
    print(f"[{item_number}] Requesting price data...")
    try:
        price_response = session.get(price_endpoint, params=price_params, headers=price_headers, timeout=15)
        price_response.raise_for_status()
        price_data = price_response.json()
        current_price = price_data['priceData']['displayPrice']['onlinePrice']
    except Exception as e:
        print(f"[{item_number}] Failed to fetch price: {e}")
        return None

    # --- 2. FETCH INVENTORY ---
    inventory_endpoint = f'https://ecom-api.costco.com/ebusiness/inventory/v1/inventorylevels/availability/v2/{item_number}' 
    
    inventory_headers = {
        'Accept': '*/*',
        'Connection': 'keep-alive',
        'Origin': 'https://www.costco.ca',
        'Referer': 'https://www.costco.ca/',
        'client-identifier': '481b1aec-aa3b-454b-b81b-48187e28f205',
        'costco.env': 'ECOM',
        'costco.service': 'restInventory',
    }
    inventory_params = {
        'destinationState': 'BC',
        'destinationPostalCode': 'V3E 0T2',
        'destinationCountryCode': 'CA',
        'orderItemId': '0',
        'shippingCodes': 'USG',
        'action': 'EDD',
        'quantity': '1',
    }
    
    print(f"[{item_number}] Requesting inventory data...")
    try:
        inv_response = session.get(inventory_endpoint, params=inventory_params, headers=inventory_headers, timeout=15)
        inv_response.raise_for_status()
        inv_data = inv_response.json()
        
        raw_availability = inv_data.get('availability', 'Unknown')
        
        # Normalize Costco's 'true' flag to a clean string
        if raw_availability is True or str(raw_availability).lower() == 'true':
            current_availability = "INSTOCK"
        else:
            current_availability = str(raw_availability).upper()

    except Exception as e:
        print(f"[{item_number}] Failed to fetch inventory: {e}")
        current_availability = "ERROR"

    return {
        "title": item_config['title'],
        "url": item_config['url'],
        "price": current_price,
        "availability": current_availability,
    }

def send_batched_email(batched_data):
    """Sends a multipart email with HTML formatting for status colors."""
    msg = EmailMessage()
    msg['Subject'] = "Costco Tracker: Product Updates Detected"
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = TO_EMAIL

    # 1. Build Plain Text Fallback
    plain_body = "The following updates were detected:\n\n"
    
    # 2. Build HTML Body
    html_body = """
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2>Costco Tracking Updates</h2>
        <hr>
    """

    for item in batched_data:
        # Plain text append
        plain_body += f"Item: {item['title']}\n"
        for c in item['changes']:
            plain_body += f"- {c}\n"
        plain_body += f"Current Price: ${item['price']}\n"
        plain_body += f"Status: {item['availability']}\n"
        plain_body += f"Link: {item['url']}\n"
        plain_body += "-" * 40 + "\n"

        # HTML append
        color = "green" if item['availability'] == "INSTOCK" else "red"
        
        html_body += f"<h3><a href='{item['url']}' style='color: #0056b3; text-decoration: none;'>{item['title']}</a></h3>"
        html_body += "<ul>"
        for c in item['changes']:
            html_body += f"<li>{c}</li>"
        html_body += f"<li><strong>Current Price:</strong> ${item['price']}</li>"
        html_body += f"<li><strong>Status:</strong> <span style='color: {color}; font-weight: bold;'>{item['availability']}</span></li>"
        html_body += "</ul><hr>"

    html_body += "</body></html>"

    # Attach both versions (email clients will prefer the HTML version)
    msg.set_content(plain_body)
    msg.add_alternative(html_body, subtype='html')

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
        print("Batched HTML email alert sent successfully.")
    except Exception as e:
        print(f"Failed to send email: {e}. Check credentials.")

def main():
    if not os.path.exists(CONTROL_FILE):
        print(f"Control file {CONTROL_FILE} not found. Exiting.")
        return
        
    with open(CONTROL_FILE, 'r') as f:
        items_to_track = json.load(f)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8,zh-TW;q=0.7,zh;q=0.6",
        "Accept-Encoding": "gzip, deflate, br"
    })

    print("Pinging https://www.costco.ca/ for initial session cookies...")
    try:
        homepage_response = session.get("https://www.costco.ca/", timeout=15)
        homepage_response.raise_for_status()
    except Exception as e:
        print(f"Handshake failed: {e}. Aborting pipeline.")
        return

    previous_state = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            previous_state = json.load(f)

    current_state = {}
    batched_updates = []

    for item in items_to_track:
        item_number = item['item_number']
        live_data = fetch_costco_data(session, item)
        
        if not live_data:
            print(f"Skipping {item_number} due to extraction error.")
            if item_number in previous_state:
                current_state[item_number] = previous_state[item_number]
            continue
            
        print(f"Live Data [{item['title']}] -> Price: ${live_data['price']} | Stock: {live_data['availability']}")
        current_state[item_number] = live_data
        
        item_history = previous_state.get(item_number)
        item_changes = []
        
        # Determine if a state change occurred
        if item_history:
            if live_data['price'] != item_history.get('price'):
                item_changes.append(f"Price changed: ${item_history.get('price')} -> ${live_data['price']}")
            
            if live_data['availability'] != item_history.get('availability'):
                item_changes.append(f"Availability changed: {item_history.get('availability')} -> {live_data['availability']}")
        else:
            item_changes.append("Initial tracking run. Establishing baseline.")

        # If data changed, log it to the CSV history and queue the email
        if item_changes:
            # 1. Log to the historical CSV
            log_to_csv(item_number, item['title'], live_data['price'], live_data['availability'])
            
            # 2. Package the data for the HTML email builder
            live_data['changes'] = item_changes
            batched_updates.append(live_data)

    if batched_updates:
        print("Changes detected! Triggering batched notification pipeline...")
        if EMAIL_ADDRESS and EMAIL_PASSWORD:
            send_batched_email(batched_updates)
        else:
            print("Skipping email alert: Credentials missing.")
    else:
        print("No changes detected across any items.")
        
    # Write the new state file
    with open(STATE_FILE, 'w') as f:
        json.dump(current_state, f, indent=4)
    print("State file updated.")

if __name__ == "__main__":
    main()
