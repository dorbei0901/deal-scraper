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
            response = requests.get(proxy_url, timeout=40) 
            
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

def safe_extract_price(element):
    """Strictly extracts price from an exact DOM element."""
    if not element:
        return None
    arias = [element.get('aria-label')] + [e.get('aria-label') for e in element.find_all(attrs={"aria-label": True})]
    for aria in arias:
        if aria and '$' in aria:
            match = re.search(r'\$\s*(\d+\.\d{2})', aria)
            if match: return float(match.group(1))
    text = element.get_text(separator="", strip=True)
    clean_text = re.sub(r'[^\d\.]', '', text)
    match = re.search(r'(\d+\.\d{2})', clean_text)
    if match: return float(match.group(1))
    return None

def parse_lego_title(raw_title):
    """Extracts the Set Number and heavily truncates the SEO fluff."""
    set_number = "N/A"
    # Prioritize 5-digit modern LEGO numbers
    match_5 = re.search(r'\b(\d{5})\b', raw_title)
    if match_5:
        set_number = match_5.group(1)
    else:
        # Fallback to 4-digit numbers, but explicitly ignore years like 19xx or 20xx
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
    msg["Subject"] = f"Walmart LEGO Deals - {len(deals)} Deals Found!"
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

def scrape_walmart_lego(keyword="", min_discount_percent=0.0, min_original_price=50.0):
    all_discounted_products = []
    global_processed_urls = set() # Track URLs across ALL pages to prevent infinite loops
    
    page_number = 1
    search_session_id = str(uuid.uuid4())[:10]
    
    while page_number <= 15: # Hard cap at 15 to prevent absolute infinite runaways
        kw_encoded = keyword.strip().replace(' ', '+') if keyword else ""
        
        walmart_filter = "&filters=%5B%7B%22intent%22%3A%22retailer%22%2C%22values%22%3A%5B%22Walmart%22%5D%7D%5D"
        url = f"https://www.walmart.ca/en/search?q=lego+{kw_encoded}&page={page_number}{walmart_filter}"
        
        print_time(f"\n🔍 Fetching Walmart Search Page {page_number}...")
        html_content = get_proxied_page(url, session_id=search_session_id)
        
        if not html_content:
            page_number += 1
            continue

        soup = BeautifulSoup(html_content, "html.parser")
        product_links = soup.find_all("a", href=lambda href: href and ("/ip/" in href or "walmart.ca/en/ip" in href))
        
        new_items_on_page = 0
        
        for link in product_links:
            href = link.get("href")
            full_link = href if href.startswith("http") else "https://www.walmart.ca" + href
            clean_url = full_link.split('?')[0]
            
            # Global deduplication: Only process sets we haven't seen on previous pages
            if clean_url in global_processed_urls:
                continue
                
            raw_title_text = link.get_text(strip=True)
            if len(raw_title_text) < 5 or "lego" not in raw_title_text.lower():
                img = link.find("img")
                raw_title_text = img.get("alt", "") if img else ""
                if not raw_title_text:
                    continue
            
            global_processed_urls.add(clean_url)
            new_items_on_page += 1
            
            clean_title, set_number = parse_lego_title(raw_title_text)
            
            all_discounted_products.append({
                "title": clean_title,
                "set_number": set_number,
                "raw_title": raw_title_text,
                "link": clean_url, 
                "raw_link": full_link,
                "theme": keyword if keyword else "General LEGO" 
            })

        print_time(f"🛠️ [DEBUG] Found {new_items_on_page} NEW items on this page.")
        
        if new_items_on_page == 0:
            print_time(f"🛑 No new items found. End of Walmart catalog reached at page {page_number}.")
            break

        page_number += 1

    final_verified_deals = []
    
    if all_discounted_products:
        print_time(f"\n📦 Queued {len(all_discounted_products)} unique items. Commencing Hybrid Verification...")
        
        for index, deal in enumerate(all_discounted_products):
            print_time(f"⏳ [{index+1}/{len(all_discounted_products)}] Verifying: {deal['title']}")
            
            html_content = get_proxied_page(deal["raw_link"], max_retries=4)
            if not html_content:
                print_time("    ❌ Dropped: Failed to load product page.")
                continue

            soup = BeautifulSoup(html_content, "html.parser")
            
            # Variables to track data extracted
            curr_val = None
            orig_val = None
            seller_val = "N/A"
            is_out_of_stock = False

            # --- PHASE 1: ATTEMPT BACKEND JSON PARSING ---
            scripts = soup.find_all("script")
            backend_json_string = ""
            for script in scripts:
                if script.string and '"sellerName"' in script.string and '"currentPrice"' in script.string:
                    backend_json_string = script.string
                    break
            
            if backend_json_string:
                if '"availabilityStatus":"OUT_OF_STOCK"' in backend_json_string.replace(" ", ""):
                    is_out_of_stock = True
                    
                seller_match = re.search(r'"sellerName"\s*:\s*"([^"]+)"', backend_json_string)
                if seller_match: seller_val = seller_match.group(1).strip()
                
                curr_match = re.search(r'"currentPrice"\s*:\s*\{[^}]*"price"\s*:\s*([\d\.]+)', backend_json_string)
                if not curr_match: curr_match = re.search(r'"price"\s*:\s*([\d\.]+)', backend_json_string)
                if curr_match: curr_val = float(curr_match.group(1))
                
                orig_match = re.search(r'"wasPrice"\s*:\s*\{[^}]*"price"\s*:\s*([\d\.]+)', backend_json_string)
                if orig_match: orig_val = float(orig_match.group(1))

            # --- PHASE 2: HTML DOM FALLBACK (The Safety Net) ---
            buybox = soup.find(attrs={"data-testid": "buy-box"}) or soup.find("main") or soup.body
            buybox_text = buybox.get_text(separator=" ", strip=True)

            if not is_out_of_stock and "out of stock" in buybox_text.lower():
                is_out_of_stock = True

            if seller_val == "N/A":
                seller_elem = soup.find(attrs={"data-automation": "seller-name"})
                if seller_elem:
                    seller_val = seller_elem.get_text(strip=True)
                elif "sold and shipped by walmart" in buybox_text.lower() or "sold by walmart" in buybox_text.lower():
                    seller_val = "Walmart.ca"
                else:
                    smatch = re.search(r'(?:Sold and shipped by|Sold by)\s+([^•|\n,]+)', buybox_text, re.IGNORECASE)
                    if smatch: seller_val = smatch.group(1).strip()

            if not curr_val:
                curr_elem = buybox.find(attrs={"data-automation": "buybox-price"}) or buybox.find(attrs={"itemprop": "price"})
                curr_val = safe_extract_price(curr_elem)
                if not curr_val:
                    clean_bb = re.sub(r'(?i)(/mo|month|bi-weekly|klarna|afterpay).*', '', buybox_text)
                    prices = re.findall(r'\$\s*(\d+\.\d{2})', clean_bb)
                    if prices: curr_val = float(prices[0])

            if not orig_val:
                orig_elem = buybox.find(attrs={"data-automation": "strike-through-price"}) or buybox.find(attrs={"data-testid": "was-price"})
                orig_val = safe_extract_price(orig_elem)
                if not orig_val:
                    was_match = re.search(r'was\s*\$\s*(\d+\.\d{2})', buybox_text, re.IGNORECASE)
                    if was_match: orig_val = float(was_match.group(1))


            # --- PHASE 3: FINAL EVALUATION ---
            if is_out_of_stock:
                print_time("    ❌ Dropped: Out of Stock.")
                continue
                
            if "walmart" not in seller_val.lower():
                print_time(f"    ❌ Dropped: 3rd Party Seller ({seller_val})")
                continue
                
            if not curr_val:
                print_time("    ❌ Dropped: Could not parse current price.")
                continue

            # Zero-Trust Override
            if not orig_val or orig_val < curr_val:
                orig_val = curr_val

            deal["current_price"] = curr_val
            deal["original_price"] = orig_val
            deal["seller"] = "Walmart.ca"

            if deal["original_price"] > deal["current_price"]:
                deal["discount"] = round(((deal["original_price"] - deal["current_price"]) / deal["original_price"]) * 100, 1)
            else:
                deal["discount"] = 0.0

            if deal["original_price"] < min_original_price:
                 print_time(f"    ❌ Dropped: MSRP (${deal['original_price']}) under ${min_original_price} minimum.")
                 continue

            if deal["discount"] >= min_discount_percent:
                final_verified_deals.append(deal)
                print_time(f"    ✅ VERIFIED! Curr: ${deal['current_price']} | Orig: ${deal['original_price']} | Disc: {deal['discount']}%")
            else:
                print_time(f"    ❌ Dropped: Discount ({deal['discount']}%) too low.")

    print_time(f"--- Scrape Complete for {keyword if keyword else 'All LEGO'} ---")
    return final_verified_deals

def main():
    print_time("🔎 Walmart LEGO Proxy Scraper (Hybrid Engine Edition)")
    
    min_discount_percent = 0.0 
    min_original_price = 50.0

    themes = load_lego_themes()
    master_deal_list = []
    
    for theme in themes:
        display_name = theme if theme else "All LEGO"
        print(f"\n{'='*50}")
        print_time(f"🚀 STARTING RAW SEARCH FOR: {display_name.upper()}")
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
