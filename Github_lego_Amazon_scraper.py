#!/usr/bin/env python
# coding: utf-8

import time
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

def build_search_url(keyword: str, page: int = 1) -> str:
    base_url = "https://www.amazon.ca/s"
    # p_89%3ALEGO = Brand: LEGO
    # p_6%3AA3DWYIK6Y9EEQB = Seller: Amazon.ca
    merchant_filter = "%2Cp_6%3AA3DWYIK6Y9EEQB"
    
    if keyword:
        kw_encoded = keyword.strip().replace(' ', '+')
        query = f"k=lego+{kw_encoded}&rh=p_89%3ALEGO{merchant_filter}&page={page}"
    else:
        query = f"k=lego&rh=p_89%3ALEGO{merchant_filter}&page={page}"
    return f"{base_url}?{query}"

def load_lego_themes(filename="legoproduct.txt"):
    if not os.path.exists(filename):
        print(f"⚠️ {filename} not found in the repository. Defaulting to general LEGO search.")
        return [""] 
    with open(filename, "r", encoding="utf-8") as file:
        themes = [line.strip() for line in file if line.strip()]
    return themes if themes else [""]

def send_email_report(deals):
    """Generates an HTML table for each Product Type and sends it via email securely."""
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

    # Group deals by theme (Product Type)
    grouped_deals = {}
    for deal in deals:
        theme = deal.get("theme", "General LEGO").title()
        if theme not in grouped_deals:
            grouped_deals[theme] = []
        grouped_deals[theme].append(deal)

    # Start building the HTML
    html = """
    <html>
    <head>
    <style>
      body { font-family: Arial, sans-serif; }
      table { border-collapse: collapse; width: 100%; margin-bottom: 30px; }
      th, td { text-align: left; padding: 8px; border: 1px solid #ddd; }
      th { background-color: #f2f2f2; color: #333; }
      a { color: #0066c0; text-decoration: none; font-weight: bold; }
      a:hover { text-decoration: underline; }
      h2 { color: #232f3e; }
      h3 { color: #0066c0; border-bottom: 2px solid #0066c0; padding-bottom: 5px; margin-top: 20px;}
    </style>
    </head>
    <body>
    <h2>Daily LEGO Deals Report</h2>
    <p>Total Deals Found: <strong>{total}</strong></p>
    """.replace("{total}", str(len(deals)))
    
    # Iterate through each group and create a separate table
    for theme, theme_deals in sorted(grouped_deals.items()):
        html += f"<h3>{theme} ({len(theme_deals)} Deals)</h3>"
        html += """
        <table>
          <tr>
            <th>Product Name</th>
            <th>Current</th>
            <th>Original</th>
            <th>Discount</th>
            <th>Shipper</th>
            <th>Seller</th>
            <th>Status Change</th>
            <th>Amazon Link</th>
          </tr>
        """
        
        for deal in theme_deals:
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
        """

    html += """
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
        print(f"✅ Email successfully sent to {recipient_email} with grouped tables.")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

def scrape_amazon_lego_curl(session, keyword="", min_discount_percent=30.0, min_original_price=50.0, amazon_tag=""):
    all_discounted_products = []
    page_number = 1
    
    while True:
        url = build_search_url(keyword, page_number)
        print(f"🔍 Scraping Page {page_number}: {url}")
        
        # Update Referer to simulate sequential browsing
        if page_number > 1:
            session.headers.update({"Referer": build_search_url(keyword, page_number - 1)})
        else:
            session.headers.update({"Referer": "https://www.amazon.ca/"})
        
        try:
            response = session.get(url, timeout=15)
            
            if response.status_code == 503 or "captcha" in response.url.lower():
                print(f"⚠️ WAF Block triggered on page {page_number}. Amazon is aggressively blocking the IP.")
                break

            soup = BeautifulSoup(response.content, "lxml")
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
                                "shipper": "Amazon.ca", 
                                "seller": "Amazon.ca",  
                                "theme": keyword if keyword else "General LEGO" 
                            })

                except Exception as e:
                    continue

            next_button = soup.find("a", class_="s-pagination-next")
            if next_button and "s-pagination-disabled" not in next_button.get("class", []):
                page_number += 1
                time.sleep(3) 
            else:
                break

        except Exception as e:
            print(f"An error occurred on page {page_number}: {e}")
            break

    print(f"\n--- Scrape Complete for {keyword if keyword else 'All LEGO'} ---")
    print(f"✅ Unique products found with ≥{min_discount_percent}% discount: {len(all_discounted_products)}")
    return all_discounted_products

def main():
    print("🔎 Amazon LEGO Discount Scraper (curl-cffi Edition - WAF Optimized)")
    
    min_discount_percent = 20
    min_original_price = 50
    amazon_tag = os.getenv('AMAZON_TAG', '')

    themes = load_lego_themes()
    master_deal_list = []
    
    # Initialize the session and establish base headers
    session = requests.Session(impersonate="chrome116")
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    })

    print("🍪 Warming up session with Amazon.ca homepage to collect AWS WAF tokens...")
    try:
        session.get("https://www.amazon.ca", timeout=15)
        time.sleep(4)
    except Exception as e:
        print(f"⚠️ Homepage warmup failed: {e}")
    
    for theme in themes:
        display_name = theme if theme else "All LEGO"
        print(f"\n{'='*50}")
        print(f"🚀 STARTING SEARCH FOR: {display_name.upper()}")
        print(f"{'='*50}")
        
        found_deals = scrape_amazon_lego_curl(session=session,
                                              keyword=theme, 
                                              min_discount_percent=min_discount_percent, 
                                              min_original_price=min_original_price,
                                              amazon_tag=amazon_tag)
        if found_deals:
            master_deal_list.extend(found_deals)
            
        time.sleep(4) 

    unique_deals = {}
    for deal in master_deal_list:
        asin = extract_asin(deal["raw_link"])
        if asin not in unique_deals:
            unique_deals[asin] = deal
            
    STATE_FILE = "state_amazon_lego.json"
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
            "current_price": deal["current_price"],
            "original_price": deal["original_price"],
            "discount": deal["discount"],
            "link": deal["link"],
            "theme": deal["theme"],
            "shipper": deal["shipper"],
            "seller": deal["seller"]
        }

    for asin, old_deal in old_state.items():
        if asin not in unique_deals:
            old_deal["status_change"] = "Removed"
            final_email_deals.append(old_deal)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(new_state, f, indent=4)

    if final_email_deals:
        final_email_deals.sort(key=lambda x: x.get("discount", 0), reverse=True)
    
    send_email_report(final_email_deals)

if __name__ == "__main__":
    main()
