"""
Script to update admin dashboard colors to professional design
"""
import re

# Read the main.py file
with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Color mappings: Old colorful -> New professional
color_replacements = [
    # Background gradients
    ('#0a0e27', '#1a1a1a'),
    ('#1a1f3a', '#2d2d2d'),
    ('#0d1b2a', '#1a1a1a'),
    
    # Radial gradients (Kurdish colors -> grayscale)
    ('rgba(220, 20, 60, 0.1)', 'rgba(100, 100, 100, 0.05)'),  # Red
    ('rgba(34, 139, 34, 0.1)', 'rgba(80, 80, 80, 0.05)'),     # Green
    ('rgba(255, 215, 0, 0.1)', 'rgba(120, 120, 120, 0.05)'),  # Yellow
    
    # Header and cards
    ('rgba(220, 20, 60, 0.15)', 'rgba(30, 41, 59, 0.95)'),
    ('rgba(34, 139, 34, 0.15)', 'rgba(51, 65, 85, 0.95)'),
    ('rgba(255, 215, 0, 0.3)', 'rgba(148, 163, 184, 0.2)'),
    ('rgba(255, 215, 0, 0.2)', 'rgba(148, 163, 184, 0.2)'),
    ('rgba(255, 215, 0, 0.5)', 'rgba(6, 182, 212, 0.5)'),
    
    # Stat cards
    ('rgba(22, 33, 62, 0.9)', 'rgba(30, 41, 59, 0.9)'),
    ('rgba(26, 31, 58, 0.9)', 'rgba(51, 65, 85, 0.9)'),
    ('rgba(220, 20, 60, 0.05)', 'rgba(100, 116, 139, 0.1)'),
    ('rgba(34, 139, 34, 0.05)', 'rgba(71, 85, 105, 0.1)'),
    
    # Sections
    ('rgba(22, 33, 62, 0.95)', 'rgba(30, 41, 59, 0.95)'),
    ('rgba(26, 31, 58, 0.95)', 'rgba(51, 65, 85, 0.95)'),
    
    # Text colors
    ('#FFD700', '#06b6d4'),  # Gold -> Cyan
    
    # Gradients with Kurdish flag colors
    ('#DC143C 0%, #FFD700 50%, #228B22 100%', '#06b6d4 0%, #3b82f6 100%'),
    
    # Button gradients
    ('#FFD700 0%, #FFA500 100%', '#06b6d4 0%, #3b82f6 100%'),
    ('#FFED4E 0%, #FFD700 100%', '#0891b2 0%, #2563eb 100%'),
    
    # Table rows hover
    ('rgba(220, 20, 60, 0.1) 0%, rgba(255, 215, 0, 0.1) 50%, rgba(34, 139, 34, 0.1) 100%', 
     'rgba(100, 116, 139, 0.2) 0%, rgba(71, 85, 105, 0.2) 100%'),
    
    # Stat card value gradient
    ('#DC143C 0%, #FFD700 50%, #228B22 100%', '#f59e0b 0%, #ef4444 100%'),
    
    # IP address background
    ('rgba(220, 20, 60, 0.2) 0%, rgba(34, 139, 34, 0.2) 100%', 'rgba(30, 41, 59, 0.8) 0%, rgba(51, 65, 85, 0.8) 100%'),
    
    # Section after overlay
    ('rgba(255, 215, 0, 0.1)', 'rgba(148, 163, 184, 0.1)'),
    
    # Header shimmer
    ('rgba(255, 215, 0, 0.05)', 'rgba(148, 163, 184, 0.1)'),
    
    # Borders
    ('rgba(255, 215, 0, 0.3)', 'rgba(6, 182, 212, 0.3)'),
    
    # Shadows
    ('rgba(255, 215, 0, 0.2)', 'rgba(6, 182, 212, 0.2)'),
    ('rgba(255, 215, 0, 0.6)', 'rgba(6, 182, 212, 0.4)'),
    ('rgba(255, 215, 0, 0.5)', 'rgba(6, 182, 212, 0.3)'),
    
    # Table header gradient
    ('rgba(220, 20, 60, 0.2) 0%, rgba(34, 139, 34, 0.2) 100%', 'rgba(30, 41, 59, 0.95) 0%, rgba(51, 65, 85, 0.95) 100%'),
]

# Apply replacements
for old_color, new_color in color_replacements:
    content = content.replace(old_color, new_color)

# Remove text-shadow from certain elements
content = re.sub(r'text-shadow: 0 0 \d+px rgba\(255, 215, 0, [\d.]+\);', '', content)
content = re.sub(r'text-shadow: 0 0 \d+px rgba\(255, 215, 0, [\d.]+\);', '', content)

# Write back
with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Admin dashboard colors updated successfully!")
print("   - Changed from colorful Kurdish flag theme to professional grayscale/cyan")
print("   - Background: Dark gray gradients")
print("   - Accents: Cyan/blue (#06b6d4)")
print("   - Values: Orange/red gradient (#f59e0b)")
