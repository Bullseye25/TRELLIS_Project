import os
import modal
import subprocess
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = modal.App("skintokens-deployment")

skintokens_image = (
    modal.Image.from_registry("nvidia/cuda:12.1.1-devel-ubuntu22.04", add_python="3.11")
    .apt_install("git", "build-essential", "ninja-build", "libxrender1", "libxxf86vm1", "libxfixes3", "libxi6", "libxkbcommon0", "libsm6", "libgl1-mesa-glx", "libglib2.0-0", "libgomp1", "libegl1", "libopengl0")
    .pip_install("uv")
    .run_commands("uv pip install --system torch==2.7.0 torchvision==0.22.0 torchaudio==2.7.0 --index-url https://download.pytorch.org/whl/cu128")
    .run_commands("uv pip install --system packaging ninja wheel")
    .run_commands("uv pip install --system flash-attn --no-build-isolation")
    .run_commands("git clone https://github.com/VAST-AI-Research/SkinTokens.git /root/SkinTokens")
    .run_commands("cd /root/SkinTokens && uv pip install --system -r requirements.txt")
)

skintokens_weights_vol = modal.Volume.from_name("skintokens-weights", create_if_missing=True)
skintokens_outputs_vol = modal.Volume.from_name("trellis-outputs", create_if_missing=True)

def get_credentials():
    creds = {"HF_TOKEN": os.environ.get("HF_TOKEN")}
    try:
        with open("credentials.txt", "r") as f:
            for line in f:
                if line.startswith("HF_TOKEN="):
                    creds["HF_TOKEN"] = line.strip().split("=", 1)[1]
    except Exception:
        pass
    return creds

secrets_dict = get_credentials()
secrets = []
if secrets_dict.get("HF_TOKEN"):
    secrets.append(modal.Secret.from_dict({"HF_TOKEN": secrets_dict["HF_TOKEN"]}))

@app.function(image=skintokens_image, volumes={"/weights": skintokens_weights_vol}, secrets=secrets, timeout=3600)
def download_weights():
    print("Downloading SkinTokens weights...")
    os.makedirs("/weights/experiments", exist_ok=True)
    os.makedirs("/weights/models", exist_ok=True)
    
    # Symlink the model directories to the persistent volume
    if not os.path.exists("/root/SkinTokens/experiments"):
        os.symlink("/weights/experiments", "/root/SkinTokens/experiments")
    if not os.path.exists("/root/SkinTokens/models"):
        os.symlink("/weights/models", "/root/SkinTokens/models")
        
    subprocess.run(["python", "download.py", "--model"], cwd="/root/SkinTokens", check=True)
    skintokens_weights_vol.commit()
    print("SkinTokens weights downloaded and committed.")

@app.function(
    image=skintokens_image,
    volumes={"/weights": skintokens_weights_vol, "/outputs": skintokens_outputs_vol},
    secrets=secrets,
    timeout=600,
    gpu="L4"
)
def rig_glb(input_filename: str, output_filename: str):
    import os
    import subprocess
    
    input_path = f"/outputs/{input_filename}"
    output_path = f"/outputs/{output_filename}"
    
    # Reload outputs volume to sync the newly created GLB file from Trellis
    skintokens_outputs_vol.reload()
    
    if not os.path.exists(input_path):
        raise Exception(f"Input model not found on volume: {input_path}")
        
    print(f"SkinTokens: Rigging {input_path} to {output_path}...", flush=True)
    
    # Set up model symlinks inside the container before running
    if not os.path.exists("/root/SkinTokens/experiments"):
        os.symlink("/weights/experiments", "/root/SkinTokens/experiments")
    if not os.path.exists("/root/SkinTokens/models"):
        os.symlink("/weights/models", "/root/SkinTokens/models")
        
    subprocess.run([
        "python", "demo.py", 
        "--input", input_path, 
        "--output", output_path, 
        "--use_transfer"
    ], cwd="/root/SkinTokens", check=True)
    
    skintokens_outputs_vol.commit()
    print(f"SkinTokens: Rigging completed successfully. Saved to {output_path}", flush=True)
    return output_filename

web_app = FastAPI()

# Enable CORS for local testing
web_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@web_app.post("/rig")
def rig_mesh(file: UploadFile = File(...)):
    import uuid
    import shutil
    
    uid = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1]
    input_path = f"/tmp/{uid}{ext}"
    output_path = f"/outputs/{uid}{ext}"
    
    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
        
    print(f"Rigging {input_path} to {output_path}...")
    
    subprocess.run(["python", "demo.py", "--input", input_path, "--output", output_path, "--use_transfer"], cwd="/root/SkinTokens", check=True)
    
    skintokens_outputs_vol.commit()
    return {"status": "success", "model_url": f"/download/{uid}{ext}"}

@web_app.get("/download/{filename}")
def download_file(filename: str):
    path = f"/outputs/{filename}"
    if os.path.exists(path):
        return FileResponse(path, media_type="application/octet-stream", filename=filename)
    return {"error": "File not found"}

@app.function(image=skintokens_image, volumes={"/weights": skintokens_weights_vol, "/outputs": skintokens_outputs_vol}, secrets=secrets, timeout=600, gpu="L4")
@modal.asgi_app()
def rig_api():
    # Setup symlinks at runtime
    if not os.path.exists("/root/SkinTokens/experiments"):
        os.symlink("/weights/experiments", "/root/SkinTokens/experiments")
    if not os.path.exists("/root/SkinTokens/models"):
        os.symlink("/weights/models", "/root/SkinTokens/models")
    return web_app
