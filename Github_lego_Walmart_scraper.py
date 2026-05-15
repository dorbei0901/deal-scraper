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

def get_proxied_page(target_url, max_retries=3):
    """Fetches the raw HTML via ScraperAPI, bypassing headless browser detection."""
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

def safe_extract_price(element):
    """Strictly extracts price from an exact DOM element, preventing financing text leaks."""
    if not element:
        return None
        
    # Check hidden aria-labels (Walmart's cleanest data source)
    arias = [element.get('aria-label')] + [e.get('aria-label') for e in element.find_all(attrs={"aria-label": True})]
    for aria in arias:
        if aria and '$' in aria:
            match = re.search(r'\$\s*(\d+\.\d{2})', aria)
            if match: 
                return float(match.group(1))
                
    # Check raw text without separators to preserve decimal placements
    text = element.get_text(separator="", strip=True)
    clean_text = re.sub(r'[^\d\.]', '', text)
    
    match = re.search(r'(\d+\.\d{2})', clean_text)
    if match: 
        return float(match.group(1))
        
    return None

def load_lego_themes(filename="legoproductTest.txt"):
    if not os.path.exists(filename):
        print_time(f"⚠️ {filename} not found. Defaulting to general LEGO search.")
        return [""] 
    with open(filename, "r", encoding="utf-8") as file:
        themes = [line.strip() for line in file if line.strip()]
    return themes if themes else [""]

