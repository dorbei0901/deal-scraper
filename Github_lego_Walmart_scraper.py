#!/usr/bin/env python
# coding: utf-8

import time
import re
import os
import json
import uuid
import smtplib
import requests
from urllib.parse import urlencode
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from datetime import datetime

def print_time(msg):
    """Helper to print messages with a timestamp so you can track speed."""
    current_time = datetime.now().strftime("%H:%M:%S")
    print(f"[{current_time}] {msg}")

def get_proxied_page(target_url, max_retries=3, session_id=None):
    """Fetches the raw HTML via ScraperAPI."""
    api_key = os.getenv("SCRAPER_API_KEY")
    if not api_key:
        print_time("⚠️ Missing SCRAPER_API_KEY. Exiting.")
        return None

    payload = {
        'api_key': api_key,
        'url': target_url,
        'premium': 'true', 
        'country_code': 'ca'
    }
    
    if session_id:
        payload['session_number'] = session_id
    
    proxy_url = 'https://api.scraperapi.com/?' + urlencode(payload)
    
    for attempt in range(max_retries):
        try:
            response = requests.get(proxy_url, timeout=30) 
            
            if response.status_code == 200:
                page_text = response.text
                if "px-captcha" in page_text or "Press & Hold" in page_text:
                    print_time(f"  ⚠️ Proxy IP hit a Captcha on attempt {attempt + 1}. Requesting new IP...")
                    time.sleep(2)
                    continue
                return page_text
                
            elif response.status_code == 403:
                print_time("  ❌ 403 Forbidden: Your ScraperAPI key is invalid or out of credits.")
                return None
            else:
                print_time(f"  ⚠️ Proxy returned status {response.status_code} on attempt {attempt + 1}. Retrying...")
                time.sleep(2)
                
        except requests.exceptions.Timeout:
            print_time(f"  ⚠️ Proxy timed out on attempt {attempt + 1}. Retrying...")
        except Exception as e:
            print_time(f"  ⚠️ Proxy request failed: {e}")
            time.sleep(2)
            
    return None

def parse_lego_title(raw_title):
    """Extracts the Set Number and cleans the SEO fluff from the title."""
    set_number = "N/A"
    
    match_5 = re.search(r'\b(\d{5})\b', raw_title)
    if match_5:
        set_number = match_5.group(1)
    else:
        numbers = re.findall(r'\b(\d{4})\b', raw_title)
        for num in numbers:
            if not (num.startswith('19') or num.startswith('20')):
                set_number = num
                break

    clean_title = raw_title
    for delimiter in [' - ', ' – ', ', ', ' (']:
        if delimiter in clean_title:
            clean_title = clean_title.split(delimiter)[0]
            
    clean_title = clean_title.strip()
    if len(clean_title) > 50:
        clean_title = clean_title[:47] + "..."
        
    return clean_title, set_number

def load_lego_themes(filename="legoproductTest.txt"):
    if not os.path.exists(filename):
        print_time(f"⚠️ {filename} not found. Defaulting to general LEGO search.")
        return [""] 
    with open(filename, "r", encoding="utf-8") as file:
        themes = [line.strip() for line in file if line.strip()]
    return themes if themes else [""]

