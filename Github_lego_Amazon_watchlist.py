#!/usr/bin/env python
# coding: utf-8

import time
import random
import re
import os
import smtplib
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from curl_cffi import requests

def extract_price(text):
    """Extracts a float price from a text string, handling commas and currency symbols."""
    clean_text = text.replace('CDN$', '').replace('$', '').replace(',', '').strip()
    match = re.search(r'(\d+\.?\d*)', clean_text)
    return float(match.group(1)) if match else None

def load_watchlist(filename="legowatchlist.csv"):
    """Reads a CSV file containing LegoNumber,ASIN."""
    watchlist = []
    if not os.path.exists(filename):
        print(f"⚠️ {filename} not found. Please create it with format: LegoNumber,ASIN")
        return watchlist 
        
    with open(filename, "r", encoding="utf-8") as file:
        for line in file:
            parts = line.strip().split(',')
            if len(parts) >= 2:
                watchlist.append({"lego_number": parts[0].strip(), "asin": parts[1].strip()})
    return watchlist

def send_email_report(deals):
    """Generates an HTML table and sends it via email securely."""
    sender_email = os.getenv("GMAIL_ADDRESS")
    sender_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient_email = os.getenv("RECIPIENT_EMAIL")

    if not sender_email or not sender_password or not recipient_email:
        print("\n⚠️ Missing email credentials. Skipping email delivery.")
        return

    if not deals:
        print("\n📭 No deals or changes found today to email.")
        return

    print(f"\n📧 Formatting {len(deals)} items into an email report for {recipient_email}...")

    html = """
    <html>
    <head>
    <style>
      table { border-collapse: collapse; width: 100%; font-family: Arial, sans-serif; }
      th, td { text-align: left; padding: 8px; border: 1px solid #ddd; }
      th { background-color: #f2f2f2; color: #333; }
      a { color: #0066c0; text-decoration: none; font-weight: bold; }
      a:hover { text-decoration: underline; }
    </style>
    </head>
    <body>
    <h2>Daily LEGO Watchlist Report (via CCC)</h2>
    <table>
      <tr>
        <th>Product Name</th>
        <th>Number</th>
        <th>Current</th>
        <th>Highest (List)</th>
        <th>Discount</th>
        <th>Status Change</th>
        <th>Amazon Link</th>
      </tr>
    """
    
    for deal in deals:
        status = deal.get("status_change", "")
        row_style = ""
        
        if status == "New":
            row_style = ' style="background-color: #d4edda;"' # Light Green
        elif status == "Removed":
            row_style = ' style="background-color: #e2e3e5; color: #6c757d;"' # Light Grey
        elif status == "Price Changed":
            row_style = ' style="background-color: #fff3cd;"' # Light Yellow

        html += f"""
      <tr{row_style}>
        <td>{deal.get('title', 'N/A')}</td>
        <td>{deal.get('lego_number', 'N/A')}</td>
        <td>${deal.get('current_price', 0):.2f}</td>
        <td>${deal.get('original_price', 0):.2f}</td>
        <td style="color: red; font-weight: bold;">{deal.get('discount', 0)}%</td>
        <td style="font-weight: bold;">{status}</td>
        <td><a href="{deal.get('link', '#')}">View on Amazon</a></td>
      </tr>
        """
        
    html += """
    </table>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"LEGO Watchlist Update - {len(deals)} Items Tracked"
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg.attach(MIMEText(html, "html"))

    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipient_email, msg.as_string())
        server.quit()
        print(f"✅ Email successfully sent to {recipient_email}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

def scrape_camelcamelcamel(session, lego_number, asin, amazon_tag=""):
    # Target the Canadian CCC site
    url = f"https://ca.camelcamelcamel.com/product/{asin}"
    # But route the final email link directly to Amazon.ca
    affiliate_url = f"https://www.amazon.ca/dp/{asin}?tag={amazon_tag}" if amazon_tag else f"https://www.amazon.ca/dp/{asin}"
    
    print(f"🔍 Scraping CCC for Watchlist Item {lego_number} (ASIN: {asin})")
    
    max_retries = 3
    found_deal = None
    
    for attempt in range(max_retries):
        try:
            response = session.get(url, timeout=15)
            
            # CCC uses Cloudflare. If we hit a block, wait and retry.
            if response.status_code in [403, 503]:
                print(f"⚠️ Cloudflare Block triggered on attempt {attempt + 1}. Waiting...")
                time.sleep(random.uniform(5, 12)) 
                continue

            # Using Python's native parser to avoid 'lxml' missing errors
            soup = BeautifulSoup(response.content, "html.parser")
            
            title_tag = soup.find("title")
            if not title_tag:
                print(f"⚠️ Title not found on attempt {attempt + 1}. Retrying...")
                time.sleep(random.uniform(4, 7))
                continue
                
            # Clean up the CCC title string
            title = title_tag.get_text(strip=True).split(" | ")[0].replace("Amazon.ca Price Tracker", "").strip()

            current_price = None
            original_price = None
            discount = 0.0

            # Find the pricing table row for "Amazon"
            amazon_row = soup.find(lambda tag: tag.name == 'tr' and 'Amazon' in tag.get_text())
            
            if amazon_row:
                # Find all dollar amounts in that row
                prices = amazon_row.find_all(string=re.compile(r'\$\d+\.\d+'))
                if prices:
                    current_price = extract_price(prices[0])
                if len(prices) >= 2:
                    original_price = extract_price(prices[1]) # CCC tracks "Highest" which acts as MSRP
                    
            # Fallback to "3rd Party New" if Amazon native stock isn't found
            if not current_price:
                third_party_row = soup.find(lambda tag: tag.name == 'tr' and '3rd Party New' in tag.get_text())
                if third_party_row:
                    prices = third_party_row.find_all(string=re.compile(r'\$\d+\.\d+'))
                    if prices:
                        current_price = extract_price(prices[0])
                        if len(prices) >= 2:
                            original_price = extract_price(prices[1])

            if current_price is not None and original_price is None:
                original_price = current_price

            if current_price is not None and original_price is not None and original_price > current_price:
                discount = round(((original_price - current_price) / original_price) * 100, 1)

            if current_price is not None:
                found_deal = {
                    "title": title,
                    "lego_number": lego_number,
                    "current_price": current_price,
                    "original_price": original_price,
                    "discount": discount,
                    "link": affiliate_url, # Link routes to Amazon for easy purchasing
                    "asin": asin
                }
                print(f"✅ Found {lego_number} on CCC: {title[:35]}... | Price: ${current_price:.2f}")
                break
            else:
                print(f"⚠️ No price found for {lego_number} on attempt {attempt + 1}.")

        except Exception as e:
            print(f"An error occurred on attempt {attempt + 1}: {e}")
            time.sleep(random.uniform(4, 8))

    if not found_deal:
        print(f"❌ Item {lego_number} could not be extracted from CCC.")
        
    return found_deal

def main():
    print("🔎 Amazon LEGO Watchlist (CamelCamelCamel Exploit Edition)")
    
    amazon_tag = os.getenv('AMAZON_TAG', '')
    watchlist = load_watchlist()
    master_deal_list = []
    
    # We use chrome116 to bypass CCC's Cloudflare protection smoothly
    session = requests.Session(impersonate="chrome116")
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
        "Referer": "https://ca.camelcamelcamel.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Upgrade-Insecure-Requests": "1"
    })

    print("🍪 Warming up session with CamelCamelCamel homepage...")
    try:
        session.get("https://ca.camelcamelcamel.com/", timeout=15)
        time.sleep(random.uniform(2, 5))
    except Exception as e:
        print(f"⚠️ Homepage warmup failed: {e}")
    
    for item in watchlist:
        deal = scrape_camelcamelcamel(session=session, lego_number=item["lego_number"], asin=item["asin"], amazon_tag=amazon_tag)
        if deal:
            master_deal_list.append(deal)
            
        time.sleep(random.uniform(4.0, 7.5)) 

    unique_deals = {}
    for deal in master_deal_list:
        asin = deal["asin"]
        if asin not in unique_deals:
            unique_deals[asin] = deal
            
    STATE_FILE = "state_amazon_watchlist.json"
    old_state = {}
    
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                old_state = json.load(f)
        except json.JSONDecodeError:
            pass

    final_email_deals = []
    new_state = {}

    for asin, deal in unique_deals.items():
        if asin not in old_state:
            deal["status_change"] = "New"
        else:
            old_deal = old_state[asin]
            if deal["current_price"] != old_deal["current_price"]:
                deal["status_change"] = "Price Changed"
            else:
                deal["status_change"] = "" 
        
        final_email_deals.append(deal)
        
        new_state[asin] = {
            "title": deal["title"],
            "lego_number": deal["lego_number"],
            "current_price": deal["current_price"],
            "original_price": deal["original_price"],
            "discount": deal["discount"],
            "link": deal["link"]
        }

    for asin, old_deal in old_state.items():
        if asin not in unique_deals:
            old_deal["status_change"] = "Removed"
            final_email_deals.append(old_deal)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(new_state, f, indent=4)

    if final_email_deals:
        final_email_deals.sort(
            key=lambda x: (x.get("status_change") != "Removed", x.get("discount", 0)), 
            reverse=True
        )
    
    send_email_report(final_email_deals)

if __name__ == "__main__":
    main()
