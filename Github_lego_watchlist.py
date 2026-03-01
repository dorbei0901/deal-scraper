#!/usr/bin/env python
# coding: utf-8

import time
import re
import os
import random
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

def extract_price(text):
    """Extracts a float price from a text string, handling commas and currency symbols."""
    clean_text = text.replace('CDN$', '').replace('$', '').replace(',', '').strip()
    match = re.search(r'(\d+\.?\d*)', clean_text)
    return float(match.group(1)) if match else None

def extract_lego_theme(title):
    """Infers the LEGO theme from the product title."""
    themes = [
        "Technic", "Ideas", "Star Wars", "Creator", "City", "Friends", 
        "Ninjago", "Harry Potter", "Marvel", "DC", "Architecture", 
        "Icons", "Speed Champions", "Botanical Collection", "Super Mario", 
        "Avatar", "Jurassic World", "Minecraft", "Disney", "Classic", "Duplo", 
        "Art", "Indiana Jones", "Lord of the Rings", "Dreamzzz", "Monkie Kid"
    ]
    title_lower = title.lower()
    for theme in themes:
        if theme.lower() in title_lower:
            return theme
    return "General"

def build_search_url(keyword: str) -> str:
    base_url = "https://www.amazon.ca/s"
    if keyword:
        kw_encoded = keyword.strip().replace(' ', '+')
        query = f"k=lego+{kw_encoded}"
    else:
        query = "k=lego"
    return f"{base_url}?{query}"

def load_lego_watchlist(filename="legowatchlist.txt"):
    """Reads specific LEGO set numbers from a text file."""
    if not os.path.exists(filename):
        print(f"⚠️ {filename} not found in the repository. Please create it.")
        return [] 
    with open(filename, "r", encoding="utf-8") as file:
        numbers = [line.strip() for line in file if line.strip()]
    
    print(f"📁 Loaded {len(numbers)} LEGO numbers from {filename}")
    return numbers

def format_price(price):
    """Helper to safely format prices, handling None values."""
    return f"${price:.2f}" if price is not None else "N/A"

def send_email_report(deals):
    """Generates an HTML table and sends it via email securely."""
    sender_email = os.getenv("GMAIL_ADDRESS")
    sender_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient_email = os.getenv("RECIPIENT_EMAIL")

    if not sender_email or not sender_password or not recipient_email:
        print("\n⚠️ Missing email credentials. Skipping email delivery.")
        return

    if not deals:
        print("\n📭 Watchlist is empty, no email to send.")
        return

    print(f"\n📧 Formatting Watchlist Report into an email for {recipient_email}...")

    html = """
    <html>
    <head>
    <style>
      table { border-collapse: collapse; width: 100%; font-family: Arial, sans-serif; }
      th, td { text-align: left; padding: 8px; border: 1px solid #ddd; }
      th { background-color: #f2f2f2; color: #333; }
      tr:nth-child(even) {background-color: #f9f9f9;}
      a { color: #0066c0; text-decoration: none; font-weight: bold; }
      a:hover { text-decoration: underline; }
    </style>
    </head>
    <body>
    <h2>Daily LEGO Watchlist Report</h2>
    <table>
      <tr>
        <th>Lego Name</th>
        <th>Lego Number</th>
        <th>Lego Type</th>
        <th>Original Price</th>
        <th>Discounted Price</th>
        <th>Discount Percentage</th>
        <th>Shipper</th>
        <th>Seller</th>
        <th>Amazon Link</th>
      </tr>
    """
    
    for deal in deals:
        discount_style = 'style="color: green; font-weight: bold;"' if deal['discount'] > 0 else ''
        
        html += f"""
      <tr>
        <td>{deal['title']}</td>
        <td>{deal['lego_number']}</td>
        <td>{deal['theme']}</td>
        <td>{format_price(deal['original_price'])}</td>
        <td>{format_price(deal['current_price'])}</td>
        <td {discount_style}>{deal['discount']}%</td>
        <td>{deal['shipper']}</td>
        <td>{deal['seller']}</td>
        <td><a href="{deal['link']}">View Deal</a></td>
      </tr>
        """
        
    html += """
    </table>
    </body>
    </html>
    """

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