def send_email_report(deals):
    sender_email = os.getenv("GMAIL_ADDRESS")
    sender_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient_email = os.getenv("RECIPIENT_EMAIL")

    if not sender_email or not sender_password or not recipient_email:
        print_time("\n⚠️ Missing email credentials. Skipping email delivery.")
        return

    if not deals:
        print_time("\n📭 No deals found today to email.")
        return

    print_time(f"\n📧 Formatting {len(deals)} Walmart deals into an email report...")

    html = """
    <html>
    <head>
    <style>
      table { border-collapse: collapse; width: 100%; font-family: Arial, sans-serif; }
      th, td { text-align: left; padding: 8px; border: 1px solid #ddd; }
      th { background-color: #f2f2f2; color: #0071ce; } 
      tr:nth-child(even) {background-color: #f9f9f9;}
      a { color: #0066c0; text-decoration: none; font-weight: bold; }
    </style>
    </head>
    <body>
    <h2>Daily Walmart LEGO Deals Report</h2>
    <table>
      <tr>
        <th style="color: white;">Product Name</th>
        <th style="color: white;">Set #</th>
        <th style="color: white;">Theme</th>
        <th style="color: white;">Current</th>
        <th style="color: white;">Original</th>
        <th style="color: white;">Discount</th>
        <th style="color: white;">Seller</th>
        <th style="color: white;">Link</th>
      </tr>
    """
    
    for deal in deals:
        html += f"""
      <tr>
        <td>{deal['title']}</td>
        <td style="font-weight: bold; color: #333;">{deal['set_number']}</td>
        <td>{deal['theme'].title() if deal['theme'] else 'General'}</td>
        <td>${deal['current_price']:.2f}</td>
        <td>${deal['original_price']:.2f}</td>
        <td style="color: red; font-weight: bold;">{deal['discount']}%</td>
        <td>{deal.get('seller', 'N/A')}</td>
        <td><a href="{deal['link']}">View Deal</a></td>
      </tr>
        """
        
    html += "</table></body></html>"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Walmart LEGO Deals - {len(deals)} Verified Deals!"
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg.attach(MIMEText(html, "html"))

    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipient_email, msg.as_string())
        server.quit()
        print_time(f"✅ Email successfully sent to {recipient_email}")
    except Exception as e:
        print_time(f"❌ Failed to send email: {e}")

def extract_products_from_backend(json_data):
    """Recursively hunts through Walmart's backend JSON for product objects."""
    extracted = []
    
    def recursive_search(node):
        if isinstance(node, dict):
            if 'name' in node and 'priceInfo' in node and 'canonicalUrl' in node:
                extracted.append(node)
            else:
                for v in node.values():
                    recursive_search(v)
        elif isinstance(node, list):
            for i in node:
                recursive_search(i)
                
    recursive_search(json_data)
    return extracted

def parse_price_robustly(price_node):
    """Dynamically parses a price node regardless of if it's a dict, string, or float."""
    if price_node is None:
        return None
        
    extracted_val = None
    if isinstance(price_node, dict):
        extracted_val = price_node.get('price')
    else:
        extracted_val = price_node
        
    if extracted_val is None:
        return None
        
    try:
        if isinstance(extracted_val, str):
            clean_str = re.sub(r'[^\d\.]', '', extracted_val)
            return float(clean_str) if clean_str else None
        else:
            return float(extracted_val)
    except Exception:
        return None

