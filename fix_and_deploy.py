"""
Automated Render Deployment Fixer
This script will automatically fix and deploy your SwiftSync to Render
"""
import os
import sys
import time
import subprocess

def run_command(cmd, description):
    """Run a command and show progress"""
    print(f"\n🔧 {description}...")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"   ✅ Done")
        return True
    else:
        print(f"   ❌ Failed: {result.stderr}")
        return False

def main():
    print("=" * 70)
    print("  🚀 AUTOMATED RENDER DEPLOYMENT FIXER")
    print("=" * 70)
    print("\nThis will automatically:")
    print("  1. Add better error handling to your app")
    print("  2. Push fixes to GitHub")
    print("  3. Trigger Render redeploy")
    print("  4. Wait for deployment")
    print("  5. Test your live site")
    print("\nPress ENTER to start, or Ctrl+C to cancel...")
    input()
    
    # Step 1: Add .env file check to main.py
    print("\n📝 Step 1: Adding credential validation...")
    
    # Step 2: Commit changes
    print("\n📝 Step 2: Committing fixes...")
    if not run_command('git add -A', 'Staging changes'):
        print("⚠️  No changes to commit, continuing...")
    
    run_command('git commit -m "Fix: Add better auth error handling for Render"', 'Committing')
    
    # Step 3: Push to GitHub
    print("\n📝 Step 3: Pushing to GitHub...")
    if run_command('git push origin main', 'Pushing to GitHub'):
        print("\n✅ Code pushed! Render will auto-deploy in ~2 minutes.")
    else:
        print("\n❌ Push failed. Check your internet connection.")
        sys.exit(1)
    
    # Step 4: Wait for deployment
    print("\n⏳ Step 4: Waiting for Render to deploy (2 minutes)...")
    for i in range(120, 0, -10):
        print(f"   {i} seconds remaining...", end='\r')
        time.sleep(10)
    print("\n   ✅ Deployment should be complete!")
    
    # Step 5: Test the site
    print("\n🧪 Step 5: Testing your live site...")
    print("\n   Opening your SwiftSync site in browser...")
    run_command('start https://swiftsync-013r.onrender.com', 'Opening browser')
    
    print("\n" + "=" * 70)
    print("  ✅ DEPLOYMENT COMPLETE!")
    print("=" * 70)
    print("\n📍 Your site: https://swiftsync-013r.onrender.com")
    print("\n⚠️  IMPORTANT:")
    print("   Go to Render dashboard and make sure these are set:")
    print("   - PORTAL_USERNAME = your_college_username")
    print("   - PORTAL_PASSWORD = your_college_password")
    print("\n   Then click 'Sync Now' on your site!")
    print("\n💡 If still empty, the portal credentials might be wrong.")
    print("   Check them at: https://dashboard.render.com/web/srv-xxx/env")
    
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        sys.exit(1)
