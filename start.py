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

<<<<<<< Updated upstream
=======
GLOBAL_API_URL = ""
GLOBAL_RIG_URL = ""
GENERATION_STATUS = {}

def build_multipart_payload(image_bytes, remove_bg, animal, theme):
    import uuid
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    parts = []
    
    parts.append(f"--{boundary}".encode('utf-8'))
    parts.append(f'Content-Disposition: form-data; name="image"; filename="image.png"'.encode('utf-8'))
    parts.append(b'Content-Type: image/png')
    parts.append(b'')
    parts.append(image_bytes)
    
    parts.append(f"--{boundary}".encode('utf-8'))
    parts.append(f'Content-Disposition: form-data; name="remove_bg"'.encode('utf-8'))
    parts.append(b'')
    parts.append(str(remove_bg).lower().encode('utf-8'))
    
    if animal:
        parts.append(f"--{boundary}".encode('utf-8'))
        parts.append(f'Content-Disposition: form-data; name="animal"'.encode('utf-8'))
        parts.append(b'')
        parts.append(animal.encode('utf-8'))
        
    if theme:
        parts.append(f"--{boundary}".encode('utf-8'))
        parts.append(f'Content-Disposition: form-data; name="theme"'.encode('utf-8'))
        parts.append(b'')
        parts.append(theme.encode('utf-8'))
        
    parts.append(f"--{boundary}--".encode('utf-8'))
    body = b'\r\n'.join(parts)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type

