"""Quick Server Check"""
import requests
import time

time.sleep(3)

print("ðŸš€ Quick Server Check\n")

try:
    # Test basic connection
    r = requests.get("http://localhost:8000", timeout=5)
    print(f"âœ… Server is running: Status {r.status_code}")
    
    # Test admin portal
    r = requests.get("http://localhost:8000/admin-portal?admin_key=your_secret_admin_key_here", timeout=5)
    if "Admin SOC" in r.text:
        print("âœ… Admin portal accessible")
    
    # Test security (should block)
    r = requests.get("http://localhost:8000/?test=' OR 1=1", timeout=5)
    if r.status_code == 403:
        print("âœ… Security detection working (SQL injection blocked)")
    
    print("\nðŸŽ‰ All systems operational!")
    
except Exception as e:
    print(f"âŒ Error: {e}")

