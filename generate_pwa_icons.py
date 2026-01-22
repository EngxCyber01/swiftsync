"""
PWA Icon Generator for SwiftSync
Generates all required PWA icon sizes from KurdishFlag.jpg
"""
from PIL import Image
from pathlib import Path

# Icon sizes required for PWA
ICON_SIZES = [72, 96, 128, 144, 152, 192, 384, 512]

def generate_icons():
    """Generate all PWA icons from KurdishFlag.jpg"""
    
    # Check if source image exists
    source_image = Path("KurdishFlag.jpg")
    if not source_image.exists():
        print("❌ KurdishFlag.jpg not found!")
        print("📥 Please place KurdishFlag.jpg in the project root directory")
        return False
    
    # Create output directory
    output_dir = Path("static/icons")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("🎨 Generating PWA icons from KurdishFlag.jpg...")
    
    try:
        # Open source image
        img = Image.open(source_image)
        
        # Convert to RGB if necessary (remove alpha channel)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        
        # Generate each icon size
        for size in ICON_SIZES:
            # Resize maintaining aspect ratio and center crop to square
            img_copy = img.copy()
            
            # Make square by center cropping
            width, height = img_copy.size
            if width != height:
                min_dim = min(width, height)
                left = (width - min_dim) // 2
                top = (height - min_dim) // 2
                right = left + min_dim
                bottom = top + min_dim
                img_copy = img_copy.crop((left, top, right, bottom))
            
            # Resize to target size with high quality
            img_resized = img_copy.resize((size, size), Image.Resampling.LANCZOS)
            
            # Save icon
            output_path = output_dir / f"icon-{size}x{size}.png"
            img_resized.save(output_path, 'PNG', optimize=True)
            print(f"✅ Generated: {output_path}")
        
        print(f"\n🎉 Successfully generated {len(ICON_SIZES)} PWA icons!")
        print(f"📁 Icons saved to: {output_dir.absolute()}")
        return True
        
    except Exception as e:
        print(f"❌ Error generating icons: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("  SwiftSync PWA Icon Generator")
    print("=" * 60)
    
    success = generate_icons()
    
    if success:
        print("\n✨ Next steps:")
        print("1. Your icons are ready in static/icons/")
        print("2. Restart your server: python main.py")
        print("3. Open http://localhost:8000")
        print("4. Check Chrome DevTools > Application > Manifest")
        print("5. Look for 'Install' button in browser address bar")
    else:
        print("\n⚠️  Manual alternative:")
        print("1. Visit https://www.pwabuilder.com/imageGenerator")
        print("2. Upload your image (512x512 or larger recommended)")
        print("3. Download generated icons")
        print("4. Place them in static/icons/ folder")
