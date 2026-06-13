import os
import modal
import sys

app = modal.App("test-blender-app")

# Volumes
trellis_outputs_vol = modal.Volume.from_name("trellis-outputs", create_if_missing=True)
test_cache_vol = modal.Volume.from_name("test-blender-cache", create_if_missing=True)
weights_vol = modal.Volume.from_name("triposplat-model-weights", create_if_missing=True)

# Image
test_image = (
    modal.Image.from_registry("nvidia/cuda:12.1.1-devel-ubuntu22.04", add_python="3.11")
    .apt_install(
        "git", "libgl1-mesa-glx", "libglib2.0-0", "build-essential", "ninja-build", 
        "libopengl0", "libegl1", "libxrender1", "libxxf86vm1", "libxfixes3", "libxi6", 
        "libxkbcommon0", "libsm6", "wget", "tar", "xz-utils"
    )
    .run_commands(
        "mkdir -p /opt/blender",
        "wget -q https://download.blender.org/release/Blender4.2/blender-4.2.0-linux-x64.tar.xz -O /tmp/blender.tar.xz",
        "tar -xf /tmp/blender.tar.xz -C /opt/blender",
        "rm /tmp/blender.tar.xz"
    )
    .run_commands("pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121")
    .pip_install(
        "numpy<2", "safetensors", "pillow", "tqdm", "huggingface_hub", "trimesh", "scipy"
    )
    .run_commands(
        "pip install spconv-cu120",
        "pip install torch_scatter torch_cluster -f https://data.pyg.org/whl/torch-$(python3 -c \"import torch; print(torch.__version__.split('+')[0])\")+cu121.html"
    )
    .run_commands(
        "git clone https://github.com/VAST-AI-Research/UniRig.git /root/UniRig && cd /root/UniRig && sed -i '/flash_attn/d' requirements.txt && pip install -r requirements.txt"
    )
)

