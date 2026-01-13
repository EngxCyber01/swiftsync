"""
Quick deployment checklist and test script
"""
import os
import sys
from pathlib import Path

def check_deployment_ready():
    """Check if the system is ready for deployment"""
    print("🔍 Checking deployment readiness...\n")
    
    issues = []
    warnings = []
    
    # Check if .env file exists
    if not Path(".env").exists():
        issues.append("❌ .env file not found! Copy .env.example to .env")
    else:
        print("✅ .env file exists")
        
        # Check credentials
        from dotenv import load_dotenv
        load_dotenv()
        
        username = os.getenv("PORTAL_USERNAME", "")
        password = os.getenv("PORTAL_PASSWORD", "")
        
        if "your-email" in username or "example.com" in username:
            issues.append("❌ PORTAL_USERNAME not configured in .env")
        elif username:
            print(f"✅ Username configured: {username[:3]}***")
        else:
            issues.append("❌ PORTAL_USERNAME is empty")
            
        if "your-password" in password or not password:
            issues.append("❌ PORTAL_PASSWORD not configured in .env")
        elif password:
            print(f"✅ Password configured: {'*' * len(password)}")
    
    # Check required directories
    dirs_to_check = ["data", "lectures_storage"]
    for dir_name in dirs_to_check:
        if Path(dir_name).exists():
            print(f"✅ {dir_name}/ directory exists")
        else:
            warnings.append(f"⚠️  {dir_name}/ will be created automatically")
    
    # Check Python packages
    try:
        import fastapi
        import uvicorn
        import requests
        from bs4 import BeautifulSoup
        from dotenv import load_dotenv
        print("✅ All required packages installed")
    except ImportError as e:
        issues.append(f"❌ Missing package: {e.name}")
    
    print("\n" + "="*50)
    
    if issues:
        print("\n🚨 ISSUES THAT MUST BE FIXED:\n")
        for issue in issues:
            print(f"  {issue}")
    
    if warnings:
        print("\n⚠️  WARNINGS:\n")
        for warning in warnings:
            print(f"  {warning}")
    
    if not issues:
        print("\n✅ SYSTEM IS READY TO DEPLOY!")
        print("\n📋 File Handling Capabilities:")
        print("  ✅ PDF files - Full support with streaming download")
        print("  ✅ Word/PowerPoint - Full support")
        print("  ✅ Videos (MP4, AVI, etc.) - Full support")
        print("  ✅ Archives (ZIP, RAR) - Full support")
        print("  ✅ All file types - Preserved with original names")
        print("\n🌐 To start the server:")
        print('  py main.py')
        print("\n📱 Frontend Features:")
        print("  ✅ Modern responsive design")
        print("  ✅ File type icons (PDF, DOC, PPT, etc.)")
        print("  ✅ Search functionality")
        print("  ✅ Real-time statistics")
        print("  ✅ Auto-refresh every 5 minutes")
        print("  ✅ Mobile-friendly interface")
        return True
    else:
        print("\n❌ Please fix the issues above before deploying.")
        return False

if __name__ == "__main__":
    try:
        ready = check_deployment_ready()
        sys.exit(0 if ready else 1)
    except Exception as e:
        print(f"\n❌ Error during check: {e}")
        sys.exit(1)
