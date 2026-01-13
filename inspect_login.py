"""Inspect the actual login form to see what fields are required"""
import requests
from bs4 import BeautifulSoup

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
})

# Step 1: Get redirected to identity server
print("Step 1: Accessing app login page...")
response = session.get("https://tempapp-su.awrosoft.com/Account/Login", allow_redirects=True)
print(f"Final URL: {response.url}")

# Step 2: Parse the login form
print("\nStep 2: Analyzing login form...")
soup = BeautifulSoup(response.text, 'html.parser')

form = soup.find('form')
if form:
    print(f"\nForm action: {form.get('action')}")
    print(f"Form method: {form.get('method')}")
    
    print("\nAll input fields:")
    for input_tag in form.find_all('input'):
        input_type = input_tag.get('type', 'text')
        input_name = input_tag.get('name', 'NO_NAME')
        input_value = input_tag.get('value', '')
        print(f"  - {input_name} (type={input_type}, value='{input_value[:50]}')")
    
    print("\nAll button fields:")
    for button in form.find_all('button'):
        button_name = button.get('name', 'NO_NAME')
        button_value = button.get('value', '')
        button_text = button.get_text(strip=True)
        print(f"  - {button_name} = '{button_value}' (text: {button_text})")
else:
    print("ERROR: No form found!")
    print(f"\nPage title: {soup.title.string if soup.title else 'No title'}")
    print(f"\nPage content preview:\n{response.text[:1000]}")