def format_price(price):
    return f"${price:.2f}" if price is not None else "N/A"

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
        <th style="color: white;">Type</th>
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
        <td>{deal['theme'].title() if deal['theme'] else 'General LEGO'}</td>
        <td>${deal['current_price']:.2f}</td>
        <td>${deal['original_price']:.2f}</td>
        <td style="color: red; font-weight: bold;">{deal['discount']}%</td>
        <td>{deal.get('seller', 'N/A')}</td>
        <td><a href="{deal['link']}">View Deal</a></td>
      </tr>
        """
        
    html += "</table></body></html>"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Walmart LEGO Deals - {len(deals)} Verified Discounts!"
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
    # INCREASED to 6 to dig past 3rd party display cases/light kits on pages 1-2
    max_pages = 6  
    
    while page_number <= max_pages:
        kw_encoded = keyword.strip().replace(' ', '+') if keyword else ""
        
        # URL Filter removed so Walmart API doesn't panic and return empty grids
        url = f"https://www.walmart.ca/en/search?q=lego+{kw_encoded}&page={page_number}"
        
        print_time(f"🔍 Fetching Raw HTML for Walmart Search Page {page_number}...")
        html_content = get_proxied_page(url)
        
        if not html_content:
            print_time(f"❌ Failed to fetch search page {page_number}. Moving to next.")
            page_number += 1
            continue

        soup = BeautifulSoup(html_content, "html.parser")
        product_links = soup.find_all("a", href=lambda href: href and ("/ip/" in href or "walmart.ca/en/ip" in href))
        
        # RESTORED DEBUG PRINT
        print_time(f"🛠️ [DEBUG] Total product links found in raw HTML: {len(product_links)}")
        
        if not product_links:
            break

        processed_urls = set()

        for link in product_links:
            href = link.get("href")
            if not href or href in processed_urls:
                continue
            processed_urls.add(href)

            parent = link.find_parent(attrs={"data-automation": "product"}) 
            if not parent:
                parent = link.find_parent("div", attrs={"data-testid": "item-stack"}) or link.parent.parent.parent

            if not parent: 
                continue

            title_text = link.get_text(strip=True)
            if not title_text or len(title_text) < 5 or "lego" not in title_text.lower():
                img = link.find("img")
                title_text = img.get("alt", "") if img else ""
                if not title_text:
                    continue
            
            short_title = (title_text[:40] + '...') if len(title_text) > 40 else title_text

            # STRICT Target - Only looks at elements assigned specifically as prices
            curr_elem = parent.find(attrs={"data-automation": "current-price"}) or \
                        parent.find(attrs={"data-automation": "buybox-price"}) or \
                        parent.find(attrs={"data-testid": "current-price"})

            orig_elem = parent.find(attrs={"data-automation": "strike-through-price"}) or \
                        parent.find(attrs={"data-automation": "regular-price"}) or \
                        parent.find(attrs={"data-testid": "was-price"})

            current_price = safe_extract_price(curr_elem)
            original_price = safe_extract_price(orig_elem)

            # Check if there's a visible sale badge on the card
            parent_text_lower = parent.get_text(separator=" ", strip=True).lower()
            badge_keywords = ["save", "clearance", "rollback", "reduced", "drop"]
            has_sale_badge = any(b in parent_text_lower for b in badge_keywords)

            if current_price is None:
                continue
                
            if original_price is None:
                original_price = current_price

            discount = 0.0
            if original_price > current_price:
                discount = round(((original_price - current_price) / original_price) * 100, 1)
            elif has_sale_badge:
                discount = 99.0 # Placeholder flag to prompt the Phase 2 product page check

            if original_price < min_original_price:
                continue

            if discount >= min_discount_percent or has_sale_badge:
                if " - " in title_text: title_text = title_text.split(" - ")[0].strip()
                if len(title_text) > 60: title_text = title_text[:60].strip() + "..."
                
                full_link = href if href.startswith("http") else "https://www.walmart.ca" + href
                
                all_discounted_products.append({
                    "title": title_text,
                    "current_price": current_price,
                    "original_price": original_price,
                    "discount": discount,
                    "link": full_link.split('?')[0], 
                    "raw_link": full_link,
                    "theme": keyword if keyword else "General LEGO" 
                })

        page_number += 1

    final_verified_deals = []
    
    if all_discounted_products:
        print_time(f"📦 Found {len(all_discounted_products)} potentially qualified items. Verifying prices & seller...")
        
        for index, deal in enumerate(all_discounted_products):
            print_time(f"⏳ [{index+1}/{len(all_discounted_products)}] Fetching details for: {deal['title'][:30]}...")
            
            html_content = get_proxied_page(deal["raw_link"])
            
            if not html_content:
                print_time("  ❌ Failed to load product page.")
                continue

            prod_soup = BeautifulSoup(html_content, "html.parser")
            clean_page_text = prod_soup.get_text(separator=" ", strip=True)
            
            # Target exactly where the true product page prices live
            curr_elem = prod_soup.find(attrs={"data-automation": "buybox-price"}) or \
                        prod_soup.find(attrs={"data-automation": "current-price"})
            orig_elem = prod_soup.find(attrs={"data-automation": "strike-through-price"}) or \
                        prod_soup.find(attrs={"data-automation": "regular-price"})

            new_curr = safe_extract_price(curr_elem)
            new_orig = safe_extract_price(orig_elem)

            if new_curr: deal["current_price"] = new_curr
            if new_orig: deal["original_price"] = new_orig

            if deal["original_price"] > deal["current_price"]:
                deal["discount"] = round(((deal["original_price"] - deal["current_price"]) / deal["original_price"]) * 100, 1)
            else:
                deal["discount"] = 0.0

            # Strict Seller Check - Confined to the buybox to prevent false positives
            seller_val = "N/A"
            seller_elem = prod_soup.find(attrs={"data-automation": "seller-name"})
            if seller_elem:
                seller_val = seller_elem.get_text(strip=True)
            else:
                buybox = prod_soup.find(attrs={"data-testid": "buy-box"}) or prod_soup.body
                buybox_text = buybox.get_text(separator=" ", strip=True)
                
                if "Sold and shipped by Walmart" in buybox_text or "Sold by Walmart" in buybox_text:
                    seller_val = "Walmart.ca"
                else:
                    match = re.search(r'Sold and shipped by\s+([^|•\n]+)', buybox_text)
                    if match: seller_val = match.group(1).strip()

            if "Walmart" in seller_val: seller_val = "Walmart.ca"
            deal["seller"] = seller_val

            if deal["seller"] != "Walmart.ca":
                print_time(f"  ❌ Dropped: Sold by 3rd Party ({deal['seller']})")
                continue

            if deal["discount"] >= min_discount_percent:
                final_verified_deals.append(deal)
                print_time(f"  ✅ Verified Deal: {deal['discount']}% off! Seller: Walmart")
            else:
                print_time(f"  ❌ Dropped: Final true discount is {deal['discount']}%.")

    print_time(f"--- Scrape Complete for {keyword if keyword else 'All LEGO'} ---")
    return final_verified_deals

def main():
    print_time("🔎 Walmart LEGO Proxy Scraper (Deep Dig Debug Edition)")
    
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
