import os
import json
import smtplib
import requests
from bs4 import BeautifulSoup
from email.message import EmailMessage

# GitHub Secrets for the Action
COSTCO_URL = os.environ.get("COSTCO_URL", "https://www.costco.ca/p/-/apple-mac-mini-m4-chip-16-gb-ram-256-gb-ssd/4000244498?langId=-24")
EMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
EMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
TO_EMAIL = os.environ.get("RECIPIENT_EMAIL")
STATE_FILE = "state.json"

def fetch_costco_data():
    session = requests.Session()
    
    # 1. Establish base headers for the entire session
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8,zh-TW;q=0.7,zh;q=0.6",
        "Accept-Encoding": "gzip, deflate, br"
    })

    homepage_url = "https://www.costco.ca/"
    
    # --- 1. THE HANDSHAKE ---
    print(f"Pinging {homepage_url} for initial cookies...")
    try:
        homepage_response = session.get(homepage_url, timeout=15)
        homepage_response.raise_for_status()
    except Exception as e:
        print(f"Handshake failed: {e}")
        return None

    # --- 2. FETCH PRICE (Your working code) ---
    price_endpoint = 'https://gdx-api.costco.com/catalog/product/dispprice-api/v2/display-price'
    price_headers = {
        'Accept': '*/*',
        'Connection': 'keep-alive',
        'Origin': 'https://www.costco.ca',
        'Referer': 'https://www.costco.ca/',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'cross-site',
        'client-identifier': '6b262714-2ed4-4dcb-a39d-39a4b0357309',
        'sec-ch-ua': '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
    }
    price_params = {
        'whsNumber': '894',
        'clientId': 'e442e6e6-2602-4a39-937b-8b28b4457ed3',
        'item': '5350093',
        'country': 'CA',
        'locale': 'en-ca',
        'state': 'BC',
        'zipCode': 'V3E 0T2',
    }
    
    print(f"Requesting price data...")
    try:
        price_response = session.get(price_endpoint, params=price_params, headers=price_headers, timeout=15)
        price_response.raise_for_status()
        price_data = price_response.json()
        current_price = price_data['priceData']['displayPrice']['onlinePrice']
    except Exception as e:
        print(f"Failed to fetch price: {e}")
        return None

    # --- 3. FETCH INVENTORY (To be completed) ---
    # TODO: Paste the URL from your cURL conversion here
    inventory_endpoint = 'https://ecom-api.costco.com/ebusiness/inventory/v1/inventorylevels/availability/v2/5350093' 
    
    # TODO: Paste the headers and params dictionary from your cURL conversion here
    inventory_headers = {
        'Accept': '*/*',
        'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8,zh-TW;q=0.7,zh;q=0.6',
        'Connection': 'keep-alive',
        'Origin': 'https://www.costco.ca',
        'Referer': 'https://www.costco.ca/',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'cross-site',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
        'client-identifier': '481b1aec-aa3b-454b-b81b-48187e28f205',
        'costco.env': 'ECOM',
        'costco.service': 'restInventory',
        'sec-ch-ua': '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
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
    
    print(f"Requesting inventory data...")
    try:
        inv_response = session.get(inventory_endpoint, params=inventory_params, headers=inventory_headers, timeout=15)
        inv_response.raise_for_status()
        inv_data = inv_response.json()
        print("Inventory JSON payload:", inv_data) 
        
        # TODO: Update this extraction path based on the structure printed in your terminal
        current_availability = inv_data.get('status', 'Unknown') 
    except Exception as e:
        print(f"Failed to fetch inventory: {e}")
        current_availability = "Error checking stock"

    # --- 4. RETURN COMBINED DATA ---
    return {
        "title": "Costco Item 5350093",
        "price": current_price,
        "availability": current_availability,
    }

def send_email_alert(data, changes):
    msg = EmailMessage()
    msg['Subject'] = f"Costco Update: {data['title']}"
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = TO_EMAIL

    body = f"Updates detected for {data['title']}:\n\n"
    for change in changes:
        body += f"- {change}\n"
    
    body += f"\nCurrent Price: ${data['price']}\n"
    body += f"Status: {data['availability']}\n"
    body += f"Link: {COSTCO_URL}"

    msg.set_content(body)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
        print("Email alert sent successfully.")
    except Exception as e:
        print(f"Failed to send email: {e}. Check credentials.")

def main():
    live_data = fetch_costco_data()
    if not live_data:
        print("Pipeline aborted due to extraction failure.")
        return

    print(f"Live Data -> Price: ${live_data['price']} | Stock: {live_data['availability']}")

    # Load previous state from file
    previous_state = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            previous_state = json.load(f)

    changes = []
    
    # Compare current data against historical state
    if previous_state:
        if live_data['price'] != previous_state.get('price'):
            changes.append(f"Price changed: ${previous_state.get('price')} -> ${live_data['price']}")
        
        if live_data['availability'] != previous_state.get('availability'):
            changes.append(f"Availability changed: {previous_state.get('availability')} -> {live_data['availability']}")
    else:
        changes.append("Initial tracking run. Establishing baseline.")

    # Alert and Save State if modified
    if changes:
        print("Changes detected! Triggering notification pipeline...")
        if EMAIL_ADDRESS and EMAIL_PASSWORD:
            send_email_alert(live_data, changes)
        else:
            print("Skipping email alert: Credentials missing in environment variables.")
        
        with open(STATE_FILE, 'w') as f:
            json.dump(live_data, f, indent=4)
        print("State file updated for GitHub Actions commit.")
    else:
        print("No changes detected. Skipping alert.")

if __name__ == "__main__":
    main()
