#!/usr/bin/env python
# coding: utf-8

import time
import re
import os
import smtplib
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import subprocess

def get_chrome_major_version():
    """Dynamically finds the major version of Chrome installed on the OS."""
    try:
        process = subprocess.Popen(['google-chrome', '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, _ = process.communicate()
        version_string = stdout.decode('utf-8')
        
        match = re.search(r'(\d+)\.', version_string)
        if match:
            major_version = int(match.group(1))
            print(f"🔍 Detected Chrome Major Version: {major_version}")
            return major_version
    except Exception as e:
        print(f"⚠️ Could not detect Chrome version dynamically: {e}")
        
    return None

def extract_price(text):
    """Extracts a float price from a text string, handling commas and currency symbols."""
    clean_text = text.replace('CDN$', '').replace('$', '').replace(',', '').strip()
    match = re.search(r'(\d+\.?\d*)', clean_text)
    return float(match.group(1)) if match else None

def extract_asin(url):
    """Extracts the unique Amazon ASIN from a URL for deduplication."""
    match = re.search(r'/(?:dp|gp/product)/([a-zA-Z0-9]{10})', url)
    return match.group(1) if match else url

def build_search_url(keyword: str) -> str:
    base_url = "https://www.amazon.ca/s"
    if keyword:
        kw_encoded = keyword.strip().replace(' ', '+')
        query = f"k=lego+{kw_encoded}&rh=p_89%3ALEGO"
    else:
        query = "k=lego&rh=p_89%3ALEGO"
    return f"{base_url}?{query}"

def load_lego_themes(filename="legoproduct.txt"):
    if not os.path.exists(filename):
        print(f"⚠️ {filename} not found in the repository. Defaulting to general LEGO search.")
        return [""] 
    with open(filename, "r", encoding="utf-8") as file:
        themes = [line.strip() for line in file if line.strip()]
    return themes if themes else [""]

def send_email_report(deals):
    """Generates an HTML table and sends it via email securely."""
    sender_email = os.getenv("GMAIL_ADDRESS")
    sender_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient_email = os.getenv("RECIPIENT_EMAIL")

    if not sender_email or not sender_password or not recipient_email:
        print("\n⚠️ Missing email credentials or recipient email in GitHub Secrets. Skipping email delivery.")
        return

    if not deals:
        print("\n📭 No deals found today to email.")
        return

    print(f"\n📧 Formatting {len(deals)} deals into an email report for {recipient_email}...")

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
    <h2>Daily LEGO Deals Report</h2>
    <table>
      <tr>
        <th>Product Name</th>
        <th>Product Type</th>
        <th>Current</th>
        <th>Original</th>
        <th>Discount</th>
        <th>Shipper</th>
        <th>Seller</th>
        <th>Status Change</th>
        <th>Amazon Link</th>
      </tr>
    """
    
    for deal in deals:
        status = deal.get("status_change", "")
        row_style = ""
        
        # Color coding based on status change
        if status == "New":
            row_style = ' style="background-color: #d4edda;"' # Light Green
        elif status == "Removed":
            row_style = ' style="background-color: #e2e3e5; color: #6c757d;"' # Light Grey
        elif status == "Price Changed":
            row_style = ' style="background-color: #fff3cd;"' # Light Yellow

        html += f"""
      <tr{row_style}>
        <td>{deal.get('title', 'N/A')}</td>
        <td>{deal.get('theme', 'General LEGO').title()}</td>
        <td>${deal.get('current_price', 0):.2f}</td>
        <td>${deal.get('original_price', 0):.2f}</td>
        <td style="color: red; font-weight: bold;">{deal.get('discount', 0)}%</td>
        <td>{deal.get('shipper', 'N/A')}</td>
        <td>{deal.get('seller', 'N/A')}</td>
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
    msg["Subject"] = f"LEGO Deals Report - {len(deals)} Great Discounts Found!"
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

def scrape_amazon_lego_selenium(keyword="", min_discount_percent=30.0, min_original_price=50.0, amazon_tag=""):
    options = uc.ChromeOptions()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

    chrome_version = get_chrome_major_version()
    
    if chrome_version:
        driver = uc.Chrome(options=options, version_main=chrome_version)
    else:
        driver = uc.Chrome(options=options)
        
    all_discounted_products = []
    page_number = 1
    max_retries = 5 

    try:
        url = build_search_url(keyword)
        print("🍪 Warming up session cookies to bypass WAF...")
        
        driver.get("https://www.amazon.ca")
        time.sleep(6) 
        driver.execute_script("window.scrollBy(0, 700);")
        time.sleep(3)
        
        print(f"🔍 Now navigating to target URL: {url}")

        initial_load_successful = False
        for attempt in range(max_retries):
            driver.get(url)
            time.sleep(6) 

            try:
                WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.ID, "sp-cc-accept"))
                ).click()
                time.sleep(2)
            except (TimeoutException, NoSuchElementException):
                pass 

            if "Something went wrong" in driver.page_source or "Sorry!" in driver.title or "captcha" in driver.current_url.lower():
                print(f"⚠️ Bot detection triggered on attempt {attempt + 1}. Refreshing...")
                driver.refresh() 
                time.sleep(7) 
            else:
                try:
                    WebDriverWait(driver, 10).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, "div[data-component-type='s-search-result']"))
                    )
                    initial_load_successful = True
                    break 
                except TimeoutException:
                    print(f"❌ Products not detected on attempt {attempt + 1}. Retrying...")
                    driver.refresh()
                    time.sleep(6)

        if not initial_load_successful:
            print(f"❌ Failed to load search results after {max_retries} attempts. Amazon is blocking the GitHub IP.")
            return [] 

        while True:
            try:
                banner_accept_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, '#cos-banner [name="accept"]'))
                )
                banner_accept_button.click()
                time.sleep(2)
            except (TimeoutException, NoSuchElementException):
                pass 

            for _ in range(3):
                driver.execute_script("window.scrollBy(0, 1500);")
                time.sleep(1.5)

            try:
                WebDriverWait(driver, 10).until( 
                    EC.visibility_of_element_located((By.CSS_SELECTOR, "div[data-component-type='s-search-result']"))
                )
            except TimeoutException:
                break

            soup = BeautifulSoup(driver.page_source, "lxml")
            products = soup.find_all("div", {"data-component-type": "s-search-result"})

            if not products:
                break

            for item in products:
                title = "N/A"
                link = "N/A"
                current_price = None
                original_price = None
                discount = 0.0

                try:
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
                                if relative_link and not relative_link.startswith("http"):
                                    link = "https://www.amazon.ca" + relative_link
                                else:
                                    link = relative_link

                    if title != "N/A" and " - " in title:
                        title = title.split(" - ")[0].strip()

                    current_price_span = item.find("span", class_="a-price")
                    if current_price_span:
                        current_price_offscreen = current_price_span.find("span", class_="a-offscreen")
                        if current_price_offscreen:
                            current_price = extract_price(current_price_offscreen.get_text(strip=True))

                    original_price_span = item.find("span", class_="a-text-price")
                    if original_price_span:
                        original_price_offscreen = original_price_span.find("span", class_="a-offscreen")
                        if original_price_offscreen:
                            original_price = extract_price(original_price_offscreen.get_text(strip=True))
                    elif item.find('span', {'data-a-strike': 'true'}):
                        strike_tag = item.find('span', {'data-a-strike': 'true'})
                        offscreen_span = strike_tag.find('span', class_='a-offscreen')
                        if offscreen_span:
                            original_price = extract_price(offscreen_span.get_text(strip=True))
                        else:
                             original_price = extract_price(strike_tag.get_text(strip=True))

                    if current_price is not None and original_price is None:
                        original_price = current_price

                    if current_price is not None and original_price is not None and original_price > 0 and original_price > current_price:
                        discount = round(((original_price - current_price) / original_price) * 100, 1)

                    if title != "N/A" and link != "N/A" and "slredirect.amazon.ca" not in link:
                        if discount >= min_discount_percent and original_price >= min_original_price:
                            
                            if amazon_tag:
                                separator = "&" if "?" in link else "?"
                                final_link = f"{link}{separator}tag={amazon_tag}"
                            else:
                                final_link = link

                            all_discounted_products.append({
                                "title": title,
                                "current_price": current_price,
                                "original_price": original_price,
                                "discount": discount,
                                "link": final_link,
                                "raw_link": link,
                                "shipper": "N/A",
                                "seller": "N/A",
                                "theme": keyword if keyword else "General LEGO" 
                            })

                except Exception as e:
                    continue

            next_button = None
            try:
                next_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, 'a.s-pagination-next'))
                )
            except (NoSuchElementException, TimeoutException):
                pass

            if next_button and 's-pagination-disabled' not in next_button.get_attribute('class'):
                next_button.click()
                page_number += 1
                time.sleep(4)
            else:
                break

        if all_discounted_products:
            print(f"\n📦 Fetching Shipper & Seller info for {len(all_discounted_products)} qualified items...")
            for deal in all_discounted_products:
                try:
                    driver.get(deal["raw_link"])
                    
                    try:
                        WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located((By.ID, "desktop_buybox"))
                        )
                    except TimeoutException:
                        pass
                        
                    time.sleep(2)
                    prod_soup = BeautifulSoup(driver.page_source, "html.parser")
                    
                    buybox = prod_soup.find("div", id="desktop_buybox") or prod_soup.find("div", id="buybox")
                    
                    if buybox:
                        bb_text = buybox.get_text(separator=" ", strip=True)
                        shipper_val, seller_val = "N/A", "N/A"
                        
                        if "Shipper / Seller" in bb_text:
                            match = re.search(r'Shipper / Seller\s+(.*?)(?:\s+Returns|\s+Payment|\s+Details|$)', bb_text)
                            if match:
                                shipper_val = seller_val = match.group(1).strip()
                        
                        elif "Ships from" in bb_text and "Sold by" in bb_text:
                            shipper_match = re.search(r'Ships from\s+(.*?)(?:\s+Sold by|\s+Returns|\s+Payment|$)', bb_text)
                            if shipper_match: shipper_val = shipper_match.group(1).strip()
                            
                            seller_match = re.search(r'Sold by\s+(.*?)(?:\s+Returns|\s+Payment|\s+Details|$)', bb_text)
                            if seller_match: seller_val = seller_match.group(1).strip()
                            
                        if "Ships from and sold by Amazon" in bb_text:
                            shipper_val = seller_val = "Amazon.ca"

                        if "Amazon" in shipper_val: shipper_val = "Amazon.ca"
                        if "Amazon" in seller_val: seller_val = "Amazon.ca"

                        deal["shipper"] = shipper_val
                        deal["seller"] = seller_val
                        
                except Exception as e:
                    print(f"  ⚠️ Could not load Shipper/Seller info for {deal['title'][:30]}: {e}")

        print(f"\n--- Scrape Complete for {keyword if keyword else 'All LEGO'} ---")
        print(f"✅ Unique products found with ≥{min_discount_percent}% discount: {len(all_discounted_products)}")
        return all_discounted_products

    except Exception as e:
        print(f"An unexpected error occurred during scraping: {e}")
        return []
    finally:
        if driver:
            driver.quit()

