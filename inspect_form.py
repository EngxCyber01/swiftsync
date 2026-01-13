"""
Inspect the actual login form to find correct field names
"""
import requests
from bs4 import BeautifulSoup

login_url = "https://tempids-su.awrosoft.com/account/login"

print("🔍 Fetching login page...\n")
response = requests.get(login_url)

if response.status_code == 200:
    soup = BeautifulSoup(response.text, "html.parser")
    
    # Find the form
    form = soup.find("form")
    if form:
        print("✅ Found login form\n")
        print("📋 Form inputs:")
        print("="*60)
        
        for input_tag in form.find_all("input"):
            name = input_tag.get("name", "")
            input_type = input_tag.get("type", "text")
            value = input_tag.get("value", "")
            
            if name:
                if input_type == "hidden":
                    print(f"  🔒 {name:30} = {value[:50]}")
                else:
                    print(f"  📝 {name:30} (type: {input_type})")
        
        print("\n" + "="*60)
        print("\n💡 Use these field names in auth.py payload!")
    else:
        print("❌ No form found")
        print(f"\nPage content:\n{response.text[:1000]}")
else:
    print(f"❌ Failed to fetch page: {response.status_code}")
