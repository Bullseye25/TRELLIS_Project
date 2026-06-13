import os
import subprocess

def main():
    print("========================================")
    print("   Modal Volume GLB Downloader          ")
    print("========================================")
    filename = input("Please enter the GLB filename (e.g. model.glb): ").strip()
    
    if not filename:
        print("Error: Filename cannot be empty.")
        return
        
    if not filename.endswith(".glb"):
        filename += ".glb"
        
    download_dir = os.path.expanduser("~/Downloads")
    os.makedirs(download_dir, exist_ok=True)
    output_path = os.path.join(download_dir, filename)
    
    print(f"\nDownloading '{filename}' from Modal to: {output_path}...")
    try:
        # Using the modal CLI via python to download from the trellis-outputs volume
        subprocess.run([
            "python3", "-m", "modal", "volume", "get", "trellis-outputs", filename, output_path
        ], check=True)
        print(f"\n[+] Success! Your 3D model is ready at: {output_path}")
    except subprocess.CalledProcessError as e:
        print(f"\n[-] Failed to download the file. Error: {e}")

if __name__ == "__main__":
    main()