def main():
    print("🔎 Amazon LEGO Discount Scraper (GitHub Actions Edition)")
    
    min_discount_percent = 20
    min_original_price = 10
    amazon_tag = os.getenv('AMAZON_TAG', '')

    themes = load_lego_themes()
    master_deal_list = []
    
    for theme in themes:
        display_name = theme if theme else "All LEGO"
        print(f"\n{'='*50}")
        print(f"🚀 STARTING SEARCH FOR: {display_name.upper()}")
        print(f"{'='*50}")
        
        found_deals = scrape_amazon_lego_selenium(keyword=theme, 
                                                  min_discount_percent=min_discount_percent, 
                                                  min_original_price=min_original_price,
                                                  amazon_tag=amazon_tag)
        if found_deals:
            master_deal_list.extend(found_deals)
            
        time.sleep(5) 

    # --- 1 & 2. Filter Amazon.ca and Deduplicate ---
    unique_deals = {}
    for deal in master_deal_list:
        # Require BOTH Shipper and Seller to be Amazon.ca
        if deal.get("shipper") != "Amazon.ca" or deal.get("seller") != "Amazon.ca":
            continue
            
        # Deduplicate using the ASIN as the unique identifier
        asin = extract_asin(deal["raw_link"])
        if asin not in unique_deals:
            unique_deals[asin] = deal
            
    # --- 3. State Table Management ---
    STATE_FILE = "state_amazon_lego.json"
    old_state = {}
    
    # Load previous run state
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                old_state = json.load(f)
        except json.JSONDecodeError:
            pass

    final_email_deals = []
    new_state = {}

    # Compare current deals against old state (New, Price Changed, Unchanged)
    for asin, deal in unique_deals.items():
        if asin not in old_state:
            deal["status_change"] = "New"
        else:
            old_deal = old_state[asin]
            if deal["current_price"] != old_deal["current_price"]:
                deal["status_change"] = "Price Changed"
            else:
                deal["status_change"] = "" # Unchanged
        
        final_email_deals.append(deal)
        
        # Save to new state table
        new_state[asin] = {
            "title": deal["title"],
            "current_price": deal["current_price"],
            "original_price": deal["original_price"],
            "discount": deal["discount"],
            "link": deal["link"],
            "theme": deal["theme"],
            "shipper": deal["shipper"],
            "seller": deal["seller"]
        }

    # Handle Removed items
    for asin, old_deal in old_state.items():
        if asin not in unique_deals:
            old_deal["status_change"] = "Removed"
            final_email_deals.append(old_deal)
            # Purposely omitting this from new_state so it doesn't persist

    # Save the new state back to the JSON file
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(new_state, f, indent=4)

    # Sort final output by discount size
    if final_email_deals:
        final_email_deals.sort(key=lambda x: x.get("discount", 0), reverse=True)
    
    # --- 4. Send Email Report ---
    send_email_report(final_email_deals)

if __name__ == "__main__":
    main()
