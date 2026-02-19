import time
import re
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, ElementClickInterceptedException

def extract_price(text):
    """Extracts a float price from a text string, handling commas and currency symbols."""
    clean_text = text.replace('CDN$', '').replace('$', '').replace(',', '').strip()
    match = re.search(r'(\d+\.?\d*)', clean_text)
    return float(match.group(1)) if match else None

def build_search_url(keyword: str) -> str:
    """
    Build the Amazon.ca search URL for LEGO products filtered by brand,
    optionally with a keyword to narrow down.
    """
    base_url = "https://www.amazon.ca/s"
    params = {
        "i": "toys-and-games",
        "rh": "p_89:LEGO", # Filters by LEGO brand
    }
    if keyword:
        kw_encoded = keyword.strip().replace(' ', '+')
        params["k"] = f"lego+{kw_encoded}"
    else:
        params["k"] = "lego"

    query = "&".join(f"{key}={value}" for key, value in params.items())
    url = f"{base_url}?{query}"
    return url

def scrape_amazon_lego_selenium(keyword="", min_discount_percent="", min_original_price=""):
    options = uc.ChromeOptions()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

    driver = uc.Chrome(options=options, version_main=144)
    all_discounted_products = []
    page_number = 1
    max_retries = 3 

    try:
        url = build_search_url(keyword)
        print("🍪 Warming up session cookies to bypass WAF...")
        
        # --- NEW: Warm-up Phase ---
        driver.get("https://www.amazon.ca")
        time.sleep(6) # Let the homepage load fully
        
        # Simulate human behavior by scrolling slightly
        driver.execute_script("window.scrollBy(0, 700);")
        time.sleep(3)
        
        print(f"🔍 Now navigating to target URL: {url}")

        # --- Initial Page Load with Retry Logic ---
        initial_load_successful = False
        for attempt in range(max_retries):
            driver.get(url)
            time.sleep(6) # Increased wait for the actual search page

            # Handle initial cookie banner (common on first load)
            try:
                WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.ID, "sp-cc-accept"))
                ).click()
                print(f"✅ Accepted initial cookies (Attempt {attempt + 1}).")
                time.sleep(2)
            except (TimeoutException, NoSuchElementException):
                pass 

            # Check if the "Something went wrong" page is displayed
            if "Something went wrong" in driver.page_source or "Sorry!" in driver.title or "captcha" in driver.current_url.lower():
                print(f"⚠️ 'Something went wrong' or CAPTCHA detected on attempt {attempt + 1}. Refreshing...")
                driver.refresh() 
                time.sleep(7) 
            else:
                # Try to detect if product results are present
                try:
                    WebDriverWait(driver, 10).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, "div[data-component-type='s-search-result']"))
                    )
                    print(f"✅ Initial product results detected on attempt {attempt + 1}.")
                    initial_load_successful = True
                    break 
                except TimeoutException:
                    print(f"❌ Products not detected on initial load attempt {attempt + 1}. Retrying...")
                    driver.refresh()
                    time.sleep(6)

        if not initial_load_successful:
            print(f"❌ Failed to load initial search results after {max_retries} attempts. Aborting.")
            return [] 
        # --- END Initial Page Load ---

        # --- Scraping Loop ---
        while True:
            print(f"\n--- Scraping Page {page_number} ---")

            try:
                banner_accept_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, '#cos-banner [name="accept"]'))
                )
                banner_accept_button.click()
                print("✅ Accepted 'cos-banner' (likely a privacy consent form).")
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
                print(f"❌ Products lost or not visible on page {page_number} after scroll. Ending scrape for this path.")
                break

            soup = BeautifulSoup(driver.page_source, "lxml")
            products = soup.find_all("div", {"data-component-type": "s-search-result"})

            if not products:
                print(f"No product containers found in HTML on page {page_number}. Ending scrape.")
                break

            print(f"✅ Found {len(products)} potential search results on page {page_number}.")

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

                    if title != "N/A" and link != "N/A" and "slredirect.amazon.ca" not in link and "N/A" not in title:
                        if discount >= min_discount_percent and original_price >= min_original_price:
                            all_discounted_products.append({
                                "title": title,
                                "current_price": current_price,
                                "original_price": original_price,
                                "discount": discount,
                                "link": link
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
                print(f"Clicking 'Next' button to go to page {page_number + 1}...")
                next_button.click()
                page_number += 1
                time.sleep(4)
            else:
                print("No more pages or 'Next' button disabled. Ending pagination.")
                break

        print(f"\n--- Scrape Complete ---")
        print(f"✅ Total unique products found with ≥{min_discount_percent}% discount across all pages: {len(all_discounted_products)}")

        all_discounted_products.sort(key=lambda x: x["discount"], reverse=True)

        for idx, prod in enumerate(all_discounted_products, 1):
            print(f"\n[{idx}] {prod['title']}")
            print(f"    💰 Current: ${prod['current_price'] if prod['current_price'] is not None else 'N/A'}")
            print(f"    🏷️ Original: ${prod['original_price'] if prod['original_price'] is not None else 'N/A'}")
            print(f"    🔻 Discount: {prod['discount']}%")
            print(f"    🔗 {prod['link']}")
            print("-" * 60)

        if not all_discounted_products:
            print(f"❌ No LEGO products found with ≥{min_discount_percent}% discount across all pages.")

    except Exception as e:
        print(f"An unexpected error occurred during scraping: {e}")
    finally:
        if driver:
            driver.quit()
            print("Browser closed.")

def main():
    print("🔎 Amazon LEGO Discount Scraper (All Pages)")
    keyword = ''
    min_discount_percent = 25
    min_original_price = 50

    scrape_amazon_lego_selenium(keyword, min_discount_percent, min_original_price)

if __name__ == "__main__":
    main()
