import asyncio
import aiohttp
import os
import json
import base64

API_KEY_PATH = "/Users/mac/Documents/Models Generator/TripoSplat_Project/poster generator/api_key.txt"

def get_api_key():
    try:
        with open(API_KEY_PATH, "r") as f:
            return f.read().strip()
    except Exception as e:
        print(f"Error reading API key: {e}")
        return ""

async def generate_character_image(animal, theme_name, theme_palette, theme_accessory, output_path):
    api_key = get_api_key()
    if not api_key:
        print("API Key not found.")
        return False

    prompt = (
        f"An adorable, ultra-cute 3D humanoid cartoon {animal} character, standing upright on two legs, "
        f"designed in a distinct hyper-chibi anime aesthetic. Extreme proportional emphasis on an oversized, "
        f"giant round head with large expressive eyes, paired with a tiny, small, stylized body. The character "
        f"is completely empty-handed with open palms, absolutely not holding anything in its hands, keeping both "
        f"hands completely free and visible. The character is themed as a {theme_name}, dressed in a "
        f"stylized outfit using a curated {theme_palette} color scheme, wearing a prominent "
        f"{theme_accessory}. Beautiful smooth surfaces, clean outer outlines, vibrant high-contrast "
        f"professional color combinations. Perfect symmetrical game-ready 3D character asset, relaxed standard "
        f"A-pose, set against a solid pure black background, isolated professional studio lighting, high-quality "
        f"detailed 3D rendering, incredibly cute, charming, and cool vinyl toy aesthetic."
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-image-2",
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024"
    }

    print(f"Sending async request to OpenAI for {animal} ({theme_name})...")
    
    # We wait (no timeout) as requested
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post("https://api.openai.com/v1/images/generations", headers=headers, json=payload, timeout=None) as response:
                response_data = await response.json()
                
                if response.status == 200:
                    image_data = response_data['data'][0]
                    
                    if 'b64_json' in image_data:
                        print("Image returned as base64 (b64_json). Decoding...")
                        img_bytes = base64.b64decode(image_data['b64_json'])
                        with open(output_path, 'wb') as f:
                            f.write(img_bytes)
                        print(f"Successfully saved image to {output_path}")
                        return True
                    
                    image_url = image_data.get('url')
                    if not image_url:
                        print("No image URL or b64_json returned.")
                        return False
                        
                    print(f"Image generated! Downloading from {image_url}...")
                    
                    # Download the image
                    async with session.get(image_url, timeout=None) as img_resp:
                        if img_resp.status == 200:
                            img_bytes = await img_resp.read()
                            with open(output_path, 'wb') as f:
                                f.write(img_bytes)
                            print(f"Successfully saved image to {output_path}")
                            return True
                        else:
                            print(f"Failed to download image. Status: {img_resp.status}")
                            return False
                else:
                    print(f"OpenAI API Error ({response.status}): {response_data}")
                    return False
        except Exception as e:
            print(f"Request failed: {e}")
            return False

async def main():
    downloads_dir = os.path.expanduser("~/Downloads")
    output_path = os.path.join(downloads_dir, "generated_character.png")
    
    animal = "Red Panda"
    theme_name = "Cyberpunk Netrunner"
    theme_palette = "matte black, electric cyan, and hot magenta"
    theme_accessory = "glowing neon futuristic visor and a high-collar techwear jacket"
    
    await generate_character_image(animal, theme_name, theme_palette, theme_accessory, output_path)

if __name__ == "__main__":
    asyncio.run(main())