def scrape_walmart_lego(keyword="", min_discount_percent=20.0, min_original_price=0.0):
    all_discounted_products = []
    processed_urls = set()
    
    page_number = 1
    max_pages = 60  
    search_session_id = str(uuid.uuid4())[:10]
    
    while page_number <= max_pages:
        kw_encoded = keyword.strip().replace(' ', '+') if keyword else ""
        
        walmart_filter = "&filters=%5B%7B%22intent%22%3A%22retailer%22%2C%22values%22%3A%5B%22Walmart%22%5D%7D%5D"
        url = f"https://www.walmart.ca/en/search?q=lego+{kw_encoded}&page={page_number}{walmart_filter}"
        
        print_time(f"\n🔍 Fetching Database Payload for Search Page {page_number}...")
        html_content = get_proxied_page(url, session_id=search_session_id)
        
        if not html_content:
            page_number += 1
            continue

        soup = BeautifulSoup(html_content, "html.parser")
        script_tag = soup.find("script", id="__NEXT_DATA__")
        
        if not script_tag or not script_tag.string:
            print_time(f"🛑 Could not locate JSON Database on page {page_number}. Ending search.")
            break
            
        try:
            backend_data = json.loads(script_tag.string)
            raw_products = extract_products_from_backend(backend_data)
        except Exception as e:
            print_time(f"❌ JSON Parse Error: {e}")
            break

        print_time(f"🛠️ [DEBUG] Extracted {len(raw_products)} raw items from backend database.")
        
        if len(raw_products) == 0:
            print_time(f"🛑 Database is empty. End of search results reached at page {page_number}.")
            break

        new_items_found = 0

        for item in raw_products:
            raw_title = item.get('name', '')
            if not raw_title or 'lego' not in raw_title.lower():
                continue
                
            url_path = item.get('canonicalUrl', '')
            full_link = "https://www.walmart.ca" + url_path if url_path.startswith('/') else url_path
            clean_url = full_link.split('?')[0]
            
            if clean_url in processed_urls:
                continue
            processed_urls.add(clean_url)
            new_items_found += 1

            clean_title, set_number = parse_lego_title(raw_title)
            is_nasa = "42182" in set_number

            # --- COMPREHENSIVE OUT OF STOCK DRAGNET (WITH NONE/NULL FIX) ---
            item_json_str = json.dumps(item).replace(" ", "").upper()
            is_oos = False
            
            if item.get('isOutOfStock') is True: is_oos = True
            elif '"ISOUTOFSTOCK":TRUE' in item_json_str: is_oos = True
            elif '"AVAILABILITYSTATUS":"OUT_OF_STOCK"' in item_json_str: is_oos = True
            elif '"AVAILABILITYSTATUS":"UNAVAILABLE"' in item_json_str: is_oos = True
            elif '"OFFERTYPE":"OUT_OF_STOCK"' in item_json_str: is_oos = True
            elif '"STOCKSTATUS":"OUTOFSTOCK"' in item_json_str: is_oos = True
            
            badges = item.get('badges') or {}
            if isinstance(badges, dict):
                flags = badges.get('flags') or [] 
                if isinstance(flags, list):
                    for flag in flags:
                        if isinstance(flag, dict) and 'out of stock' in str(flag.get('text', '')).lower():
                            is_oos = True

            if is_oos:
                continue

            price_info = item.get('priceInfo', {})
            curr_price_raw = price_info.get('currentPrice') or price_info.get('price') or price_info.get('linePrice')
            was_price_raw = price_info.get('wasPrice') or price_info.get('regularPrice') or price_info.get('listPrice')

            curr_price = parse_price_robustly(curr_price_raw)
            was_price = parse_price_robustly(was_price_raw)
                
            if curr_price is None:
                continue
                
            if was_price is None or was_price < curr_price:
                was_price = curr_price

            seller = item.get('sellerName', '')
            if not seller:
                seller_info = item.get('seller', {})
                if isinstance(seller_info, dict):
                    seller = seller_info.get('sellerName', 'N/A')
            
            if seller and seller != "N/A" and "walmart" not in seller.lower():
                continue

            discount = 0.0
            if was_price > curr_price:
                discount = round(((was_price - curr_price) / was_price) * 100, 1)

            # Updated Check: Will not drop items based on original price anymore
            if was_price < min_original_price:
                continue

            # Updated Check: Requires exactly 20.0% or higher discount
            if discount >= min_discount_percent:
                all_discounted_products.append({
                    "title": clean_title,
                    "set_number": set_number,
                    "current_price": curr_price,
                    "original_price": was_price,
                    "discount": discount,
                    "seller": "Walmart.ca",
                    "link": clean_url,
                    "theme": keyword if keyword else "General LEGO"
                })
                print_time(f"    ✅ Added: {clean_title[:30]}... | ${curr_price} | Disc: {discount}%")

        if new_items_found == 0:
            print_time(f"🛑 No new items on page {page_number}. Ending search.")
            break

        page_number += 1

    print_time(f"--- Extraction Complete for {keyword if keyword else 'All LEGO'} ---")
    return all_discounted_products

def main():
    print_time("🔎 Walmart LEGO Proxy Scraper (Production Edition)")
    
    # --- UPDATED CRITERIA ---
    min_discount_percent = 20.0  # Only keep items >= 20% off
    min_original_price = 0.0     # Removed the $50 threshold

    themes = load_lego_themes()
    master_deal_list = []
    
    for theme in themes:
        display_name = theme if theme else "All LEGO"
        print(f"\n{'='*50}")
        print_time(f"🚀 STARTING DATABASE EXTRACTION FOR: {display_name.upper()}")
        print(f"{'='*50}")
        
        found_deals = scrape_walmart_lego(keyword=theme, 
                                          min_discount_percent=min_discount_percent, 
                                          min_original_price=min_original_price)
        if found_deals:
            master_deal_list.extend(found_deals)

    if master_deal_list:
        master_deal_list.sort(key=lambda x: x["discount"], reverse=True)
    
    send_email_report(master_deal_list)

if __name__ == "__main__":
    main()
