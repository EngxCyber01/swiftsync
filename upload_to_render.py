"""
Upload local database to Render deployment via API endpoint
"""
import os
import sys
import zipfile
from pathlib import Path
import requests
from tqdm import tqdm

# Configuration
RENDER_URL = "https://swiftsync-013r.onrender.com"
LOCAL_DB = Path("data/lecture_sync.db")
LOCAL_FILES = Path("lectures_storage")

def create_data_package():
    """Package database and files into a zip"""
    print("📦 Creating data package...")
    
    if not LOCAL_DB.exists():
        print("❌ Database not found! Run local sync first.")
        sys.exit(1)
    
    if not LOCAL_FILES.exists() or not list(LOCAL_FILES.glob("*")):
        print("❌ No lecture files found! Run local sync first.")
        sys.exit(1)
    
    zip_path = Path("data_package.zip")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add database
        print(f"  Adding database: {LOCAL_DB}")
        zipf.write(LOCAL_DB, "lecture_sync.db")
        
        # Add all files
        files = list(LOCAL_FILES.glob("*"))
        print(f"  Adding {len(files)} lecture files...")
        for file in tqdm(files, desc="  Packaging"):
            zipf.write(file, f"lectures/{file.name}")
    
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"✅ Package created: {zip_path} ({size_mb:.2f} MB)")
    return zip_path

def upload_to_render(zip_path):
    """Upload package to Render via admin endpoint"""
    print(f"\n🚀 Uploading to {RENDER_URL}...")
    
    upload_url = f"{RENDER_URL}/api/admin/upload-data"
    
    try:
        with open(zip_path, 'rb') as f:
            files = {'package': ('data_package.zip', f, 'application/zip')}
            
            print("  Uploading... (this may take a minute)")
            response = requests.post(
                upload_url,
                files=files,
                timeout=300,  # 5 minutes
                headers={'X-Admin-Key': os.getenv('ADMIN_KEY', 'swiftsync-admin-2026')}
            )
        
        if response.status_code == 200:
            print("✅ Upload successful!")
            data = response.json()
            print(f"  📊 {data.get('files_count', 0)} files uploaded")
            print(f"  📚 {data.get('db_records', 0)} database records")
            print(f"\n🎉 Your site is now live with all lectures!")
            print(f"   Visit: {RENDER_URL}")
            return True
        else:
            print(f"❌ Upload failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error: {e}")
        return False

def main():
    print("=" * 60)
    print("  SwiftSync - Upload Local Data to Render")
    print("=" * 60)
    print()
    
    # Create package
    zip_path = create_data_package()
    
    # Upload
    success = upload_to_render(zip_path)
    
    # Cleanup
    if zip_path.exists():
        zip_path.unlink()
        print(f"\n🧹 Cleaned up temporary file")
    
    if success:
        print("\n" + "=" * 60)
        print("  ✅ DEPLOYMENT COMPLETE!")
        print("=" * 60)
        sys.exit(0)
    else:
        print("\n⚠️  Upload failed. See error above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