def run_animation_pipeline_background(api_url, call_id, folder_path, animal_clean, theme_clean, folder_number):
    rel_folder = f"outputs/{animal_clean}_{theme_clean}_{folder_number}"
    GENERATION_STATUS[call_id] = {
        "status": "processing",
        "message": "3D model is in progress..."
    }
    time.sleep(2)
    print(f"[pipeline] Background worker started for call {call_id}...", flush=True)
    
    # 1. Poll for status until success
    asset_url = None
    fbx_url = None
    texture_url = None
    while True:
        try:
            req = urllib.request.Request(f"{api_url}/status/{call_id}")
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get('status') == 'success':
                    asset_url = data.get('asset_url')
                    fbx_url = data.get('fbx_url')
                    texture_url = data.get('texture_url')
                    print(f"[pipeline] Generation success for call {call_id}!", flush=True)
                    break
                elif data.get('status') == 'error':
                    print(f"[pipeline] Error returned from Modal: {data.get('message')}", flush=True)
                    GENERATION_STATUS[call_id] = {
                        "status": "error",
                        "message": data.get('message', 'Generation failed')
                    }
                    return
                elif data.get('status') == 'processing':
                    msg = data.get('message', '3D model is in progress...')
                    GENERATION_STATUS[call_id]["message"] = msg
                    print(f"[pipeline] Polling: {msg}", flush=True)
        except Exception as e:
            print(f"[pipeline] Polling warning: {e}", flush=True)
        time.sleep(5)
        
    # 2. Download rigged GLB, rigged FBX, and texture to folder
    try:
        glb_filename = asset_url.split('/')[-1]
        fbx_filename = fbx_url.split('/')[-1]
        
        # Extract the 5-digit random number from glb_filename
        match = re.search(r'_(\d{5})\.glb$', glb_filename)
        if match:
            rand_num = match.group(1)
        else:
            rand_num = str(folder_number)
            
        local_glb_name = f"{animal_clean}_{theme_clean}_{rand_num}.glb"
        local_fbx_name = f"{animal_clean}_{theme_clean}_{rand_num}.fbx"
        local_tex_name = f"{animal_clean}_{theme_clean}_{rand_num}_texture.png" if texture_url else None
        
        print(f"[pipeline] Downloading rigged GLB...", flush=True)
        urllib.request.urlretrieve(f"{api_url}{asset_url}", str(folder_path / local_glb_name))
        
        print(f"[pipeline] Downloading rigged FBX...", flush=True)
        urllib.request.urlretrieve(f"{api_url}{fbx_url}", str(folder_path / local_fbx_name))
        
        if texture_url:
            print(f"[pipeline] Downloading texture...", flush=True)
            urllib.request.urlretrieve(f"{api_url}{texture_url}", str(folder_path / local_tex_name))
            
        print(f"[pipeline] All base model assets downloaded to {folder_path}", flush=True)
    except Exception as e:
        print(f"[pipeline] Download error: {e}", flush=True)
        GENERATION_STATUS[call_id] = {
            "status": "error",
            "message": f"Download failed: {e}"
        }
        return
        
    # 3. Clean outputs volume except templates and our newly generated FBX file
    try:
        print(f"[pipeline] Invoking clean_volume on Modal...", flush=True)
        subprocess.run([
            sys.executable, "-m", "modal", "run",
            "tests/successful/merge_animations.py",
            "--keep-fbx", fbx_filename
        ], check=True)
    except Exception as e:
        print(f"[pipeline] Volume cleaning failed: {e}", flush=True)
        
    # 4. Run retargeting animations in parallel in cloud on Modal
    GENERATION_STATUS[call_id]["message"] = "creating and applying animations..."
    try:
        print(f"[pipeline] Running retargeting animations in parallel in cloud...", flush=True)
        p1 = subprocess.Popen([
            sys.executable, "-m", "modal", "run",
            "tests/successful/run_universal_chibi_walk.py",
            "--choice", "0",
            "--no-download"
        ])
        p2 = subprocess.Popen([
            sys.executable, "-m", "modal", "run",
            "tests/successful/run_universal_chibi_idle.py",
            "--choice", "0",
            "--no-download"
        ])
        p3 = subprocess.Popen([
            sys.executable, "-m", "modal", "run",
            "tests/successful/run_universal_chibi_thinking.py",
            "--choice", "0",
            "--no-download"
        ])
        
        ret1 = p1.wait()
        ret2 = p2.wait()
        ret3 = p3.wait()
        
        if ret1 != 0 or ret2 != 0 or ret3 != 0:
            raise RuntimeError(f"Parallel retargeting failed: walk={ret1}, idle={ret2}, thinking={ret3}")
    except Exception as e:
        print(f"[pipeline] Animation retargeting execution failed: {e}", flush=True)
        GENERATION_STATUS[call_id] = {
            "status": "error",
            "message": f"Retargeting failed: {e}"
        }
        return

    # 5. Invoke merge_animations on Modal!
    GENERATION_STATUS[call_id]["message"] = "will be finishing up soon..."
    model_id = os.path.splitext(fbx_filename)[0]
    walk_cache_fbx = f"walk_retargeted_{fbx_filename}"
    idle_outputs_fbx = f"{model_id}_idle.fbx"
    thinking_outputs_fbx = f"{model_id}_thinking.fbx"
    merged_outputs_fbx = f"{model_id}_animated.fbx"
    
    try:
        print(f"[pipeline] Invoking Blender merge_anims on Modal...", flush=True)
        subprocess.run([
            sys.executable, "-m", "modal", "run",
            "tests/successful/merge_animations.py",
            "--merge",
            "--walk-fbx", walk_cache_fbx,
            "--idle-fbx", idle_outputs_fbx,
            "--thinking-fbx", thinking_outputs_fbx,
            "--output-fbx", merged_outputs_fbx
        ], check=True)
        
        # 6. Download the final merged FBX and GLB files
        local_merged_name = f"{animal_clean}_{theme_clean}_{rand_num}_animated.fbx"
        local_merged_glb_name = f"{animal_clean}_{theme_clean}_{rand_num}_animated.glb"
        merged_outputs_glb = os.path.splitext(merged_outputs_fbx)[0] + ".glb"
        
        print(f"[pipeline] Downloading merged FBX file...", flush=True)
        urllib.request.urlretrieve(f"{api_url}/download/{merged_outputs_fbx}", str(folder_path / local_merged_name))
        print(f"[pipeline] SUCCESS! Merged animation FBX saved: {folder_path / local_merged_name}", flush=True)
        
        print(f"[pipeline] Downloading merged GLB file...", flush=True)
        try:
            urllib.request.urlretrieve(f"{api_url}/download/{merged_outputs_glb}", str(folder_path / local_merged_glb_name))
            print(f"[pipeline] SUCCESS! Merged animation GLB saved: {folder_path / local_merged_glb_name}", flush=True)
        except Exception as glb_dl_err:
            print(f"[pipeline] Warning: Failed to download merged GLB file: {glb_dl_err}", flush=True)
            local_merged_glb_name = None
        
        GENERATION_STATUS[call_id] = {
            "status": "success",
            "asset_url": f"{rel_folder}/{local_glb_name}",
            "animated_glb_url": f"{rel_folder}/{local_merged_glb_name}" if local_merged_glb_name else None,
            "fbx_url": f"{rel_folder}/{local_merged_name}",
            "texture_url": f"{rel_folder}/{local_tex_name}" if local_tex_name else None
        }
        
        # 7. Wait 5 seconds, then perform cleanup of intermediate animation files on Modal
        print(f"[pipeline] Waiting 5 seconds before cleanup...", flush=True)
        time.sleep(5)
        print(f"[pipeline] Performing cleanup of intermediate animation files on Modal...", flush=True)
        try:
            subprocess.run([
                sys.executable, "-m", "modal", "run",
                "tests/successful/merge_animations.py",
                "--cleanup",
                "--walk-fbx", walk_cache_fbx,
                "--idle-fbx", idle_outputs_fbx,
                "--thinking-fbx", thinking_outputs_fbx
            ], check=True)
            print(f"[pipeline] Intermediate animation files cleaned up successfully on Modal.", flush=True)
        except Exception as cleanup_err:
            print(f"[pipeline] Warning: Cleanup of intermediate animation files failed: {cleanup_err}", flush=True)
            
    except Exception as e:
        print(f"[pipeline] Blending/Merging failed: {e}", flush=True)
        GENERATION_STATUS[call_id] = {
            "status": "error",
            "message": f"Merging failed: {e}"
        }

