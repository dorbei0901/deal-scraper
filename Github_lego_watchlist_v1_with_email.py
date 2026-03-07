#!/usr/bin/env python
# coding: utf-8

# In[2]:


#!/usr/bin/env python
# coding: utf-8

import time
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
from selenium.common.exceptions import NoSuchElementException, TimeoutException

def extract_price(text):
    """Extracts a float price from a text string, handling commas and currency symbols."""
    clean_text = text.replace('CDN$', '').replace('$', '').replace(',', '').strip()
    match = re.search(r'(\d+\.?\d*)', clean_text)
    return float(match.group(1)) if match else None

def build_search_url(keyword: str) -> str:
    base_url = "https://www.amazon.ca/s"
    if keyword:
        kw_encoded = keyword.strip().replace(' ', '+')
        query = f"k=lego+{kw_encoded}&rh=p_89%3ALEGO"
    else:
        query = "k=lego&rh=p_89%3ALEGO"
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

def scrape_single_lego_set(lego_number, amazon_tag=""):
    """Searches for a specific LEGO number and returns its details."""
    options = uc.ChromeOptions()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

    driver = uc.Chrome(options=options, version_main=144)
    max_retries = 3 
    
    result_deal = {
        "title": "Not Found / Out of Stock",
        "lego_number": lego_number,
        "current_price": None,
        "original_price": None,
        "discount": 0.0,
        "shipper": "N/A",
        "seller": "N/A",
        "link": build_search_url(lego_number)
    }

    try:
        url = result_deal["link"]
        driver.get("https://www.amazon.ca")
        time.sleep(4) 
        driver.execute_script("window.scrollBy(0, 500);")
        time.sleep(2)
        
        initial_load_successful = False
        for attempt in range(max_retries):
            driver.get(url)
            time.sleep(5) 

            try:
                WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.ID, "sp-cc-accept"))
                ).click()
                time.sleep(1)
            except:
                pass 

            if "Something went wrong" in driver.page_source or "captcha" in driver.current_url.lower():
                driver.refresh() 
                time.sleep(6) 
            else:
                try:
                    WebDriverWait(driver, 8).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, "div[data-component-type='s-search-result']"))
                    )
                    initial_load_successful = True
                    break 
                except TimeoutException:
                    driver.refresh()
                    time.sleep(5)

        if not initial_load_successful:
            print(f"❌ Failed to load search page for {lego_number}.")
            return result_deal

        soup = BeautifulSoup(driver.page_source, "html.parser")
        products = soup.find_all("div", {"data-component-type": "s-search-result"})

        for item in products[:5]:
            title_text = "N/A"
            link = url
            
            link_tag = item.find("a", class_="a-link-normal s-line-clamp-4 s-link-style a-text-normal")
            if link_tag:
                title_tag = link_tag.find("h2")
                title_text = title_tag.get_text(strip=True) if title_tag else "N/A"
                link = "https://www.amazon.ca" + link_tag.get("href", "")
            else: 
                title_h2 = item.find("h2")
                if title_h2:
                    link_tag_fallback = title_h2.find("a", class_="a-link-normal")
                    if link_tag_fallback:
                        title_span = link_tag_fallback.find("span", class_="a-text-normal")
                        title_text = title_span.get_text(strip=True) if title_span else "N/A"
                        relative_link = link_tag_fallback.get("href", "")
                        link = "https://www.amazon.ca" + relative_link if not relative_link.startswith("http") else relative_link

            # Validate it's the right item
            if lego_number in title_text:
                # AMENDMENT 1: Trim the name before " - "
                if " - " in title_text:
                    title_text = title_text.split(" - ")[0].strip()
                
                result_deal["title"] = title_text
                
                # Format affiliate link
                if amazon_tag and "slredirect.amazon.ca" not in link:
                    separator = "&" if "?" in link else "?"
                    result_deal["link"] = f"{link}{separator}tag={amazon_tag}"
                else:
                    result_deal["link"] = link

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

                # AMENDMENT 2: Visit the product page to get Shipper & Seller
                try:
                    driver.get(link)
                    time.sleep(3)
                    prod_soup = BeautifulSoup(driver.page_source, "html.parser")
                    
                    # Look for the newer tabular buy box layout
                    ships_from_div = prod_soup.find("div", {"tabular-attribute-name": "Ships from"})
                    if ships_from_div:
                        val = ships_from_div.find_next_sibling("div")
                        if val: result_deal["shipper"] = val.get_text(strip=True)
                        
                    sold_by_div = prod_soup.find("div", {"tabular-attribute-name": "Sold by"})
                    if sold_by_div:
                        val = sold_by_div.find_next_sibling("div")
                        if val: result_deal["seller"] = val.get_text(strip=True)
                        
                    # Fallback for the older text-based buy box
                    if result_deal["shipper"] == "N/A" and result_deal["seller"] == "N/A":
                        merchant_info = prod_soup.find("div", id="merchant-info")
                        if merchant_info:
                            merchant_text = merchant_info.get_text(separator=" ", strip=True)
                            if "Ships from and sold by Amazon.ca" in merchant_text:
                                result_deal["shipper"] = "Amazon.ca"
                                result_deal["seller"] = "Amazon.ca"
                            else:
                                result_deal["seller"] = merchant_text[:40] + "..." # Captures third-party details
                except Exception as e:
                    print(f"  ⚠️ Could not load Shipper/Seller info for {lego_number}: {e}")

                print(f"✅ Found {lego_number}: {result_deal['title'][:40]}... | Discount: {result_deal['discount']}% | Seller: {result_deal['seller']}")
                break 

        return result_deal

    except Exception as e:
        print(f"Error processing {lego_number}: {e}")
        return result_deal
    finally:
        if driver:
            driver.quit()

def main():
    print("🔎 Amazon LEGO Watchlist Scraper (GitHub Actions Edition)")
    
    amazon_tag = os.getenv('AMAZON_TAG', '')
    lego_numbers = load_lego_watchlist()
    master_watchlist_deals = []
    
    for number in lego_numbers:
        print(f"\n🚀 Checking Watchlist: LEGO {number}")
        
        deal = scrape_single_lego_set(lego_number=number, amazon_tag=amazon_tag)
        master_watchlist_deals.append(deal)
            
        time.sleep(3)

    if master_watchlist_deals:
        master_watchlist_deals.sort(key=lambda x: x["discount"], reverse=True)
    
    send_email_report(master_watchlist_deals)

if __name__ == "__main__":
    main()


# In[ ]:




