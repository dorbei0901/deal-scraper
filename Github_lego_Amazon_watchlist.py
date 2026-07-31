#!/usr/bin/env python
# coding: utf-8

import time
import random
import re
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import subprocess

def get_chrome_major_version():
    """Dynamically finds the major version of Chrome installed on the OS."""
    try:
        process = subprocess.Popen(['google-chrome', '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, _ = process.communicate()
        version_string = stdout.decode('utf-8')
        match = re.search(r'(\d+)\.', version_string)
        if match:
            return int(match.group(1))
    except Exception as e:
        print(f"⚠️ Could not detect Chrome version dynamically: {e}")
    return None
    
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
    
    print(f"📁 Loaded {len(watchlist)} LEGO ASINs from {filename}")
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

def main():
    print("🔎 Amazon LEGO ASIN Scraper (undetected-chromedriver Edition)")
    
    amazon_tag = os.getenv('AMAZON_TAG', '')
    watchlist = load_watchlist()
    master_watchlist_deals = []
    
    if not watchlist:
        return

    options = uc.ChromeOptions()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    chrome_version = get_chrome_major_version()
    
    print("🚀 Initializing browser...")
    if chrome_version:
        driver = uc.Chrome(options=options, version_main=chrome_version)
    else:
        driver = uc.Chrome(options=options)

    try:
        # Warmup
        driver.get("https://www.amazon.ca")
        time.sleep(random.uniform(3.0, 5.0))
        
        for item in watchlist:
            lego_number = item['lego_number']
            asin = item['asin']
            
            print(f"\n🚀 Checking Watchlist: LEGO {lego_number} (ASIN: {asin})")
            
            url = f"https://www.amazon.ca/dp/{asin}"
            affiliate_url = f"{url}?tag={amazon_tag}" if amazon_tag else url
            
            result_deal = {
                "title": "Not Found / Blocked",
                "lego_number": lego_number,
                "current_price": None,
                "original_price": None,
                "discount": 0.0,
                "link": affiliate_url
            }

            max_retries = 2
            load_successful = False
            
            for attempt in range(max_retries):
                driver.get(url)
                time.sleep(random.uniform(4.0, 6.0))
                
                # Check for bot challenge page
                if "Robot Check" in driver.title or "captcha" in driver.current_url.lower():
                    print(f"  ⚠️ Amazon CAPTCHA triggered (Attempt {attempt+1}). Retrying...")
                    time.sleep(random.uniform(5.0, 10.0))
                    continue
                
                try:
                    # Wait explicitly for the title to ensure page rendered
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.ID, "productTitle"))
                    )
                    load_successful = True
                    break
                except TimeoutException:
                    print(f"  ⚠️ Timeout waiting for product info (Attempt {attempt+1}). Retrying...")
                    time.sleep(random.uniform(3.0, 6.0))
            
            if not load_successful:
                print(f"❌ Failed to load valid product data for {lego_number}")
                master_watchlist_deals.append(result_deal)
                continue

            # Parse DOM with BeautifulSoup
            soup = BeautifulSoup(driver.page_source, "html.parser")
            
            title_tag = soup.find(id="productTitle")
            if title_tag:
                title_text = title_tag.get_text(strip=True)
                if " - " in title_text:
                    title_text = title_text.split(" - ")[0].strip()
                result_deal["title"] = title_text

            price_core = soup.find("span", class_="a-price aok-align-center priceToPay")
            if not price_core:
                price_core = soup.find("span", class_="a-price apexPriceToPay")
            
            if price_core:
                offscreen = price_core.find("span", class_="a-offscreen")
                if offscreen:
                    result_deal["current_price"] = extract_price(offscreen.get_text(strip=True))

            basis_price_block = soup.find("span", class_="basisPrice")
            if basis_price_block:
                offscreen = basis_price_block.find("span", class_="a-offscreen")
                if offscreen:
                    result_deal["original_price"] = extract_price(offscreen.get_text(strip=True))
            
            if result_deal["current_price"] and not result_deal["original_price"]:
                result_deal["original_price"] = result_deal["current_price"]

            if result_deal["current_price"] and result_deal["original_price"] and result_deal["original_price"] > result_deal["current_price"]:
                result_deal["discount"] = round(((result_deal["original_price"] - result_deal["current_price"]) / result_deal["original_price"]) * 100, 1)

            print(f"✅ Found {lego_number}: {result_deal['title'][:40]}... | Discount: {result_deal['discount']}%")
            master_watchlist_deals.append(result_deal)

    finally:
        driver.quit()

    if master_watchlist_deals:
        master_watchlist_deals.sort(key=lambda x: x["discount"], reverse=True)
    
    send_email_report(master_watchlist_deals)

if __name__ == "__main__":
    main()
