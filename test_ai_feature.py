"""
Quick test script to verify the AI Summarization feature implementation
"""
import sys
from pathlib import Path

print("=" * 60)
print("SwiftSync AI Summarization - Implementation Test")
print("=" * 60)

# Test 1: Check dependencies
print("\n1. Checking dependencies...")
try:
    import PyPDF2
    print("   ✓ PyPDF2 installed")
except ImportError:
    print("   ✗ PyPDF2 not installed")
    sys.exit(1)

try:
    import openai
    print("   ✓ openai installed")
except ImportError:
    print("   ✗ openai not installed")
    sys.exit(1)

try:
    import aiofiles
    print("   ✓ aiofiles installed")
except ImportError:
    print("   ✗ aiofiles not installed")
    sys.exit(1)

# Test 2: Check module imports
print("\n2. Checking module imports...")
try:
    from summarizer import (
        extract_text_from_pdf,
        summarize_single_lecture,
        summarize_all_lectures,
        SummarizationError
    )
    print("   ✓ summarizer module imports successfully")
except ImportError as e:
    print(f"   ✗ Error importing summarizer: {e}")
    sys.exit(1)

# Test 3: Check main.py imports
print("\n3. Checking main.py imports...")
try:
    # We can't fully import main.py as it starts the server
    # But we can check if it would import without errors
    import ast
    with open("main.py", "r", encoding="utf-8") as f:
        code = f.read()
        ast.parse(code)
    print("   ✓ main.py syntax is valid")
except Exception as e:
    print(f"   ✗ Error in main.py: {e}")
    sys.exit(1)

# Test 4: Check cache directory
print("\n4. Checking cache directory...")
cache_dir = Path("data/summary_cache")
if cache_dir.exists():
    print(f"   ✓ Cache directory exists: {cache_dir}")
else:
    print(f"   ✓ Cache directory will be created on first use: {cache_dir}")

# Test 5: Check API endpoint definitions in main.py
print("\n5. Checking API endpoints...")
with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()
    if '/api/summarize"' in content:
        print("   ✓ /api/summarize endpoint defined")
    else:
        print("   ✗ /api/summarize endpoint not found")
    
    if '/api/summarize-all"' in content:
        print("   ✓ /api/summarize-all endpoint defined")
    else:
        print("   ✗ /api/summarize-all endpoint not found")

# Test 6: Check UI elements
print("\n6. Checking UI elements...")
ui_checks = {
    "summary-btn": "Get Summary button",
    "summarize-all-btn": "Summarize All button",
    "summaryModal": "Summary modal",
    "summarizeLecture": "Single lecture function",
    "summarizeAllLectures": "All lectures function"
}

for check_str, description in ui_checks.items():
    if check_str in content:
        print(f"   ✓ {description} implemented")
    else:
        print(f"   ✗ {description} not found")

# Test 7: Environment variable check
print("\n7. Checking environment configuration...")
try:
    from dotenv import load_dotenv
    import os
    load_dotenv()
    
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key and api_key != "your_openai_api_key_here":
        print("   ✓ OPENAI_API_KEY is configured")
    else:
        print("   ⚠ OPENAI_API_KEY not configured (required for AI features)")
        print("     Add OPENAI_API_KEY to your .env file")
except Exception as e:
    print(f"   ⚠ Could not check environment: {e}")

print("\n" + "=" * 60)
print("Implementation Test Complete!")
print("=" * 60)
print("\nNext steps:")
print("1. Add OPENAI_API_KEY to your .env file")
print("2. Start the server: python main.py")
print("3. Navigate to http://localhost:8000")
print("4. Test the 'Get Summary' and 'Summarize All' buttons")
print("\nFor detailed documentation, see: AI_SUMMARIZATION.md")
print("=" * 60)
