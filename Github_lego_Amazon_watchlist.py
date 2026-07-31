#!/usr/bin/env python
# coding: utf-8

import time
import random
import re
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from curl_cffi import requests

def extract_price(text):
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
            if len(parts) == 2:
                watchlist.append({"lego_number": parts[0].strip(), "asin": parts[1].strip()})
    return watchlist

def format_price(price):
    return f"${price:.2f}" if price is not None else "N/A"

def send_email_report(deals):
    sender_email = os.getenv("GMAIL_ADDRESS")
    sender_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient_email = os.getenv("RECIPIENT_EMAIL")

    if not sender_email or not sender_password or not recipient_email:
        print("\n⚠️ Missing email credentials. Skipping email delivery.")
        return

    if not deals:
        return

    print(f"\n📧 Formatting Watchlist Report for {len(deals)} items...")

    html = """
    <html>
    <head>
    <style>
      table { border-collapse: collapse; width: 100%; font-family: Arial, sans-serif; }
      th, td { text-align: left; padding: 8px; border: 1px solid #ddd; }
      th { background-color: #f2f2f2; color: #333; }
      tr:nth-child(even) {background-color: #f9f9f9;}
      a { color: #0066c0; text-decoration: none; font-weight: bold; }
    </style>
    </head>
    <body>
    <h2>Daily LEGO Watchlist Report</h2>
    <table>
      <tr>
        <th>Lego Name</th>
        <th>Number</th>
        <th>Original</th>
        <th>Current</th>
        <th>Discount</th>
        <th>Amazon Link</th>
      </tr>
    """
    
    for deal in deals:
        discount_style = 'style="color: green; font-weight: bold;"' if deal['discount'] > 0 else ''
        html += f"""
      <tr>
        <td>{deal['title']}</td>
        <td>{deal['lego_number']}</td>
        <td>{format_price(deal['original_price'])}</td>
        <td>{format_price(deal['current_price'])}</td>
        <td {discount_style}>{deal['discount']}%</td>
        <td><a href="{deal['link']}">View Deal</a></td>
      </tr>
        """
    html += "</table></body></html>"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"LEGO Watchlist Report - Checked {len(deals)} Sets"
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

def scrape_direct_asin(session, lego_number, asin, amazon_tag=""):
    url = f"https://www.amazon.ca/dp/{asin}"
    affiliate_url = f"{url}?tag={amazon_tag}" if amazon_tag else url
    
    result_deal = {
        "title": "Not Found / Out of Stock",
        "lego_number": lego_number,
        "current_price": None,
        "original_price": None,
        "discount": 0.0,
        "link": affiliate_url
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = session.get(url, timeout=10)
            
            if response.status_code == 503 or "captcha" in response.url.lower():
                print(f"  ⚠️ WAF Block on {lego_number} (Attempt {attempt+1}). Retrying...")
                time.sleep(random.uniform(3, 7))
                continue
                
            soup = BeautifulSoup(response.content, "lxml")
            
            # Extract Title
            title_tag = soup.find(id="productTitle")
            if title_tag:
                title = title_tag.get_text(strip=True)
                if " - " in title:
                    title = title.split(" - ")[0].strip()
                result_deal["title"] = title

            # Extract Current Price (Buy Box)
            price_core = soup.find("span", class_="a-price aok-align-center priceToPay")
            if not price_core:
                price_core = soup.find("span", class_="a-price apexPriceToPay") # Alternative format
            
            if price_core:
                offscreen = price_core.find("span", class_="a-offscreen")
                if offscreen:
                    result_deal["current_price"] = extract_price(offscreen.get_text(strip=True))

            # Extract Original/List Price
            basis_price_block = soup.find("span", class_="basisPrice")
            if basis_price_block:
                offscreen = basis_price_block.find("span", class_="a-offscreen")
                if offscreen:
                    result_deal["original_price"] = extract_price(offscreen.get_text(strip=True))
            
            # Fallback for original price if basis isn't present
            if result_deal["current_price"] and not result_deal["original_price"]:
                result_deal["original_price"] = result_deal["current_price"]

            # Calculate Discount
            if result_deal["current_price"] and result_deal["original_price"] and result_deal["original_price"] > result_deal["current_price"]:
                result_deal["discount"] = round(((result_deal["original_price"] - result_deal["current_price"]) / result_deal["original_price"]) * 100, 1)

            print(f"✅ Found {lego_number}: {result_deal['title'][:40]}... | Discount: {result_deal['discount']}%")
            break # Success, break out of retry loop

        except Exception as e:
            print(f"  ⚠️ Request failed for {lego_number}: {e}")
            time.sleep(random.uniform(2, 5))

    return result_deal

def main():
    print("🔎 Amazon LEGO ASIN Direct Scraper (Fast Edition)")
    
    amazon_tag = os.getenv('AMAZON_TAG', '')
    watchlist = load_watchlist()
    master_watchlist_deals = []
    
    if not watchlist:
        return

    # Using curl_cffi to bypass basic WAF
    session = requests.Session(impersonate="chrome116")
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
    })

    print("🍪 Warming up session...")
    try:
        session.get("https://www.amazon.ca", timeout=10)
        time.sleep(2)
    except:
        pass
    
    for item in watchlist:
        print(f"\n🚀 Checking Watchlist: LEGO {item['lego_number']} (ASIN: {item['asin']})")
        deal = scrape_direct_asin(session, item["lego_number"], item["asin"], amazon_tag)
        master_watchlist_deals.append(deal)
        
        # Short human-like delay between instant page loads
        time.sleep(random.uniform(1.5, 3.5))

    if master_watchlist_deals:
        master_watchlist_deals.sort(key=lambda x: x["discount"], reverse=True)
    
    send_email_report(master_watchlist_deals)

if __name__ == "__main__":
    main()