def scrape_single_lego_set(driver, lego_number, amazon_tag=""):
    """Searches using robust ASIN-extraction and deep-links to product page."""
    max_retries = 3 
    
    result_deal = {
        "title": "Not Found / Out of Stock",
        "lego_number": lego_number,
        "theme": "N/A",
        "current_price": None,
        "original_price": None,
        "discount": 0.0,
        "shipper": "N/A",
        "seller": "N/A",
        "link": build_search_url(lego_number)
    }

    try:
        url = result_deal["link"]
        target_asin = None
        target_url = None
        
        search_current_price = None
        search_original_price = None
        
        # Step 1: Execute Search
        for attempt in range(max_retries):
            driver.get(url)
            time.sleep(random.uniform(3, 5)) 

            if "captcha" in driver.current_url.lower() or "Robot Check" in driver.title or "Sorry!" in driver.title:
                print(f"  ⚠️ Amazon bot check detected. Resting and clearing cookies...")
                driver.delete_all_cookies()
                driver.get("https://www.amazon.ca")
                time.sleep(5)
                continue

            driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(2)

            try:
                WebDriverWait(driver, 8).until(
                    lambda d: "/dp/" in d.current_url or "/product/" in d.current_url or \
                              d.find_elements(By.CSS_SELECTOR, "div[data-component-type='s-search-result']") or \
                              d.find_elements(By.CSS_SELECTOR, "div[data-asin]")
                )
                break 
            except TimeoutException:
                driver.refresh()
                time.sleep(4)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # Determine the core 4 or 5 digit Lego number to search for
        match = re.search(r'\d{4,5}', str(lego_number))
        core_set_number = match.group(0) if match else str(lego_number).lower().strip()
        
        # Extensive Junk Filter
        junk_words = [
            "light kit", "led light", "lighting kit", "briksmax", "lightailing", 
            "acrylic", "display case", "wall mount", "display stand", "wall hanger", "frame"
        ]

        # Step 2: Determine Target ASIN / URL
        if "/dp/" in driver.current_url or "/product/" in driver.current_url:
            target_url = driver.current_url
        else:
            products = soup.find_all("div", attrs={"data-asin": True})
            
            for item in products:
                asin = item.get("data-asin")
                if not asin or len(asin) < 10:
                    continue 
                
                full_item_text = item.get_text(separator=" ", strip=True).lower()
                
                # Check 1: Must contain the core Lego number
                if core_set_number not in full_item_text:
                    continue
                
                # Check 2: Reject junk items
                if any(junk in full_item_text for junk in junk_words):
                    continue 
                        
                target_asin = asin
                
                # Opportunistically grab search page prices as a backup (Upgraded to handle missing .a-offscreen)
                price_span = item.find("span", class_="a-price")
                if price_span:
                    off = price_span.find("span", class_="a-offscreen")
                    search_current_price = extract_price(off.get_text(strip=True)) if off else extract_price(price_span.get_text(strip=True))
                    
                orig_span = item.find("span", class_="a-text-price")
                if orig_span:
                    off = orig_span.find("span", class_="a-offscreen")
                    search_original_price = extract_price(off.get_text(strip=True)) if off else extract_price(orig_span.get_text(strip=True))
                elif item.find('span', {'data-a-strike': 'true'}):
                    strike = item.find('span', {'data-a-strike': 'true'})
                    off = strike.find('span', class_='a-offscreen')
                    search_original_price = extract_price(off.get_text(strip=True)) if off else extract_price(strike.get_text(strip=True))

                break # Target ASIN secured! Exit loop.

        if target_asin and not target_url:
            target_url = f"https://www.amazon.ca/dp/{target_asin}"
        
        if not target_url:
            print(f"❌ Could not locate {lego_number} in search results.")
            return result_deal

        # Step 3: Deep Link Extraction on Product Page
        if target_url != driver.current_url:
            driver.get(target_url)
            time.sleep(random.uniform(3, 5)) 
            soup = BeautifulSoup(driver.page_source, "html.parser")
            
        title_elem = soup.find(id="productTitle")
        if not title_elem:
            return result_deal 
            
        title_text = title_elem.get_text(strip=True)
        
        # Double check it isn't a junk item that slipped through a direct Amazon redirect
        if any(junk in title_text.lower() for junk in junk_words):
            print(f"❌ Blocked Junk Item for {lego_number}: {title_text[:40]}...")
            return result_deal

        result_deal["theme"] = extract_lego_theme(title_text)

        # Name Trimming Rules
        if " - " in title_text:
            title_text = title_text.split(" - ")[0].strip()
        if len(title_text) > 60:
            result_deal["title"] = title_text[:60].strip() + "..."
        else:
            result_deal["title"] = title_text
        
        # Affiliate Link Generation
        result_deal["link"] = f"https://www.amazon.ca/dp/{target_asin}?tag={amazon_tag}" if target_asin and amazon_tag else driver.current_url

        # Master Price Extraction - UPGRADED CATCH-ALL
        current_price_tag = soup.select_one('div#corePriceDisplay_desktop_feature_div span.a-price.priceToPay') or \
                            soup.select_one('div#corePriceDisplay_desktop_feature_div span.a-price') or \
                            soup.select_one('#desktop_buybox span.a-price') or \
                            soup.select_one('#buybox span.a-price') or \
                            soup.select_one('#buyNewSection span.a-price') or \
                            soup.select_one('div#corePrice_feature_div span.a-price') or \
                            soup.select_one('.priceToPay')
        
        if current_price_tag:
            offscreen = current_price_tag.select_one('span.a-offscreen')
            text_to_extract = offscreen.get_text(strip=True) if offscreen else current_price_tag.get_text(strip=True)
            result_deal["current_price"] = extract_price(text_to_extract)
        else:
            result_deal["current_price"] = search_current_price

        original_price_tag = soup.select_one('div#corePriceDisplay_desktop_feature_div span.basisPrice') or \
                             soup.select_one('#desktop_buybox span.basisPrice') or \
                             soup.select_one('#buybox span.basisPrice') or \
                             soup.select_one('.basisPrice') or \
                             soup.select_one('span.a-text-strike')
                             
        if original_price_tag: 
            offscreen = original_price_tag.select_one('span.a-offscreen')
            text_to_extract = offscreen.get_text(strip=True) if offscreen else original_price_tag.get_text(strip=True)
            result_deal["original_price"] = extract_price(text_to_extract)
        else:
            result_deal["original_price"] = search_original_price 

        if result_deal["current_price"] is not None and result_deal["original_price"] is None:
            result_deal["original_price"] = result_deal["current_price"]

        if result_deal["current_price"] and result_deal["original_price"] and result_deal["original_price"] > result_deal["current_price"]:
            result_deal["discount"] = round(((result_deal["original_price"] - result_deal["current_price"]) / result_deal["original_price"]) * 100, 1)

        # Master Shipper/Seller Extraction
        buybox = soup.find("div", id="desktop_buybox") or soup.find("div", id="buybox")
        if buybox:
            bb_text = buybox.get_text(separator=" ", strip=True)
            shipper_val, seller_val = "N/A", "N/A"
            
            if "Shipper / Seller" in bb_text:
                match = re.search(r'Shipper / Seller\s+(.*?)(?:\s+Returns|\s+Payment|\s+Details|$)', bb_text)
                if match: shipper_val = seller_val = match.group(1).strip()
            elif "Ships from" in bb_text and "Sold by" in bb_text:
                shipper_match = re.search(r'Ships from\s+(.*?)(?:\s+Sold by|\s+Returns|\s+Payment|$)', bb_text)
                if shipper_match: shipper_val = shipper_match.group(1).strip()
                seller_match = re.search(r'Sold by\s+(.*?)(?:\s+Returns|\s+Payment|\s+Details|$)', bb_text)
                if seller_match: seller_val = seller_match.group(1).strip()
                
            if "Ships from and sold by Amazon" in bb_text:
                shipper_val = seller_val = "Amazon.ca"

            if "Amazon" in shipper_val: shipper_val = "Amazon.ca"
            if "Amazon" in seller_val: seller_val = "Amazon.ca"

            result_deal["shipper"] = shipper_val
            result_deal["seller"] = seller_val

        print(f"✅ Found {lego_number}: {result_deal['title'][:40]}... | Type: {result_deal['theme']} | Discount: {result_deal['discount']}%")
        return result_deal
        
    except Exception as e:
        print(f"Error processing {lego_number}: {e}")
        return result_deal

def main():
    print("🔎 Amazon LEGO Watchlist Scraper (GitHub Actions Edition)")
    
    amazon_tag = os.getenv('AMAZON_TAG', '')
    lego_numbers = load_lego_watchlist()
    master_watchlist_deals = []
    
    options = uc.ChromeOptions()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

    driver = uc.Chrome(options=options, version_main=144)
    
    try:
        driver.get("https://www.amazon.ca")
        time.sleep(4)
        
        for number in lego_numbers:
            print(f"\n🚀 Checking Watchlist: LEGO {number}")
            deal = scrape_single_lego_set(driver, lego_number=number, amazon_tag=amazon_tag)
            master_watchlist_deals.append(deal)
            
            time.sleep(random.uniform(4, 7))

        if master_watchlist_deals:
            master_watchlist_deals.sort(key=lambda x: x["discount"], reverse=True)
        
        send_email_report(master_watchlist_deals)
        
    finally:
        driver.quit()
        print("\n🏁 Script Complete. Browser closed securely.")

if __name__ == "__main__":
    main()
