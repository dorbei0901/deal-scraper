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
    clean_text = text.replace('CDN$', '').replace('$', '').replace(',', '').strip()
    match = re.search(r'(\d+\.?\d*)', clean_text)
    return float(match.group(1)) if match else None

def load_lego_themes(filename="legoproductTest.txt"):
    if not os.path.exists(filename):
        print(f"⚠️ {filename} not found in the repository. Defaulting to general LEGO search.")
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
        print("\n⚠️ Missing email credentials or recipient email in GitHub Secrets. Skipping email delivery.")
        return

    if not deals:
        print("\n📭 No deals found today to email.")
        return

    print(f"\n📧 Formatting {len(deals)} Walmart deals into an email report for {recipient_email}...")

    html = """
    <html>
    <head>
    <style>
      table { border-collapse: collapse; width: 100%; font-family: Arial, sans-serif; }
      th, td { text-align: left; padding: 8px; border: 1px solid #ddd; }
      th { background-color: #f2f2f2; color: #0071ce; } 
      tr:nth-child(even) {background-color: #f9f9f9;}
      a { color: #0066c0; text-decoration: none; font-weight: bold; }
      a:hover { text-decoration: underline; }
    </style>
    </head>
    <body>
    <h2>Daily Walmart LEGO Deals Report</h2>
    <table>
      <tr>
        <th style="color: white;">Product Name</th>
        <th style="color: white;">Product Type</th>
        <th style="color: white;">Current</th>
        <th style="color: white;">Original</th>
        <th style="color: white;">Discount</th>
        <th style="color: white;">Shipper</th>
        <th style="color: white;">Seller</th>
        <th style="color: white;">Walmart Link</th>
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
        <td>{deal.get('shipper', 'N/A')}</td>
        <td>{deal.get('seller', 'N/A')}</td>
        <td><a href="{deal['link']}">View Deal</a></td>
      </tr>
        """
        
    html += """
    </table>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Walmart LEGO Deals - {len(deals)} Great Discounts Found!"
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

def human_like_scroll(driver):
    for _ in range(random.randint(3, 6)):
        scroll_amount = random.randint(200, 600)
        driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
        time.sleep(random.uniform(0.7, 2.0))

def create_stealth_driver():
    """Generates a fresh browser with randomized stealth parameters to beat 403 Forbidden blocks."""
    options = uc.ChromeOptions()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    # Randomize viewport size
    width = random.choice([1366, 1440, 1536, 1920])
    height = random.choice([768, 900, 864, 1080])
    options.add_argument(f"--window-size={width},{height}")
    
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-popup-blocking")
    
    # Randomize User-Agent slightly to avoid fingerprinting
    chrome_versions = ["120.0.0.0", "121.0.0.0", "122.0.0.0", "123.0.0.0"]
    v = random.choice(chrome_versions)
    options.add_argument(f"--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v} Safari/537.36")

    driver = uc.Chrome(options=options, version_main=146)
    
    # Inject JavaScript to hide webdriver flags
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """
    })
    return driver