@app.function(
    image=test_image,
    gpu="A10G",
    volumes={
        "/trellis_outputs": trellis_outputs_vol,
        "/test_cache": test_cache_vol,
        "/weights": weights_vol
    },
    timeout=600
)
def run_conversion() -> tuple[str, bytes, str, bytes]:
    import os
    import subprocess
    import tempfile
    from huggingface_hub import snapshot_download
    
    # Reload input volumes
    trellis_outputs_vol.reload()
    weights_vol.reload()
    
    # Ensure UniRig weights exist in the volume
    unirig_weights_dir = "/weights/unirig_weights"
    if not os.path.exists(unirig_weights_dir) or not os.listdir(unirig_weights_dir):
        print("UniRig weights not found in /weights volume. Downloading them now...")
        snapshot_download(
            repo_id="VAST-AI/UniRig",
            repo_type="model",
            local_dir=unirig_weights_dir
        )
        print("Weights downloaded successfully!")
        weights_vol.commit()
    else:
        print("Found existing UniRig weights in weights volume.")
    
    # Find the first GLB file
    glb_files = [f for f in os.listdir("/trellis_outputs") if f.endswith(".glb")]
    if not glb_files:
        raise ValueError("No .glb files found in trellis-outputs volume!")
        
    src_glb = glb_files[0]
    src_glb_path = os.path.join("/trellis_outputs", src_glb)
    
    dst_fbx = src_glb.replace(".glb", ".fbx")
    dst_fbx_path = os.path.join("/test_cache", dst_fbx)
    
    print(f"Found source GLB: {src_glb_path}")
    print(f"Destination FBX path: {dst_fbx_path}")
    
    model_id = src_glb.replace(".glb", "")
    blender_script = """import bpy
import sys
import os

print("BLENDER PYTHON PATHS:", sys.path)
print("BLENDER PYTHON EXECUTABLE:", sys.executable)

import addon_utils

try:
    input_file = sys.argv[-3]
    output_file = sys.argv[-2]
    model_id = sys.argv[-1]
    
    # Enable glTF and FBX addons explicitly
    addon_utils.enable("io_scene_gltf2", default_set=True)
    addon_utils.enable("io_scene_fbx", default_set=True)
    
    # Clear default scene
    bpy.ops.wm.read_factory_settings(use_empty=True)
    
    # Import GLB
    bpy.ops.import_scene.gltf(filepath=input_file)
    
    # Rename and save texture images
    output_dir = os.path.dirname(output_file)
    for image in bpy.data.images:
        if image.name in ['Render Result', 'Viewer Node']:
            continue
        
        # Rename the image so it matches our file naming convention
        image.name = f"{model_id}_texture"
        
        # Save the image as PNG
        image.file_format = 'PNG'
        texture_name = f"{model_id}_texture.png"
        texture_path = os.path.join(output_dir, texture_name)
        image.filepath_raw = texture_path
        image.save()
        print(f"Extracted and saved texture to: {texture_path}")
        
    # Export FBX with referenced textures (not embedded)
    bpy.ops.export_scene.fbx(filepath=output_file, check_existing=False, path_mode='AUTO', embed_textures=False)
    print("Blender conversion completed successfully!")
except Exception as e:
    print("Blender script error:", e)
    sys.exit(1)
"""
    
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as script_file:
        script_file.write(blender_script)
        script_path = script_file.name
        
    try:
        print("Running Blender headless conversion...")
        cmd = [
            "/opt/blender/blender-4.2.0-linux-x64/blender",
            "--background",
            "--python", script_path,
            "--",
            src_glb_path,
            dst_fbx_path,
            model_id
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        print("Blender Output:")
        print(result.stdout)
        
        if result.returncode != 0:
            raise RuntimeError(f"Blender conversion failed with exit code {result.returncode}")
            
        if not os.path.exists(dst_fbx_path):
            raise RuntimeError("FBX file was not generated by Blender")
            
        print("Unrigged FBX generated successfully.")
        
    finally:
        if os.path.exists(script_path):
            os.remove(script_path)
            
    # Apply skeletal rigging using UniRig
    
    # 1. Patch UniRig's unirig_skin.py to use a custom native PyTorch MHA implementation to bypass flash_attn and load checkpoints successfully
    skin_py_path = "/root/UniRig/src/model/unirig_skin.py"
    if os.path.exists(skin_py_path):
        print("Patching unirig_skin.py to insert custom native MHA class...")
        with open(skin_py_path, "r") as f:
            code = f.read()
        
        # Define the custom MHA class in Python
        custom_mha_code = """
# Custom native PyTorch MHA class to bypass flash_attn and support checkpoint state_dict mapping
class MHA(nn.Module):
    def __init__(self, embed_dim, num_heads, cross_attn=True, **kwargs):
        super().__init__()
        self.embed_dim = embed_dim
        self.num_heads = num_heads
        self.cross_attn = cross_attn
        self.head_dim = embed_dim // num_heads
        
        self.Wq = nn.Linear(embed_dim, embed_dim)
        if cross_attn:
            self.Wkv = nn.Linear(embed_dim, embed_dim * 2)
        else:
            self.Wkv = nn.Linear(embed_dim, embed_dim * 2)
            
        self.out_proj = nn.Linear(embed_dim, embed_dim)
        
    def forward(self, q, x_kv=None):
        B, N, C = q.shape
        H = self.num_heads
        d = self.head_dim
        
        q_proj = self.Wq(q)
        q_proj = q_proj.view(B, N, H, d).transpose(1, 2)
        
        kv_input = x_kv if x_kv is not None else q
        kv_proj = self.Wkv(kv_input)
        S = kv_input.shape[1]
        
        k_proj, v_proj = torch.split(kv_proj, C, dim=-1)
        k_proj = k_proj.view(B, S, H, d).transpose(1, 2)
        v_proj = v_proj.view(B, S, H, d).transpose(1, 2)
        
        attn = torch.matmul(q_proj, k_proj.transpose(-2, -1)) / math.sqrt(d)
        attn = torch.softmax(attn, dim=-1)
        
        out = torch.matmul(attn, v_proj)
        out = out.transpose(1, 2).contiguous().view(B, N, C)
        
        return self.out_proj(out)
"""
        code = code.replace("from flash_attn.modules.mha import MHA", custom_mha_code)
        with open(skin_py_path, "w") as f:
            f.write(code)
        print("Patched unirig_skin.py successfully.")
    else:
        print("Warning: unirig_skin.py not found for patching!")
        
    # 2. Patch UniRig's merge.py to export referencing FBX, pack glTF images, rename images, and bypass open3d to avoid segmentation faults
    merge_py_path = "/root/UniRig/src/inference/merge.py"
    if os.path.exists(merge_py_path):
        print("Patching merge.py...")
        with open(merge_py_path, "r") as f:
            code = f.read()
        # Rename images to match model_id and export referencing FBX
        code = code.replace("bpy.ops.export_scene.fbx(filepath=output_path, add_leaf_bones=True)",
                            "model_id = os.path.basename(output_path).replace('_rigged.fbx', '').replace('.fbx', '').replace('.FBX', '')\n            for img in bpy.data.images:\n                if img.name not in ['Render Result', 'Viewer Node']:\n                    img.name = f'{model_id}_texture'\n            bpy.ops.export_scene.fbx(filepath=output_path, add_leaf_bones=True, path_mode='AUTO', embed_textures=False)")
        # Pack glTF images on import
        code = code.replace("import_pack_images=False", "import_pack_images=True")
        # Remove unused open3d import which causes segmentation faults on exit
        code = code.replace("import open3d as o3d", "# import open3d as o3d")
        with open(merge_py_path, "w") as f:
            f.write(code)
        print("Patched merge.py successfully.")
    else:
        print("Warning: merge.py not found for patching!")
    # 2.2. Patch UniRig's exporter.py to disable open3d to avoid segmentation faults on exit
    exporter_py_path = "/root/UniRig/src/data/exporter.py"
    if os.path.exists(exporter_py_path):
        print("Patching exporter.py to bypass open3d...")
        with open(exporter_py_path, "r") as f:
            code = f.read()
        code = code.replace("import open3d as o3d", "# import open3d as o3d")
        with open(exporter_py_path, "w") as f:
            f.write(code)
        print("Patched exporter.py successfully.")
    else:
        print("Warning: exporter.py not found for patching!")
        
    # 2.5. Patch UniRig's model config to use native attention (sdpa) instead of flash_attn
    model_yaml_path = "/root/UniRig/configs/model/unirig_ar_350m_1024_81920_float32.yaml"
    if os.path.exists(model_yaml_path):
        print("Patching model config to use eager/sdpa attention...")
        with open(model_yaml_path, "r") as f:
            code = f.read()
        code = code.replace("_attn_implementation: flash_attention_2", "_attn_implementation: sdpa")
        with open(model_yaml_path, "w") as f:
            f.write(code)
        print("Patched model config successfully.")
    # 2.7. Patch UniRig's skin model config to disable flash attention in PointTransformerV3
    skin_yaml_path = "/root/UniRig/configs/model/unirig_skin.yaml"
    if os.path.exists(skin_yaml_path):
        print("Patching skin model config to disable flash attention...")
        with open(skin_yaml_path, "r") as f:
            code = f.read()
        code = code.replace("  res_linear: True", "  res_linear: True\n  enable_flash: False")
        with open(skin_yaml_path, "w") as f:
            f.write(code)
        print("Patched skin model config successfully.")
    else:
        print("Warning: skin model config YAML not found for patching!")
        
    # 3. Define paths for intermediate products and output
    skeleton_fbx = src_glb.replace(".glb", "_skeleton.fbx")
    skeleton_fbx_path = os.path.join("/test_cache", skeleton_fbx)
    
    skinned_fbx = src_glb.replace(".glb", "_skinned.fbx")
    skinned_fbx_path = os.path.join("/test_cache", skinned_fbx)
    
    rigged_fbx = src_glb.replace(".glb", "_rigged.fbx")
    rigged_fbx_path = os.path.join("/test_cache", rigged_fbx)
    
    env = os.environ.copy()
    env["HF_HOME"] = "/weights"
    
    # Prepend Blender 4.2 path so UniRig's subprocess calls the WebP-compatible Blender 4.2
    blender_dir = "/opt/blender/blender-4.2.0-linux-x64"
    env["PATH"] = f"{blender_dir}:{env.get('PATH', '')}"
    
    # Run Skeleton Prediction
    print(f"Running UniRig skeleton prediction on: {dst_fbx_path}...")
    cmd_skeleton = [
        "bash", "launch/inference/generate_skeleton.sh",
        "--input", dst_fbx_path,
        "--output", skeleton_fbx_path
    ]
    result_skeleton = subprocess.run(
        cmd_skeleton, 
        cwd="/root/UniRig", 
        env=env, 
        capture_output=True, 
        text=True
    )
    print("--- Skeleton prediction STDOUT ---")
    print(result_skeleton.stdout)
    print("--- Skeleton prediction STDERR ---")
    print(result_skeleton.stderr)
    
    if result_skeleton.returncode != 0 or not os.path.exists(skeleton_fbx_path):
        raise RuntimeError(f"Skeleton prediction failed with exit code {result_skeleton.returncode}")
        
    # Run Skin Prediction
    print(f"Running UniRig skin prediction on: {skeleton_fbx_path}...")
    cmd_skin = [
        "bash", "launch/inference/generate_skin.sh",
        "--input", skeleton_fbx_path,
        "--output", skinned_fbx_path
    ]
    result_skin = subprocess.run(
        cmd_skin, 
        cwd="/root/UniRig", 
        env=env, 
        capture_output=True, 
        text=True
    )
    print("--- Skin prediction STDOUT ---")
    print(result_skin.stdout)
    print("--- Skin prediction STDERR ---")
    print(result_skin.stderr)
    
    if result_skin.returncode != 0 or not os.path.exists(skinned_fbx_path):
        raise RuntimeError(f"Skin prediction failed with exit code {result_skin.returncode}")
        
    # Run Merge Step
    print(f"Running UniRig merge on source: {skinned_fbx_path} and target: {src_glb_path}...")
    cmd_merge = [
        "bash", "launch/inference/merge.sh",
        "--source", skinned_fbx_path,
        "--target", src_glb_path,
        "--output", rigged_fbx_path
    ]
    result_merge = subprocess.run(
        cmd_merge, 
        cwd="/root/UniRig", 
        env=env, 
        capture_output=True, 
        text=True
    )
    print("--- Merge STDOUT ---")
    print(result_merge.stdout)
    print("--- Merge STDERR ---")
    print(result_merge.stderr)
    
    if result_merge.returncode != 0 or not os.path.exists(rigged_fbx_path):
        raise RuntimeError(f"Merge failed with exit code {result_merge.returncode}")
        
    print(f"Rigging complete! Rigged FBX saved to {rigged_fbx_path}")
    
    print("Committing volumes...")
    weights_vol.commit()
    test_cache_vol.commit()
    
    # Read files to return
    with open(dst_fbx_path, "rb") as f:
        unrigged_bytes = f.read()
    with open(rigged_fbx_path, "rb") as f:
        rigged_bytes = f.read()
        
    texture_name = f"{model_id}_texture.png"
    texture_path = os.path.join("/test_cache", texture_name)
    with open(texture_path, "rb") as f:
        texture_bytes = f.read()
        
    return dst_fbx, unrigged_bytes, rigged_fbx, rigged_bytes, texture_name, texture_bytes

@app.local_entrypoint()
def main():
    print("Starting Blender GLB to FBX + UniRig rigging test on Modal...")
    try:
        unrigged_name, unrigged_bytes, rigged_name, rigged_bytes, texture_name, texture_bytes = run_conversion.remote()
        
        # Save to Downloads folder on Mac
        downloads_dir = os.path.expanduser("~/Downloads")
        
        # Save texture first
        texture_path = os.path.join(downloads_dir, texture_name)
        with open(texture_path, "wb") as f:
            f.write(texture_bytes)
        print(f"[+] Success! Texture downloaded to: {texture_path} ({len(texture_bytes)} bytes)")
        
        # Save unrigged FBX
        unrigged_path = os.path.join(downloads_dir, unrigged_name)
        with open(unrigged_path, "wb") as f:
            f.write(unrigged_bytes)
        print(f"[+] Success! Unrigged FBX downloaded to: {unrigged_path} ({len(unrigged_bytes)} bytes)")
        
        # Save rigged FBX
        rigged_path = os.path.join(downloads_dir, rigged_name)
        with open(rigged_path, "wb") as f:
            f.write(rigged_bytes)
        print(f"[+] Success! Rigged FBX downloaded to: {rigged_path} ({len(rigged_bytes)} bytes)")
        
    except Exception as e:
        print(f"\n[-] Rigging pipeline failed: {e}")
