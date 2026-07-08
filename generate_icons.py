from PIL import Image, ImageDraw
import os
import sys

def resize_icon(source_path, target_res_dir):
    sizes = {
        'mdpi': 48,
        'hdpi': 72,
        'xhdpi': 96,
        'xxhdpi': 144,
        'xxxhdpi': 192
    }
    
    # Load source image
    try:
        img = Image.open(source_path).convert("RGBA")
    except Exception as e:
        print(f"Error opening image: {e}")
        return

    # Create a mask for perfect circle (for round icon) just in case
    # Actually, the user asked for "rounded squircle", and the generated image is already a squircle on a background.
    # So we'll just resize it directly for both ic_launcher and ic_launcher_round.
    
    for density, size in sizes.items():
        resized = img.resize((size, size), Image.Resampling.LANCZOS)
        
        dir_path = os.path.join(target_res_dir, f'mipmap-{density}')
        os.makedirs(dir_path, exist_ok=True)
        
        # Save as both ic_launcher and ic_launcher_round
        resized.save(os.path.join(dir_path, 'ic_launcher.png'), 'PNG')
        resized.save(os.path.join(dir_path, 'ic_launcher_round.png'), 'PNG')
        print(f"Generated {density} ({size}x{size})")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python generate_icons.py <source_image> <res_dir>")
        sys.exit(1)
    
    source = sys.argv[1]
    res_dir = sys.argv[2]
    resize_icon(source, res_dir)
