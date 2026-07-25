import os
import json
import smtplib
import requests
from email.message import EmailMessage

# GitHub Secrets
EMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
EMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
TO_EMAIL = os.environ.get("RECIPIENT_EMAIL")

STATE_FILE = "state.json"
CONTROL_FILE = "costco_items.json"

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
        'zipCode': 'V3E 0T2', # Retained your Coquitlam parameter
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
    # Injected the item_number dynamically into the URL string
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
        
        # Extracted the specific 'availability' key you found in the logs
        current_availability = inv_data.get('availability', 'Unknown') 
    except Exception as e:
        print(f"[{item_number}] Failed to fetch inventory: {e}")
        current_availability = "Error checking stock"

    return {
        "title": item_config['title'],
        "url": item_config['url'],
        "price": current_price,
        "availability": current_availability,
    }

def send_batched_email(batched_changes):
    msg = EmailMessage()
    msg['Subject'] = "Costco Tracker: Product Updates Detected"
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = TO_EMAIL

    body = "The following updates were detected in your tracking list:\n\n"
    for change in batched_changes:
        body += f"{change}\n"
        body += "-" * 40 + "\n"

    msg.set_content(body)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
        print("Batched email alert sent successfully.")
    except Exception as e:
        print(f"Failed to send email: {e}. Check credentials.")

def main():
    # 1. Load the control file
    if not os.path.exists(CONTROL_FILE):
        print(f"Control file {CONTROL_FILE} not found. Exiting.")
        return
        
    with open(CONTROL_FILE, 'r') as f:
        items_to_track = json.load(f)

    # 2. Establish the session and perform the handshake ONCE
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

    # 3. Load previous state
    previous_state = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            previous_state = json.load(f)

    current_state = {}
    batched_alert_messages = []

    # 4. Iterate through the control file
    for item in items_to_track:
        item_number = item['item_number']
        live_data = fetch_costco_data(session, item)
        
        if not live_data:
            print(f"Skipping {item_number} due to extraction error.")
            # Retain old state if extraction fails so we don't trigger false alerts next run
            if item_number in previous_state:
                current_state[item_number] = previous_state[item_number]
            continue
            
        print(f"Live Data [{item['title']}] -> Price: ${live_data['price']} | Stock: {live_data['availability']}")
        
        # Save to current state dictionary
        current_state[item_number] = live_data
        
        # Compare against history
        item_history = previous_state.get(item_number)
        item_changes = []
        
        if item_history:
            if live_data['price'] != item_history.get('price'):
                item_changes.append(f"Price: ${item_history.get('price')} -> ${live_data['price']}")
            
            if live_data['availability'] != item_history.get('availability'):
                item_changes.append(f"Availability: {item_history.get('availability')} -> {live_data['availability']}")
        else:
            item_changes.append("New item added to tracking.")

        # If this specific item changed, format a block for the batched email
        if item_changes:
            alert_block = f"Item: {live_data['title']}\n"
            for c in item_changes:
                alert_block += f"- {c}\n"
            alert_block += f"Current Price: ${live_data['price']}\n"
            alert_block += f"Current Status: {live_data['availability']}\n"
            alert_block += f"Link: {live_data['url']}"
            batched_alert_messages.append(alert_block)

    # 5. Alert and Save State
    if batched_alert_messages:
        print("Changes detected! Triggering batched notification pipeline...")
        if EMAIL_ADDRESS and EMAIL_PASSWORD:
            send_batched_email(batched_alert_messages)
        else:
            print("Skipping email alert: Credentials missing.")
    else:
        print("No changes detected across any items.")
        
    # Always write the new state file
    with open(STATE_FILE, 'w') as f:
        json.dump(current_state, f, indent=4)
    print("State file updated for GitHub Actions commit.")

if __name__ == "__main__":
    main()
