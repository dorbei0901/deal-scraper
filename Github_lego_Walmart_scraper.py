#!/usr/bin/env python
# coding: utf-8

import time
import re
import os
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
            # Slightly longer timeout for product pages
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

def parse_lego_title(raw_title):
    """Extracts the Set Number and heavily truncates the SEO fluff."""
    # Prioritize 5-digit numbers (modern sets), then 4-digit numbers that aren't years (19xx, 20xx)
    set_num_match = re.search(r'\b(\d{5})\b', raw_title)
    if not set_num_match:
        # Excludes 1900-1999 and 2000-2099 safely for old sets
        set_num_match = re.search(r'\b([1-8]\d{3})\b', raw_title) 
        
    set_number = set_num_match.group(1) if set_num_match else "N/A"
    
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
    page_number = 1
    max_pages = 6
    
    # Generate a simple sticky session ID
    import uuid
    search_session_id = str(uuid.uuid4())[:10]
    
    while page_number <= max_pages:
        kw_encoded = keyword.strip().replace(' ', '+') if keyword else ""
        
        # THE FIX: Reinjected the Walmart filter directly into the URL
        walmart_filter = "&filters=%5B%7B%22intent%22%3A%22retailer%22%2C%22values%22%3A%5B%22Walmart%22%5D%7D%5D"
        url = f"https://www.walmart.ca/en/search?q=lego+{kw_encoded}&page={page_number}{walmart_filter}"
        
        print_time(f"\n🔍 Fetching Walmart Search Page {page_number}...")
        html_content = get_proxied_page(url, session_id=search_session_id)
        
        if not html_content:
            page_number += 1
            continue

        soup = BeautifulSoup(html_content, "html.parser")
        product_links = soup.find_all("a", href=lambda href: href and ("/ip/" in href or "walmart.ca/en/ip" in href))
        
        print_time(f"🛠️ [DEBUG] Total product URLs found on page: {len(product_links)}")
        if not product_links:
            print_time(f"🛑 End of search results reached at page {page_number}.")
            break

        processed_urls = set()

        for link in product_links:
            href = link.get("href")
            if not href or href in processed_urls:
                continue
            processed_urls.add(href)

            raw_title_text = link.get_text(strip=True)
            if len(raw_title_text) < 5 or "lego" not in raw_title_text.lower():
                img = link.find("img")
                raw_title_text = img.get("alt", "") if img else ""
                if not raw_title_text:
                    continue
            
            clean_title, set_number = parse_lego_title(raw_title_text)
            full_link = href if href.startswith("http") else "https://www.walmart.ca" + href
            
            all_discounted_products.append({
                "title": clean_title,
                "set_number": set_number,
                "raw_title": raw_title_text,
                "link": full_link.split('?')[0], 
                "raw_link": full_link,
                "theme": keyword if keyword else "General LEGO" 
            })

        page_number += 1

    final_verified_deals = []
    
    if all_discounted_products:
        print_time(f"\n📦 Queued {len(all_discounted_products)} items. Intercepting Backend Payloads...")
        
        for index, deal in enumerate(all_discounted_products):
            print_time(f"⏳ [{index+1}/{len(all_discounted_products)}] Verifying: {deal['title']}")
            
            # Increased retries to 5 to prevent random network drops
            html_content = get_proxied_page(deal["raw_link"], max_retries=5)
            
            if not html_content:
                print_time("    ❌ Dropped: Failed to load product page after 5 attempts.")
                continue

            soup = BeautifulSoup(html_content, "html.parser")
            scripts = soup.find_all("script")
            
            backend_json_string = ""
            for script in scripts:
                if script.string and '"sellerName"' in script.string and '"currentPrice"' in script.string:
                    backend_json_string = script.string
                    break
            
            # 1. OUT OF STOCK CHECK
            if backend_json_string and '"availabilityStatus":"OUT_OF_STOCK"' in backend_json_string.replace(" ", ""):
                print_time("    ❌ Dropped: Backend status is Out of Stock.")
                continue

            # 2. SELLER CHECK
            seller_val = "N/A"
            if backend_json_string:
                seller_match = re.search(r'"sellerName"\s*:\s*"([^"]+)"', backend_json_string)
                if seller_match:
                    seller_val = seller_match.group(1).strip()
            
            if seller_val != "N/A" and "walmart" not in seller_val.lower():
                print_time(f"    ❌ Dropped: 3rd Party Seller ({seller_val})")
                continue
            
            deal["seller"] = "Walmart.ca"

            # 3. CURRENT PRICE (With Bulletproof Fallback)
            curr_val = None
            if backend_json_string:
                curr_match = re.search(r'"currentPrice"\s*:\s*\{[^}]*"price"\s*:\s*([\d\.]+)', backend_json_string)
                if curr_match:
                    curr_val = float(curr_match.group(1))
                    
            # HTML DOM Fallback if JSON Regex fails
            if not curr_val:
                price_elem = soup.find(attrs={"itemprop": "price"})
                if price_elem and price_elem.get("content"):
                    curr_val = float(price_elem.get("content"))
                
            if not curr_val:
                print_time("    ❌ Dropped: Could not parse current price.")
                continue

            deal["current_price"] = curr_val

            # 4. ORIGINAL/WAS PRICE
            orig_val = None
            if backend_json_string:
                orig_match = re.search(r'"wasPrice"\s*:\s*\{[^}]*"price"\s*:\s*([\d\.]+)', backend_json_string)
                if orig_match:
                    orig_val = float(orig_match.group(1))

            if not orig_val or orig_val < curr_val:
                orig_val = curr_val

            deal["original_price"] = orig_val

            # 5. FINAL MATH & VALIDATION
            if deal["original_price"] > deal["current_price"]:
                deal["discount"] = round(((deal["original_price"] - deal["current_price"]) / deal["original_price"]) * 100, 1)
            else:
                deal["discount"] = 0.0

            if deal["original_price"] < min_original_price:
                 print_time(f"    ❌ Dropped: MSRP (${deal['original_price']}) under minimum threshold (${min_original_price}).")
                 continue

            if deal["discount"] >= min_discount_percent:
                final_verified_deals.append(deal)
                print_time(f"    ✅ VERIFIED! Curr: ${deal['current_price']} | Orig: ${deal['original_price']} | Disc: {deal['discount']}%")
            else:
                print_time(f"    ❌ Dropped: Discount ({deal['discount']}%) too low.")

    print_time(f"--- Scrape Complete for {keyword if keyword else 'All LEGO'} ---")
    return final_verified_deals

def main():
    print_time("🔎 Walmart LEGO Proxy Scraper (Final Precision Edition)")
    
    # Kept at 0.0% for wide testing
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
