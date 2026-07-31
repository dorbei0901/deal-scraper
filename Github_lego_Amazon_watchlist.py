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

def load_lego_watchlist(filename="legowatchlist.txt"):
    if not os.path.exists(filename):
        print(f"⚠️ {filename} not found. Please create it with one LEGO number per line.")
        return [] 
    with open(filename, "r", encoding="utf-8") as file:
        numbers = [line.strip() for line in file if line.strip()]
    
    print(f"📁 Loaded {len(numbers)} LEGO numbers from {filename}")
    return numbers

def format_price(price):
    return f"${price:.2f}" if price is not None else "N/A"

def build_search_url(lego_number: str) -> str:
    base_url = "https://www.amazon.ca/s"
    # p_89%3ALEGO = Brand: LEGO (Removed the p_6 Amazon-only seller filter to allow 3rd party stock)
    query = f"k=lego+{lego_number}&rh=p_89%3ALEGO"
    return f"{base_url}?{query}"

def send_email_report(deals):
    sender_email = os.getenv("GMAIL_ADDRESS")
    sender_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient_email = os.getenv("RECIPIENT_EMAIL")

    if not sender_email or not sender_password or not recipient_email:
        print("\n⚠️ Missing email credentials. Skipping email delivery.")
        return

    if not deals:
        print("\n📭 Watchlist is empty or no deals found, no email to send.")
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
        <th>Seller Type</th>
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
        <td>{deal['seller']}</td>
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

def scrape_lego_search(session, lego_number, amazon_tag=""):
    url = build_search_url(lego_number)
    
    result_deal = {
        "title": "Not Found",
        "lego_number": lego_number,
        "current_price": None,
        "original_price": None,
        "discount": 0.0,
        "seller": "N/A",
        "link": url
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = session.get(url, timeout=15)
            soup = BeautifulSoup(response.content, "lxml")
            
            page_title = soup.title.text.strip() if soup.title else ""
            if page_title == "Amazon.ca" or "captcha" in response.url.lower():
                print(f"  ⚠️ Soft CAPTCHA triggered (Attempt {attempt+1}/{max_retries}). Retrying...")
                time.sleep(random.uniform(5.0, 10.0))
                continue
                
            products = soup.find_all("div", {"data-component-type": "s-search-result"})
            
            if not products:
                # DEBUG DUMP: If no products are found but no obvious CAPTCHA, save the HTML
                debug_file = f"debug_lego_{lego_number}.html"
                with open(debug_file, "w", encoding="utf-8") as f:
                    f.write(response.text)
                print(f"  ⚠️ No products found in DOM on attempt {attempt+1}. Saved HTML to {debug_file} for inspection.")
                time.sleep(random.uniform(3.0, 6.0))
                continue
                
            item_found = False
            for item in products[:5]: 
                title_tag = item.find("h2")
                if not title_tag: continue
                
                title_text = title_tag.get_text(strip=True)
                
                if lego_number in title_text:
                    if " - " in title_text:
                        title_text = title_text.split(" - ")[0].strip()
                    result_deal["title"] = title_text
                    result_deal["seller"] = "Amazon or 3rd Party" 
                    
                    link_tag = item.find("a", class_="a-link-normal s-line-clamp-4 s-link-style a-text-normal")
                    if not link_tag:
                        link_tag = item.find("a", class_="a-link-normal")
                        
                    if link_tag:
                        raw_link = link_tag.get("href", "")
                        full_link = f"https://www.amazon.ca{raw_link}" if raw_link.startswith("/") else raw_link
                        
                        if amazon_tag and "slredirect" not in full_link:
                            separator = "&" if "?" in full_link else "?"
                            result_deal["link"] = f"{full_link}{separator}tag={amazon_tag}"
                        else:
                            result_deal["link"] = full_link

                    current_price_span = item.find("span", class_="a-price")
                    if current_price_span:
                        offscreen = current_price_span.find("span", class_="a-offscreen")
                        if offscreen:
                            result_deal["current_price"] = extract_price(offscreen.get_text(strip=True))

                    original_price_span = item.find("span", class_="a-text-price")
                    if original_price_span:
                        offscreen = original_price_span.find("span", class_="a-offscreen")
                        if offscreen:
                            result_deal["original_price"] = extract_price(offscreen.get_text(strip=True))
                    elif item.find('span', {'data-a-strike': 'true'}):
                        strike_tag = item.find('span', {'data-a-strike': 'true'})
                        offscreen = strike_tag.find('span', class_='a-offscreen')
                        if offscreen:
                            result_deal["original_price"] = extract_price(offscreen.get_text(strip=True))
                        else:
                            result_deal["original_price"] = extract_price(strike_tag.get_text(strip=True))

                    if result_deal["current_price"] is not None and result_deal["original_price"] is None:
                        result_deal["original_price"] = result_deal["current_price"]

                    if result_deal["current_price"] and result_deal["original_price"] and result_deal["original_price"] > result_deal["current_price"]:
                        result_deal["discount"] = round(((result_deal["original_price"] - result_deal["current_price"]) / result_deal["original_price"]) * 100, 1)

                    print(f"✅ Found {lego_number}: {result_deal['title'][:40]}... | Discount: {result_deal['discount']}%")
                    item_found = True
                    break 
            
            if item_found:
                break 

        except Exception as e:
            print(f"  ⚠️ Request failed for {lego_number}: {e}")
            time.sleep(random.uniform(4.0, 8.0))

    if result_deal["current_price"] is None:
        print(f"❌ Could not extract price for {lego_number}. (Check debug_lego_{lego_number}.html)")

    return result_deal

def main():
    print("🔎 Amazon LEGO Search Scraper (Fast curl-cffi Edition v5 - Debug Mode)")
    
    amazon_tag = os.getenv('AMAZON_TAG', '')
    watchlist = load_lego_watchlist()
    master_watchlist_deals = []
    
    if not watchlist:
        return

    browser_options = ["chrome116", "chrome120", "edge116"]
    impersonate_choice = random.choice(browser_options)
    
    session = requests.Session(impersonate=impersonate_choice)
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1"
    })

    print(f"🍪 Warming up session (Impersonating {impersonate_choice})...")
    try:
        session.get("https://www.amazon.ca", timeout=15)
        time.sleep(random.uniform(2.0, 4.5))
    except:
        pass
    
    for number in watchlist:
        print(f"\n🚀 Checking Watchlist: LEGO {number}")
        
        session.headers.update({"Referer": "https://www.amazon.ca/"})
        deal = scrape_lego_search(session, number, amazon_tag)
        master_watchlist_deals.append(deal)
        
        time.sleep(random.uniform(3.5, 6.5))

    if master_watchlist_deals:
        # Only email items where we actually found a price
        valid_deals = [d for d in master_watchlist_deals if d["current_price"] is not None]
        valid_deals.sort(key=lambda x: x["discount"], reverse=True)
        send_email_report(valid_deals)
    else:
        print("\n📭 No valid data extracted today.")

if __name__ == "__main__":
    main()
