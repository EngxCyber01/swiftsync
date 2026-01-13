from dotenv import load_dotenv
import os

load_dotenv()

print(f"Username: {os.getenv('PORTAL_USERNAME', 'NOT_FOUND')}")
print(f"Password: {os.getenv('PORTAL_PASSWORD', 'NOT_FOUND')[:5]}...")
