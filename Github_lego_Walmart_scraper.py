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
    """Extracts price from a specific HTML element."""
    if not element:
        return None
    aria = element.get('aria-label')
    if aria and '$' in aria:
        match = re.search(r'\$\s*(\d+\.?\d*)', aria)
        if match: 
            return float(match.group(1))
    text = element.get_text(separator=".", strip=True)
    clean_text = re.sub(r'[^\d\.]', '', text)
    match = re.search(r'(\d+\.\d{2})', clean_text)
    if match: return float(match.group(1))
    match2 = re.search(r'(\d+)', clean_text)
    if match2: return float(match2.group(1))
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
    <style
