import os
import subprocess
import sys
import re
import threading
import time
import http.server
import socketserver
import urllib.request
import urllib.error
import json
import webbrowser
import functools
import base64
import datetime
from pathlib import Path

# ── Local image-save server (port 8083) ──────────────────────────────────────
# The frontend POSTs JSON here after every 2D generation so we can persist
# the PNG + prompt text to the local images_2D folder.

BASE_DIR = Path(__file__).parent.resolve()
IMAGES_DIR = BASE_DIR / "images_2D"

class ImageSaveHandler(http.server.BaseHTTPRequestHandler):
    """Tiny HTTP handler that saves 2D character images to disk."""

    # ── CORS pre-flight ───────────────────────────────────────────────────────
    def do_OPTIONS(self):
        self._cors(200)

    # ── Save endpoint ─────────────────────────────────────────────────────────
    def do_POST(self):
        if self.path != '/save-image':
            self._cors(404)
            return

        try:
            length = int(self.headers.get('Content-Length', 0))
            body   = json.loads(self.rfile.read(length))

            animal     = body.get('animal', 'creature').strip()
            theme_name = body.get('theme_name', 'unknown').strip()
            prompt     = body.get('prompt', '')
            image_b64  = body.get('image_b64', '')   # pure base64, no data-URI prefix

            # Build a safe filename  e.g.  20260605_215802_Fox_Cyberpunk_Netrunner
            ts   = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            slug = f"{ts}_{animal}_{theme_name}".replace(' ', '_')[:120]

            IMAGES_DIR.mkdir(parents=True, exist_ok=True)

            # Save PNG
            if image_b64:
                if image_b64.startswith('http://') or image_b64.startswith('https://'):
                    print(f"[images_2D] Downloading from URL: {image_b64}", flush=True)
                    req = urllib.request.Request(
                        image_b64,
                        headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
                    )
                    with urllib.request.urlopen(req) as response:
                        img_bytes = response.read()
                else:
                    img_bytes = base64.b64decode(image_b64)
                (IMAGES_DIR / f"{slug}.png").write_bytes(img_bytes)

            # Save prompt as .txt
            if prompt:
                (IMAGES_DIR / f"{slug}.txt").write_text(prompt, encoding='utf-8')

            print(f"[images_2D] Saved {slug}.png + .txt", flush=True)
            resp = json.dumps({'status': 'ok', 'slug': slug}).encode()
            self._cors(200, resp)

        except Exception as exc:
            print(f"[images_2D] Save error: {exc}", flush=True)
            self._cors(500, json.dumps({'error': str(exc)}).encode())

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _cors(self, code, body=b''):
        self.send_response(code)
        self.send_header('Access-Control-Allow-Origin',  '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, *_):  # suppress noisy access logs
        pass


class NoCacheFrontendHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()


def start_save_server(port=8083):
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(('', port), ImageSaveHandler) as httpd:
        print(f'[+] Image-save server running at http://localhost:{port}', flush=True)
        httpd.serve_forever()


def start_frontend_server(port=8082):
    socketserver.TCPServer.allow_reuse_address = True
    # Use functools.partial to configure the directory with our no-cache handler
    Handler = functools.partial(NoCacheFrontendHandler, directory=str(BASE_DIR / "frontend"))
    with socketserver.TCPServer(("", port), Handler) as httpd:
        print(f"\n[+] Frontend running at http://localhost:{port}", flush=True)
        httpd.serve_forever()

def warmup_backend(api_url):
    print("\n========================================", flush=True)
    print("   Warming Up GPU Backend & Models      ", flush=True)
    print("========================================", flush=True)
    print("Waking up GPU container on Modal (preloading models into memory)...", flush=True)
    
    warmup_url = f"{api_url}/warmup"
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(warmup_url, data=b"{}", headers=headers, method="POST")
    
    start_time = time.time()
    
    while True:
        elapsed = time.time() - start_time
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                if response.status == 200:
                    resp_data = json.loads(response.read().decode())
                    if resp_data.get("status") in ["ready", "warmed_up"]:
                        print(f"\n[+] GPU Backend is fully warm and model loaded! (Took {elapsed:.1f}s)", flush=True)
                        return True
        except Exception:
            pass
            
        print(f"\r⌛ Waiting for GPU container to initialize... ({elapsed:.1f}s elapsed)", end="", flush=True)
        time.sleep(2)
        
        if elapsed > 180:
            print("\n[-] Warmup took too long. Proceeding, but backend might still be loading.", flush=True)
            return False

def check_credentials_flow():
    new_setup = not os.path.exists("credentials.txt")
    if new_setup:
        print("\n[!] credentials.txt not found. Initializing authentication flow...", flush=True)
        
        # Modal Authentication
        print("\n--- Modal Authentication ---", flush=True)
        print("Running Modal setup SDK... Please authenticate in the browser if prompted.", flush=True)
        try:
            subprocess.run([sys.executable, "-m", "modal", "setup"], check=True)
            print("[+] Modal SDK setup completed successfully.", flush=True)
        except subprocess.CalledProcessError as e:
            print(f"[-] Modal authentication failed: {e}", flush=True)
            return False
            
        # Hugging Face Authentication
        print("\n--- Hugging Face Authentication ---", flush=True)
        hf_token_path = os.path.expanduser("~/.cache/huggingface/token")
        
        token_input = ""
        if not os.path.exists(hf_token_path):
            print("TRELLIS.2 requires a Hugging Face token to download the model weights.", flush=True)
            print("You can create one at: https://huggingface.co/settings/tokens", flush=True)
            token_input = input("Please paste your Hugging Face Token (starts with hf_): ").strip()
            
            if token_input:
                os.makedirs(os.path.dirname(hf_token_path), exist_ok=True)
                with open(hf_token_path, "w") as f:
                    f.write(token_input)
                print("[+] Hugging Face token saved to cache.", flush=True)
            else:
                print("[-] Warning: Proceeding without Hugging Face token.", flush=True)
        else:
            print("[+] Found existing Hugging Face token in cache.", flush=True)
            with open(hf_token_path, "r") as f:
                token_input = f.read().strip()
            
        # Extract and save to credentials.txt
        print("\n[+] Saving credentials to credentials.txt...", flush=True)
        with open("credentials.txt", "w") as f:
            modal_toml = os.path.expanduser("~/.modal.toml")
            if not os.path.exists(modal_toml):
                modal_toml = os.path.expanduser("~/.config/modal.toml")
                
            if os.path.exists(modal_toml):
                with open(modal_toml, "r") as m:
                    for line in m:
                        if "token_id" in line:
                            val = line.split('=')[1].strip().strip('"').strip("'")
                            f.write(f"MODAL_TOKEN_ID={val}\n")
                        elif "token_secret" in line:
                            val = line.split('=')[1].strip().strip('"').strip("'")
                            f.write(f"MODAL_TOKEN_SECRET={val}\n")
                            
            if token_input:
                f.write(f"HF_TOKEN={token_input}\n")
            
        print("[+] Credentials successfully saved to credentials.txt!", flush=True)
    else:
        print("[+] Found existing credentials.txt.", flush=True)
    return True

def check_volumes_weights():
    print("\n========================================", flush=True)
    print("   Verifying Modal Storage Volumes      ", flush=True)
    print("========================================", flush=True)
    
    scripts = {"TRELLIS": "deploy_trellis.py", "SkinTokens": "deploy_skintokens.py"}
    
    for name, script in scripts.items():
        print(f"[+] Verifying model weights for {name} ({script}::download_weights)...", flush=True)
        try:
            subprocess.run([sys.executable, "-m", "modal", "run", f"{script}::download_weights"], check=True)
            print(f"[+] {name} storage volume weight verification complete!", flush=True)
        except subprocess.CalledProcessError as e:
            print(f"[-] Warning: Volume weight pre-caching failed for {name}: {e}", flush=True)
            print("    The app will attempt to download them dynamically at runtime.", flush=True)

def deploy_backends_to_modal():
    print("\n========================================", flush=True)
    print("   Deploying Backend APIs to Modal      ", flush=True)
    print("========================================", flush=True)
    print("[+] Ensuring local dependencies are installed (FastAPI, Modal)...", flush=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "fastapi", "python-multipart", "modal", "--quiet"], check=False)
    
    scripts = {"TRELLIS": "deploy_trellis.py", "SkinTokens": "deploy_skintokens.py"}
    api_urls = {}
    
    for name, script in scripts.items():
        print(f"\n[+] Deploying {name} backend ({script}) to Modal...", flush=True)
        
        process = subprocess.Popen(
            [sys.executable, "-m", "modal", "deploy", script], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        url = None
        for line in process.stdout:
            print(line, end="", flush=True)
            match = re.search(r'(https://[a-zA-Z0-9-]+\.modal\.run)', line)
            if match:
                url = match.group(1)
                
        process.wait()
        
        if process.returncode != 0:
            print(f"\n[-] Deployment of {name} failed.", flush=True)
            choice = input("Would you like to fallback to the existing configuration? (y/n): ").strip().lower()
            if choice == 'y':
                config_path = Path("frontend/config.js")
                if config_path.exists():
                    content = config_path.read_text()
                    m_api = re.search(r"const API_URL = '(.*?)';", content)
                    m_rig = re.search(r"const RIG_API_URL = '(.*?)';", content)
                    if m_api and m_rig:
                        api_urls["TRELLIS"] = m_api.group(1)
                        api_urls["SkinTokens"] = m_rig.group(1)
                        print(f"[+] Using cached URLs:\n    TRELLIS: {api_urls['TRELLIS']}\n    SkinTokens: {api_urls['SkinTokens']}", flush=True)
                        break
            return None
            
        if not url:
            print(f"\n[-] Could not find the deployed API endpoint URL for {name}.", flush=True)
            return None
            
        print(f"\n[+] {name} Deployment successful! Backend API: {url}", flush=True)
        api_urls[name] = url
        
    return api_urls

def launch_local_servers(api_url, rig_api_url):
    print("\n========================================", flush=True)
    print("   Launching Local Servers...           ", flush=True)
    print("========================================", flush=True)
    
    # Read OpenAI API Key for frontend injection
    api_key_path = Path("../TripoSplat_Project/poster generator/api_key.txt")
    openai_key = ""
    if api_key_path.exists():
        with open(api_key_path, "r") as f:
            content = f.read().strip()
            if content and content != "YOUR_OPENAI_API_KEY_HERE":
                openai_key = content

    # Write the API URLs and keys to the frontend config
    config_path = Path("frontend/config.js")
    with open(config_path, "w") as f:
        f.write(f"const API_URL = '{api_url}';\n")
        f.write(f"const RIG_API_URL = '{rig_api_url}';\n")
        f.write(f"const OPENAI_API_KEY = '{openai_key}';\n")
        f.write(f"const LOCAL_SAVE_URL = 'http://localhost:8083';\n")
        
    print("[+] Wrote configuration to frontend/config.js", flush=True)
    
    # Start the image-save server in a background thread
    save_thread = threading.Thread(target=start_save_server, daemon=True)
    save_thread.start()

    # Start the frontend server in a background thread
    print("[+] Launching frontend web server...", flush=True)
    server_thread = threading.Thread(target=start_frontend_server, daemon=True)
    server_thread.start()
    
    # Short sleep to allow local servers to bind
    time.sleep(1)
    
    print("\n========================================", flush=True)
    print("   Ready! Opening http://localhost:8082 ", flush=True)
    print("   Press Ctrl+C to quit.                ", flush=True)
    print("========================================", flush=True)
    
    try:
        webbrowser.open("http://localhost:8082")
    except Exception:
        pass
        
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[+] Shutting down launcher...", flush=True)
        sys.exit(0)

def main():
    # Force working directory to the script's directory so all relative paths resolve correctly
    os.chdir(BASE_DIR)
    
    print("========================================", flush=True)
    print("   Tripo 3D Studio - Launcher           ", flush=True)
    print("========================================", flush=True)
    
    # Check flags first for automation compatibility
    frontend_only = "--frontend-only" in sys.argv or "-f" in sys.argv
    skip_deploy = "--skip-deploy" in sys.argv or "-s" in sys.argv
    
    if frontend_only:
        print("\n[+] Running in Frontend-Only mode (No backend deployment).", flush=True)
        config_path = Path("frontend/config.js")
        api_url = ""
        rig_url = ""
        if config_path.exists():
            content = config_path.read_text()
            m_api = re.search(r"const API_URL = '(.*?)';", content)
            m_rig = re.search(r"const RIG_API_URL = '(.*?)';", content)
            if m_api: api_url = m_api.group(1)
            if m_rig: rig_url = m_rig.group(1)
        launch_local_servers(api_url, rig_url)
        return
        
    if skip_deploy:
        print("\n[+] Skipping backend deployment, launching using cached config.", flush=True)
        config_path = Path("frontend/config.js")
        api_url = ""
        rig_url = ""
        if config_path.exists():
            content = config_path.read_text()
            m_api = re.search(r"const API_URL = '(.*?)';", content)
            m_rig = re.search(r"const RIG_API_URL = '(.*?)';", content)
            if m_api: api_url = m_api.group(1)
            if m_rig: rig_url = m_rig.group(1)
        if not api_url or not rig_url:
            print("[-] Error: Could not find existing URLs in config.js.", flush=True)
            return
        warmup_backend(api_url)
        launch_local_servers(api_url, rig_url)
        return

    # Interactive Phase Selection Menu
    print("\nPlease select an execution phase to run:")
    print("  [1] Full Flow (Credentials -> Verify Volumes -> Deploy Backend -> Warmup -> Run Frontend)")
    print("  [2] Phase 1: Modal Setup & Hugging Face authentication")
    print("  [3] Phase 2: Pre-cache Model Weights on Modal Volumes")
    print("  [4] Phase 3: Deploy Backend APIs to Modal")
    print("  [5] Phase 4: Warmup Backend GPU container")
    print("  [6] Phase 5: Launch Local Servers & Web Interface (from cached config)")
    print("  [7] Exit")
    
    try:
        choice = input("\nEnter choice [1-7] (Default: 1): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nExiting...")
        return
        
    if not choice:
        choice = "1"
        
    if choice == "7":
        print("Exiting...")
        return
        
    if choice == "2":
        check_credentials_flow()
        print("\n[+] Credentials setup finished.", flush=True)
        return
        
    if choice == "3":
        check_credentials_flow()
        check_volumes_weights()
        print("\n[+] Volumes weights caching finished.", flush=True)
        return
        
    if choice == "4":
        check_credentials_flow()
        api_urls = deploy_backends_to_modal()
        if api_urls:
            # Write to config
            config_path = Path("frontend/config.js")
            openai_key = ""
            api_key_path = Path("../TripoSplat_Project/poster generator/api_key.txt")
            if api_key_path.exists():
                with open(api_key_path, "r") as f:
                    content = f.read().strip()
                    if content and content != "YOUR_OPENAI_API_KEY_HERE":
                        openai_key = content
            with open(config_path, "w") as f:
                f.write(f"const API_URL = '{api_urls['TRELLIS']}';\n")
                f.write(f"const RIG_API_URL = '{api_urls['SkinTokens']}';\n")
                f.write(f"const OPENAI_API_KEY = '{openai_key}';\n")
                f.write(f"const LOCAL_SAVE_URL = 'http://localhost:8083';\n")
            print("[+] Deployed and saved configuration to config.js.", flush=True)
        return
        
    if choice == "5":
        config_path = Path("frontend/config.js")
        api_url = ""
        if config_path.exists():
            content = config_path.read_text()
            m_api = re.search(r"const API_URL = '(.*?)';", content)
            if m_api: api_url = m_api.group(1)
        if not api_url:
            print("[-] Error: No API URL found in config.js. Deploy first.", flush=True)
            return
        warmup_backend(api_url)
        return
        
    if choice == "6":
        config_path = Path("frontend/config.js")
        api_url = ""
        rig_url = ""
        if config_path.exists():
            content = config_path.read_text()
            m_api = re.search(r"const API_URL = '(.*?)';", content)
            m_rig = re.search(r"const RIG_API_URL = '(.*?)';", content)
            if m_api: api_url = m_api.group(1)
            if m_rig: rig_url = m_rig.group(1)
        launch_local_servers(api_url, rig_url)
        return
        
    if choice == "1":
        # Full Sequence
        if not check_credentials_flow():
            return
        check_volumes_weights()
        
        # Wait 5 seconds
        print("\n========================================", flush=True)
        print("   Waiting 5 seconds for Volume sync... ", flush=True)
        print("========================================", flush=True)
        for i in range(5, 0, -1):
            print(f"\r⌛ Continuing in {i} seconds...", end="", flush=True)
            time.sleep(1)
        print("\r[+] Proceeding to backend start.       \n", flush=True)
        
        api_urls = deploy_backends_to_modal()
        if not api_urls:
            return
            
        warmup_backend(api_urls["TRELLIS"])
        launch_local_servers(api_urls["TRELLIS"], api_urls["SkinTokens"])

if __name__ == "__main__":
    main()
