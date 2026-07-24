import requests
from bs4 import BeautifulSoup

def fetch_api_data():
    # 1. Initialize the session
    session = requests.Session()
    
    # Establish base headers for the entire session
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br"
    })

    homepage_url = "https://www.costco.ca/"
    api_endpoint = "https://gdx-api.costco.com/catalog/product/dispprice-api/v2/display-price?whsNumber=894&clientId=e442e6e6-2602-4a39-937b-8b28b4457ed3&item=5350093&country=CA&locale=en-ca&state=BC&zipCode=V3E+0T2"

    try:
        # 2. The Handshake: Hit the homepage to grab Akamai/Session cookies
        print(f"Pinging {homepage_url} for initial cookies...")
        homepage_response = session.get(homepage_url, timeout=15)
        homepage_response.raise_for_status()
        
        # Look at the cookies automatically captured by the session
        print("Captured Cookies:", session.cookies.get_dict())

        # 3. Token Extraction (Optional, but common)
        # Sometimes APIs require a specific token passed in the header, 
        # which is often hidden in the homepage HTML as a meta tag.
        soup = BeautifulSoup(homepage_response.text, 'html.parser')
        csrf_token_tag = soup.find('meta', {'name': 'csrf-token'})
        
        if csrf_token_tag:
            custom_token = csrf_token_tag.get('content')
            # Inject the extracted token into the session's headers
            session.headers.update({"X-CSRF-Token": custom_token})
            print("Extracted and applied custom token.")

        # 4. The Target Request
        # The session will automatically attach the cookies from step 2 
        # and the updated headers from step 3.
        print(f"Requesting data from {api_endpoint}...")
        
        # We add headers specific to this API call (e.g., expecting JSON)
        api_headers = {
            "Accept": "application/json",
            "Referer": "https://www.costco.ca/",
            "x-api-key": "134a4023-68d5-4138-8e03-8353667d5fb3" # The key you found
        }
        
        api_response = session.get(api_endpoint, headers=api_headers, timeout=15)
        api_response.raise_for_status()
        
        # Process the JSON payload
        data = api_response.json()
        print("Success! Data retrieved:")
        print(data)

    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error occurred: {e}")
        print(f"Response Body: {e.response.text}")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    fetch_api_data()
