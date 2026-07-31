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

def extract_asin(url):
    """Extracts the unique Amazon ASIN from a URL for deduplication."""
    match = re.search(r'/(?:dp|gp/product)/([a-zA-Z0-9]{10})', url)
    return match.group(1) if match else url

def build_search_url(lego_number: str) -> str:
    base_url = "https://www.amazon.ca/s"
    # p_89%3ALEGO = Brand: LEGO
    # p_6%3AA3DWYIK6Y9EEQB = Seller: Amazon.ca (Crucial for bypassing Datacenter WAF blocks)
    merchant_filter = "%2Cp_6%3AA3DWYIK6Y9EEQB"
    
    query = f"k=lego+{lego_number}&rh=p_89%3ALEGO{merchant_filter}"
    return f"{base_url}?{query}"

def load_lego_watchlist(filename="legowatchlist.txt"):
    if not os.path.exists(filename):
        print(f"⚠️ {filename} not found. Please create it.")
        return [] 
    with open(filename, "r", encoding="utf-8") as file:
        numbers = [line.strip() for line in file if line.strip()]
    return numbers

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
    <h2>Daily LEGO Watchlist Report</h2>
    <table>
      <tr>
        <th>Product Name</th>
        <th>Number</th>
        <th>Current</th>
        <th>Original</th>
        <th>Discount</th>
        <th>Seller</th>
        <th>Status Change</th>
        <th>Amazon Link</th>
      </tr>
    """
    
    for deal in deals:
        status = deal.get("status_change", "")
        row_style = ""
        
        # Color coding based on status change from GitHub-Amazon v2
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
        <td>{deal.get('seller', 'Amazon.ca')}</td>
        <td style="font-weight: bold;">{status}</td>
        <td><a href="{deal.get('link', '#')}">View Deal</a></td>
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

def scrape_watchlist_item_curl(session, lego_number, amazon_tag=""):
    url = build_search_url(lego_number)
    print(f"🔍 Scraping Watchlist Item {lego_number}: {url}")
    
    max_retries = 3
    found_deal = None
    
    for attempt in range(max_retries):
        try:
            response = session.get(url, timeout=15)
            
            # WAF Bot Check / Timeout
            if response.status_code == 503 or "captcha" in response.url.lower():
                print(f"⚠️ WAF Block triggered for {lego_number} on attempt {attempt + 1}. Waiting...")
                time.sleep(random.uniform(5, 12)) 
                continue

            soup = BeautifulSoup(response.content, "lxml")
            products = soup.find_all("div", {"data-component-type": "s-search-result"})

            if not products:
                break # No results found, likely OOS from Amazon natively

            for item in products:
                title = "N/A"
                link = "N/A"
                current_price = None
                original_price = None
                discount = 0.0

                link_tag = item.find("a", class_="a-link-normal s-line-clamp-4 s-link-style a-text-normal")
                if link_tag:
                    title_tag = link_tag.find("h2")
                    title = title_tag.get_text(strip=True) if title_tag else "N/A"
                    link = "https://www.amazon.ca" + link_tag.get("href", "N/A")
                else: 
                    title_h2 = item.find("h2")
                    if title_h2:
                        link_tag_fallback = title_h2.find("a", class_="a-link-normal")
                        if link_tag_fallback:
                            title_span = link_tag_fallback.find("span", class_="a-text-normal")
                            title = title_span.get_text(strip=True) if title_span else "N/A"
                            relative_link = link_tag_fallback.get("href", "N/A")
                            link = "https://www.amazon.ca" + relative_link if not relative_link.startswith("http") else relative_link

                # Match logic: Ensure the specific LEGO number is in the title
                if lego_number in title:
                    if " - " in title:
                        title = title.split(" - ")[0].strip()

                    current_price_span = item.find("span", class_="a-price")
                    if current_price_span:
                        offscreen = current_price_span.find("span", class_="a-offscreen")
                        if offscreen:
                            current_price = extract_price(offscreen.get_text(strip=True))

                    original_price_span = item.find("span", class_="a-text-price")
                    if original_price_span:
                        offscreen = original_price_span.find("span", class_="a-offscreen")
                        if offscreen:
                            original_price = extract_price(offscreen.get_text(strip=True))
                    elif item.find('span', {'data-a-strike': 'true'}):
                        strike_tag = item.find('span', {'data-a-strike': 'true'})
                        offscreen = strike_tag.find('span', class_='a-offscreen')
                        if offscreen:
                            original_price = extract_price(offscreen.get_text(strip=True))
                        else:
                             original_price = extract_price(strike_tag.get_text(strip=True))

                    if current_price is not None and original_price is None:
                        original_price = current_price

                    if current_price is not None and original_price is not None and original_price > current_price:
                        discount = round(((original_price - current_price) / original_price) * 100, 1)

                    if title != "N/A" and "slredirect" not in link:
                        if amazon_tag:
                            separator = "&" if "?" in link else "?"
                            final_link = f"{link}{separator}tag={amazon_tag}"
                        else:
                            final_link = link
                            
                        # If we found the item and it has a price, capture it and break
                        if current_price is not None:
                            found_deal = {
                                "title": title,
                                "lego_number": lego_number,
                                "current_price": current_price,
                                "original_price": original_price,
                                "discount": discount,
                                "link": final_link,
                                "raw_link": link,
                                "seller": "Amazon.ca"
                            }
                            print(f"✅ Found {lego_number}: {title[:40]}... | Discount: {discount}%")
                            break
            
            if found_deal:
                break

        except Exception as e:
            print(f"An error occurred on attempt {attempt + 1}: {e}")
            time.sleep(random.uniform(3, 7))

    if not found_deal:
        print(f"❌ Item {lego_number} not found (Likely Out of Stock from Amazon directly).")
        
    return found_deal

def main():
    print("🔎 Amazon LEGO Watchlist (GitHub-Amazon v2 Approach)")
    
    amazon_tag = os.getenv('AMAZON_TAG', '')
    watchlist = load_lego_watchlist()
    master_deal_list = []
    
    # Initialize the session and establish base headers exactly as v2
    browser_options = ["chrome116", "chrome120", "edge116"]
    impersonate_choice = random.choice(browser_options)
    
    session = requests.Session(impersonate=impersonate_choice)
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    })

    print(f"🍪 Warming up session (Impersonating {impersonate_choice}) with Amazon.ca homepage...")
    try:
        session.get("https://www.amazon.ca", timeout=15)
        time.sleep(random.uniform(3, 6))
    except Exception as e:
        print(f"⚠️ Homepage warmup failed: {e}")
    
    for number in watchlist:
        # Update Referer to simulate natural browsing
        session.headers.update({"Referer": "https://www.amazon.ca/"})
        
        deal = scrape_watchlist_item_curl(session=session, lego_number=number, amazon_tag=amazon_tag)
        if deal:
            master_deal_list.append(deal)
            
        time.sleep(random.uniform(4.0, 7.0)) 

    unique_deals = {}
    for deal in master_deal_list:
        asin = extract_asin(deal["raw_link"])
        if asin not in unique_deals:
            unique_deals[asin] = deal
            
    # Apply the exact state tracking logic from GitHub-Amazon v2
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
            "link": deal["link"],
            "seller": deal["seller"]
        }

    for asin, old_deal in old_state.items():
        if asin not in unique_deals:
            old_deal["status_change"] = "Removed"
            final_email_deals.append(old_deal)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(new_state, f, indent=4)

    if final_email_deals:
        # Sort by discount, highest first, pushing Removed to bottom
        final_email_deals.sort(
            key=lambda x: (x.get("status_change") != "Removed", x.get("discount", 0)), 
            reverse=True
        )
    
    send_email_report(final_email_deals)

if __name__ == "__main__":
    main()