>>>>>>> Stashed changes
class ImageSaveHandler(http.server.BaseHTTPRequestHandler):
    """Tiny HTTP handler that saves 2D character images to disk."""

    # ── CORS pre-flight ───────────────────────────────────────────────────────
    def do_OPTIONS(self):
        self._cors(200)

<<<<<<< Updated upstream
    # ── Save endpoint ─────────────────────────────────────────────────────────
=======
    def do_GET(self):
        if self.path.startswith('/status-3d/'):
            call_id = self.path.split('/')[-1]
            status = GENERATION_STATUS.get(call_id, {
                "status": "processing",
                "message": "3D model is in progress..."
            })
            self._cors(200, json.dumps(status).encode())
        elif self.path == '/list-generations':
            try:
                outputs_dir = BASE_DIR / "frontend" / "outputs"
                generations = []
                if outputs_dir.exists():
                    for entry in os.listdir(outputs_dir):
                        entry_path = outputs_dir / entry
                        if os.path.isdir(entry_path):
                            gen_data = {
                                "folder": entry,
                                "glb": None,
                                "animated_glb": None,
                                "fbx": None,
                                "texture": None,
                                "image": None
                            }
                            # Look for files
                            for f in os.listdir(entry_path):
                                if f == "input.png":
                                    gen_data["image"] = f"outputs/{entry}/{f}"
                                elif f.endswith("_animated.glb"):
                                    gen_data["animated_glb"] = f"outputs/{entry}/{f}"
                                elif f.endswith(".glb"):
                                    gen_data["glb"] = f"outputs/{entry}/{f}"
                                elif f.endswith("_animated.fbx"):
                                    gen_data["fbx"] = f"outputs/{entry}/{f}"
                                elif f.endswith("_texture.png"):
                                    gen_data["texture"] = f"outputs/{entry}/{f}"
                            if gen_data["glb"] or gen_data["animated_glb"] or gen_data["fbx"] or gen_data["image"]:
                                generations.append(gen_data)
                
                # Sort generations (newest folder number first or alphabetically)
                generations.sort(key=lambda g: g["folder"], reverse=True)
                
                self._cors(200, json.dumps(generations).encode('utf-8'))
            except Exception as exc:
                print(f"[list-generations] Error: {exc}", flush=True)
                self._cors(500, json.dumps({'error': str(exc)}).encode('utf-8'))
        else:
            self._cors(404)

>>>>>>> Stashed changes
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
