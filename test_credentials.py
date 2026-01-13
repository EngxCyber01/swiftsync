"""Test what credentials are actually loaded"""
from dotenv import load_dotenv
import os

load_dotenv()

username = os.getenv('PORTAL_USERNAME', 'NOT_FOUND')
password = os.getenv('PORTAL_PASSWORD', 'NOT_FOUND')

print(f"Username loaded: '{username}'")
print(f"Password loaded: '{password}'")
print(f"Password length: {len(password)}")
print(f"Password ends with $: {password.endswith('$')}")