def scrape_walmart_lego_selenium(keyword="", min_discount_percent=30.0, min_original_price=50.0):
    driver = create_stealth_driver()
    all_discounted_products = []
    page_number = 1
    max_pages = 4 
    
    try:
        print("🍪 Warming up session cookies to bypass Walmart WAF...")
        driver.get("https://www.walmart.ca")
        time.sleep(random.uniform(6, 10)) 
        human_like_scroll(driver)
        
        while page_number <= max_pages:
            kw_encoded = keyword.strip().replace(' ', '+') if keyword else ""
            url = f"https://www.walmart.ca/en/search?q=lego+{kw_encoded}&page={page_number}"
            
            print(f"\n🔍 Navigating to: {url}")
            
            page_loaded_successfully = False
            for px_attempt in range(4): # Increased retry limit
                driver.get(url)
                time.sleep(random.uniform(7, 12)) 

                page_text = driver.page_source
                
                # Check for Hard 403 Forbidden OR Soft Captcha
                if "Forbidden" in page_text[:500] or "Press & Hold" in page_text or "px-captcha" in page_text:
                    print(f"⚠️ WAF Block (Forbidden/Captcha) on attempt {px_attempt + 1}. Rebooting browser session...")
                    driver.quit() # Completely destroy the burned browser
                    time.sleep(random.uniform(10, 20)) # Wait out the throttle
                    driver = create_stealth_driver() # Rebuild with new fingerprint
                    driver.get("https://www.walmart.ca") # Rewarm
                    time.sleep(5)
                else:
                    page_loaded_successfully = True
                    break 

            if not page_loaded_successfully:
                print(f"❌ Network permanently blocked by Walmart WAF. Skipping page {page_number}.")
                page_number += 1
                continue

            try:
                WebDriverWait(driver, 10).until(
                    lambda d: d.find_elements(By.CSS_SELECTOR, 'a[href*="/ip/"]') or \
                              d.find_elements(By.CSS_SELECTOR, '[data-automation="product"]')
                )
            except TimeoutException:
                pass # Continue anyway, the DOM might just be slow

            human_like_scroll(driver)

            soup = BeautifulSoup(driver.page_source, "html.parser")
            product_links = soup.find_all("a", href=lambda href: href and ("/ip/" in href or "/en/ip/" in href))
            
            print(f"🛠️ [DEBUG] Total /ip/ product links found on Page {page_number}: {len(product_links)}")
            
            if not product_links:
                print("🛠️ [DEBUG] No links found. Walmart served an empty grid.")
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

                if not parent: continue

                title_text = link.get_text(strip=True)
                if not title_text or len(title_text) < 5 or "lego" not in title_text.lower():
                    img = link.find("img")
                    title_text = img.get("alt", "") if img else ""
                    if not title_text:
                        continue

                current_price = None
                original_price = None

                curr_elem = parent.find(attrs={"data-automation": "current-price"})
                orig_elem = parent.find(attrs={"data-automation": "strike-through-price"})

                if curr_elem:
                    current_price = extract_price(curr_elem.get_text(strip=True))
                
                if orig_elem:
                    original_price = extract_price(orig_elem.get_text(strip=True))

                if current_price is None:
                    text_content = parent.get_text(separator=" ", strip=True)
                    prices = re.findall(r'\$\d+\.\d{2}|\$\d+', text_content)
                    unique_prices = []
                    for p in prices:
                        val = extract_price(p)
                        if val and val not in unique_prices:
                            unique_prices.append(val)

                    if len(unique_prices) >= 2:
                        unique_prices.sort()
                        current_price = unique_prices[0]
                        original_price = unique_prices[-1]
                    elif len(unique_prices) == 1:
                        current_price = unique_prices[0]
                        original_price = current_price

                debug_discount = 0.0
                if current_price and original_price and original_price > current_price:
                    debug_discount = round(((original_price - current_price) / original_price) * 100, 1)

                short_title = (title_text[:45] + '...') if len(title_text) > 45 else title_text
                print(f"👀 [RAW] {short_title:<48} | Curr: {format_price(current_price):<8} | Orig: {format_price(original_price):<8} | Disc: {debug_discount}%")

                if current_price and original_price and original_price > current_price:
                    discount = round(((original_price - current_price) / original_price) * 100, 1)

                    if discount >= min_discount_percent and original_price >= min_original_price:
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
                            "shipper": "N/A",
                            "seller": "N/A",
                            "theme": keyword if keyword else "General LEGO" 
                        })

            page_number += 1

        final_verified_deals = []
        
        if all_discounted_products:
            print(f"\n📦 Fetching Seller info for {len(all_discounted_products)} qualified items (Walmart Only)...")
            
            for deal in all_discounted_products:
                try:
                    driver.get(deal["raw_link"])
                    time.sleep(random.uniform(5, 9)) 
                    
                    page_text = driver.page_source
                    if "Forbidden" in page_text[:500] or "Press & Hold" in page_text or "px-captcha" in page_text:
                        print(f"  ⚠️ Bot block hit on product page for {deal['title'][:20]}... Skipping item.")
                        continue

                    prod_soup = BeautifulSoup(page_text, "html.parser")
                    clean_page_text = prod_soup.get_text(separator=" ", strip=True)
                    
                    curr_elem = prod_soup.find(attrs={"data-automation": "buybox-price"})
                    orig_elem = prod_soup.find(attrs={"data-automation": "strike-through-price"})

                    if curr_elem:
                        new_curr = extract_price(curr_elem.get_text(strip=True))
                        if new_curr: deal["current_price"] = new_curr

                    if orig_elem:
                        new_orig = extract_price(orig_elem.get_text(strip=True))
                        if new_orig: deal["original_price"] = new_orig

                    if deal["original_price"] > deal["current_price"]:
                        deal["discount"] = round(((deal["original_price"] - deal["current_price"]) / deal["original_price"]) * 100, 1)

                    match = re.search(r'Sold and shipped by\s+([^\\.\n]*?)(?:\s+Fulfilled by|\s+Return|\s+Free delivery|$)', clean_page_text)
                    if match:
                        seller_val = match.group(1).strip()
                        seller_val = re.sub(r'\|.*', '', seller_val).strip() 
                        deal["shipper"] = seller_val
                        deal["seller"] = seller_val
                    elif "Sold by Walmart" in clean_page_text or "shipped by Walmart" in clean_page_text:
                        deal["shipper"] = "Walmart.ca"
                        deal["seller"] = "Walmart.ca"
                    else:
                        seller_elem = prod_soup.find(attrs={"data-automation": "seller-name"})
                        if seller_elem:
                            deal["shipper"] = seller_elem.get_text(strip=True)
                            deal["seller"] = seller_elem.get_text(strip=True)

                    if "Walmart" in deal["shipper"]: deal["shipper"] = "Walmart.ca"
                    if "Walmart" in deal["seller"]: deal["seller"] = "Walmart.ca"

                    if deal["seller"] != "Walmart.ca":
                        print(f"❌ Dropped: {deal['title'][:40]}... (Sold by 3rd Party: {deal['seller']})")
                        continue

                    if deal["discount"] >= min_discount_percent:
                        final_verified_deals.append(deal)
                        print(f"✅ Verified: {deal['title'][:40]}... | Discount: {deal['discount']}% | Seller: Walmart")
                    else:
                        print(f"❌ Dropped: {deal['title'][:40]}... (Discount fell to {deal['discount']}%)")

                except Exception as e:
                    print(f"  ⚠️ Could not load Shipper/Seller info: {e}")

        print(f"\n--- Scrape Complete for {keyword if keyword else 'All LEGO'} ---")
        return final_verified_deals

    except Exception as e:
        print(f"An unexpected error occurred during scraping: {e}")
        return []
    finally:
        if driver:
            driver.quit()

def main():
    print("🔎 Walmart LEGO Discount Scraper (GitHub Actions Edition)")
    
    min_discount_percent = 30.0 
    min_original_price = 50.0

    themes = load_lego_themes()
    master_deal_list = []
    
    for theme in themes:
        display_name = theme if theme else "All LEGO"
        print(f"\n{'='*50}")
        print(f"🚀 STARTING WALMART SEARCH FOR: {display_name.upper()}")
        print(f"{'='*50}")
        
        found_deals = scrape_walmart_lego_selenium(keyword=theme, 
                                                   min_discount_percent=min_discount_percent, 
                                                   min_original_price=min_original_price)
        if found_deals:
            master_deal_list.extend(found_deals)
            
        time.sleep(random.uniform(5, 8)) 

    if master_deal_list:
        master_deal_list.sort(key=lambda x: x["discount"], reverse=True)
    
    send_email_report(master_deal_list)

if __name__ == "__main__":
    main()
