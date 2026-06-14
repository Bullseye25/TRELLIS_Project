import os
import io
import time
import uuid
import requests
import base64
from fastapi import FastAPI, HTTPException, BackgroundTasks, Form, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import modal

# Setup Modal app
app = modal.App("trellis-deployment")

# Define Modal Volume for caching LFS models and saving outputs
weights_vol = modal.Volume.from_name("trellis-model-weights", create_if_missing=True)
outputs_vol = modal.Volume.from_name("trellis-outputs", create_if_missing=True)

# Define Model Architecture
# TRELLIS.2 uses CUDA 12.4 and PyTorch 2.6.0
trellis_image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.10")
    .apt_install("git", "libgl1-mesa-glx", "libglib2.0-0", "build-essential", "ninja-build", "libjpeg-dev",
                 "wget", "tar", "xz-utils", "libxrender1", "libxxf86vm1", "libxfixes3", "libxi6",
                 "libxkbcommon0", "libsm6", "libegl1")
    .pip_install(
        "torch==2.6.0", "torchvision==0.21.0", "torchaudio==2.6.0",
        index_url="https://download.pytorch.org/whl/cu124"
    )
    .env({"TORCH_CUDA_ARCH_LIST": "8.0", "CC": "gcc", "CXX": "g++"})
    .pip_install(
        "imageio", "imageio-ffmpeg", "tqdm", "easydict", "opencv-python-headless", "ninja", 
        "trimesh", "transformers", "gradio==6.0.1", "tensorboard", "pandas", "lpips", "zstandard", 
        "kornia", "timm", "fastapi", "python-multipart", "huggingface_hub", "pillow", "requests", "openai", "rembg", "onnxruntime", "pooch", "pymatting", "scipy", "scikit-image",
        "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8"
    )
    .pip_install("packaging", "ninja", "wheel", "setuptools")
    .run_commands("pip install flash-attn==2.7.3 --no-build-isolation")
    .run_commands(
        "git clone -b v0.4.0 https://github.com/NVlabs/nvdiffrast.git /tmp/nvdiffrast && pip install /tmp/nvdiffrast --no-build-isolation",
        "git clone -b renderutils https://github.com/JeffreyXiang/nvdiffrec.git /tmp/nvdiffrec && pip install /tmp/nvdiffrec --no-build-isolation",
        "git clone https://github.com/JeffreyXiang/CuMesh.git /tmp/CuMesh --recursive && pip install /tmp/CuMesh --no-build-isolation",
        "git clone https://github.com/JeffreyXiang/FlexGEMM.git /tmp/FlexGEMM --recursive && pip install /tmp/FlexGEMM --no-build-isolation"
    )
    .run_commands(
        "git clone --recursive https://github.com/microsoft/TRELLIS.2.git /root/TRELLIS.2",
        "pip install /root/TRELLIS.2/o-voxel --no-build-isolation"
    )
    .run_commands(
        "pip install --upgrade git+https://github.com/huggingface/transformers.git",
        "python -c 'p=\"/root/TRELLIS.2/trellis2/modules/image_feature_extractor.py\"; c=open(p).read().replace(\"self.model.layer\", \"getattr(self.model, \\\"model\\\", getattr(self.model, \\\"encoder\\\", self.model)).layer\"); open(p,\"w\").write(c)'"
    )
    .run_commands(
        "python -c 'import os, urllib.request; os.makedirs(\"/root/.u2net\", exist_ok=True); urllib.request.urlretrieve(\"https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx\", \"/root/.u2net/u2net.onnx\")'"
    )
    .run_commands(
        "mkdir -p /opt/blender",
        "wget -q https://download.blender.org/release/Blender4.2/blender-4.2.0-linux-x64.tar.xz -O /tmp/blender.tar.xz",
        "tar -xf /tmp/blender.tar.xz -C /opt/blender",
        "rm /tmp/blender.tar.xz"
    )
)

# Fetch secrets from environment or file
def get_credentials():
    creds = {"OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"), "HF_TOKEN": os.environ.get("HF_TOKEN")}
    try:
        with open("credentials.txt", "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("OPENAI_API_KEY="):
                    creds["OPENAI_API_KEY"] = line.split("=", 1)[1]
                elif line.startswith("HF_TOKEN="):
                    creds["HF_TOKEN"] = line.split("=", 1)[1]
                elif line.startswith("hf_"):
                    creds["HF_TOKEN"] = line
    except Exception:
        pass
        
    if not creds.get("OPENAI_API_KEY"):
        api_key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "TripoSplat_Project", "poster generator", "api_key.txt")
        if os.path.exists(api_key_path):
            try:
                with open(api_key_path, "r") as f:
                    content = f.read().strip()
                if content and content != "YOUR_OPENAI_API_KEY_HERE":
                    creds["OPENAI_API_KEY"] = content
            except Exception:
                pass

    return creds

secrets_dict = get_credentials()
secrets = []
if secrets_dict.get("OPENAI_API_KEY"):
    secrets.append(modal.Secret.from_dict({"OPENAI_API_KEY": secrets_dict["OPENAI_API_KEY"]}))
if secrets_dict.get("HF_TOKEN"):
    secrets.append(modal.Secret.from_dict({"HF_TOKEN": secrets_dict["HF_TOKEN"]}))

@app.function(image=trellis_image, volumes={"/weights": weights_vol}, secrets=secrets, timeout=3600)
def download_weights():
    import huggingface_hub
    print("Downloading TRELLIS.2 weights to persistent volume `/weights`...")
    huggingface_hub.snapshot_download(
        "microsoft/TRELLIS.2-4B", 
        local_dir="/weights/TRELLIS.2-4B"
    )
    print("Model weights successfully downloaded and committed to volume!")

fastapi_app = FastAPI()

# Enable CORS for local testing
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BLENDER_SCRIPT = """
import bpy, sys, os, addon_utils, mathutils

try:
    input_file  = sys.argv[-2]
    output_file = sys.argv[-1]

    addon_utils.enable("io_scene_gltf2", default_set=True)
    addon_utils.enable("io_scene_fbx",   default_set=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=input_file)

    output_dir = os.path.dirname(output_file)
    model_id   = os.path.splitext(os.path.basename(output_file))[0]

    albedo_image = None

    # Walk every material and look for the Base Color input on a Principled BSDF node
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        for node in mat.node_tree.nodes:
            if node.type != "BSDF_PRINCIPLED":
                continue
            base_color_input = node.inputs.get("Base Color")
            if base_color_input is None:
                continue
            for link in mat.node_tree.links:
                if link.to_node == node and link.to_socket == base_color_input:
                    if link.from_node.type == "TEX_IMAGE" and link.from_node.image:
                        img = link.from_node.image
                        # Ensure this is not a normal map
                        if "normal" not in img.name.lower() and "nor" not in img.name.lower():
                            albedo_image = img
                            print(f"Found Base Color image in node graph: {albedo_image.name}")
                            break
            if albedo_image:
                break
        if albedo_image:
            break

    # Fallback: pick the first available non-utility and non-normal image
    if albedo_image is None:
        SKIP = {"Render Result", "Viewer Node"}
        for img in bpy.data.images:
            if img.name not in SKIP and img.size[0] > 0:
                if "normal" not in img.name.lower() and "nor" not in img.name.lower():
                    albedo_image = img
                    print(f"Fallback: using available image: {img.name}")
                    break

    if albedo_image:
        tex_out = os.path.join(output_dir, f"{model_id}_texture.png")
        
        # Set image filepath inside Blender to point to the saved texture
        albedo_image.filepath = f"{model_id}_texture.png"
        
        scene = bpy.context.scene
        scene.render.image_settings.file_format  = "PNG"
        scene.render.image_settings.color_mode   = "RGBA"
        scene.render.image_settings.color_depth  = "8"
        albedo_image.save_render(filepath=tex_out, scene=scene)
        print(f"Saved Base Color texture: {tex_out}")
    else:
        print("WARNING: No base color texture found.")

    # Identify target armature
    target_armatures = [obj for obj in bpy.data.objects if obj.type == 'ARMATURE']
    if not target_armatures:
        raise RuntimeError("No armature found in target model.")
    target_arm = target_armatures[0]
    target_arm.name = "TargetArmature"

    # Rename bones to corrected Mixamo naming structure if they aren't already renamed
    has_mixamo = any("mixamorig" in b.name.lower() for b in target_arm.data.bones)
    if not has_mixamo:
        print("Bones do not have Mixamo naming. Applying conversion mapping...")
        
        def generate_mixamo_mapping(target_arm):
            bones = target_arm.data.bones
            mapping = {}
            
            center_bones = []
            left_bones = []
            right_bones = []
            
            for b in bones:
                if b.name.endswith("_end") or "_end_" in b.name.lower():
                    continue
                head = b.head_local
                if head.x > 0.005:
                    left_bones.append(b)
                elif head.x < -0.005:
                    right_bones.append(b)
                else:
                    center_bones.append(b)
                    
            center_bones = sorted(center_bones, key=lambda b: b.head_local.z)
            if len(center_bones) > 1:
                first = center_bones[0]
                second = center_bones[1]
                if not first.parent and len(first.children) == 1 and first.children[0] == second:
                    center_bones.pop(0)
                    
            if not center_bones:
                return {}
                
            hips_bone = center_bones[0]
            mapping[hips_bone.name] = "mixamorig:Hips"
            
            # Find Neck and Head, ensuring Head is a child of Neck
            fallback_head = center_bones[-1]
            neck_bone = fallback_head.parent
            if not (neck_bone and neck_bone in center_bones):
                neck_bone = center_bones[-2] if len(center_bones) > 2 else None
                
            if neck_bone:
                mapping[neck_bone.name] = "mixamorig:Neck"
                # Find the child of neck_bone (preferring center bones) to map as Head
                neck_children = [c for c in neck_bone.children if c in center_bones]
                if not neck_children and neck_bone.children:
                    neck_children = list(neck_bone.children)
                if neck_children:
                    head_bone = max(neck_children, key=lambda b: b.head_local.z)
                    mapping[head_bone.name] = "mixamorig:Head"
                else:
                    mapping[fallback_head.name] = "mixamorig:Head"
            else:
                mapping[fallback_head.name] = "mixamorig:Head"
                    
            neck_idx = center_bones.index(neck_bone) if neck_bone in center_bones else len(center_bones) - 1
            spine_bones = center_bones[1:neck_idx]
            
            if len(spine_bones) == 1:
                mapping[spine_bones[0].name] = "mixamorig:Spine"
            elif len(spine_bones) == 2:
                mapping[spine_bones[0].name] = "mixamorig:Spine"
                mapping[spine_bones[1].name] = "mixamorig:Spine2"
            elif len(spine_bones) >= 3:
                mapping[spine_bones[0].name] = "mixamorig:Spine"
                mapping[spine_bones[1].name] = "mixamorig:Spine1"
                mapping[spine_bones[2].name] = "mixamorig:Spine2"
                for extra in spine_bones[3:]:
                    mapping[extra.name] = "mixamorig:Spine2"
                    
            z_hips = hips_bone.head_local.z
            left_leg_bones = [b for b in left_bones if b.head_local.z < z_hips]
            left_leg_bones = sorted(left_leg_bones, key=lambda b: b.head_local.z, reverse=True)
            right_leg_bones = [b for b in right_bones if b.head_local.z < z_hips]
            right_leg_bones = sorted(right_leg_bones, key=lambda b: b.head_local.z, reverse=True)
            
            leg_names = ["mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot", "mixamorig:LeftToeBase"]
            for i, b in enumerate(left_leg_bones[:len(leg_names)]):
                mapping[b.name] = leg_names[i]
                
            r_leg_names = ["mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase"]
            for i, b in enumerate(right_leg_bones[:len(r_leg_names)]):
                mapping[b.name] = r_leg_names[i]
                
            left_upper = [b for b in left_bones if b.head_local.z >= z_hips - 0.1]
            if left_upper:
                left_arm_start = min(left_upper, key=lambda b: b.head_local.x)
                left_arm_chain = [left_arm_start]
                curr = left_arm_start
                while len(left_arm_chain) < 4:
                    children = [c for c in curr.children if c in left_upper]
                    if len(children) >= 1:
                        curr = children[0]
                        left_arm_chain.append(curr)
                    else:
                        break
                if len(left_arm_chain) >= 4:
                    mapping[left_arm_chain[0].name] = "mixamorig:LeftShoulder"
                    mapping[left_arm_chain[1].name] = "mixamorig:LeftArm"
                    mapping[left_arm_chain[2].name] = "mixamorig:LeftForeArm"
                    mapping[left_arm_chain[3].name] = "mixamorig:LeftHand"
                elif len(left_arm_chain) == 3:
                    mapping[left_arm_chain[0].name] = "mixamorig:LeftArm"
                    mapping[left_arm_chain[1].name] = "mixamorig:LeftForeArm"
                    mapping[left_arm_chain[2].name] = "mixamorig:LeftHand"
                left_hand_bone = left_arm_chain[-1]
                
                def map_descendants(bone, prefix):
                    for i, child in enumerate(bone.children):
                        if child.name not in mapping:
                            mapping[child.name] = f"{prefix}Finger_{i}"
                            map_descendants(child, f"{prefix}Finger_{i}")
                map_descendants(left_hand_bone, "mixamorig:Left")
                
            right_upper = [b for b in right_bones if b.head_local.z >= z_hips - 0.1]
            if right_upper:
                right_arm_start = max(right_upper, key=lambda b: b.head_local.x)
                right_arm_chain = [right_arm_start]
                curr = right_arm_start
                while len(right_arm_chain) < 4:
                    children = [c for c in curr.children if c in right_upper]
                    if len(children) >= 1:
                        curr = children[0]
                        right_arm_chain.append(curr)
                    else:
                        break
                if len(right_arm_chain) >= 4:
                    mapping[right_arm_chain[0].name] = "mixamorig:RightShoulder"
                    mapping[right_arm_chain[1].name] = "mixamorig:RightArm"
                    mapping[right_arm_chain[2].name] = "mixamorig:RightForeArm"
                    mapping[right_arm_chain[3].name] = "mixamorig:RightHand"
                elif len(right_arm_chain) == 3:
                    mapping[right_arm_chain[0].name] = "mixamorig:RightArm"
                    mapping[right_arm_chain[1].name] = "mixamorig:RightForeArm"
                    mapping[right_arm_chain[2].name] = "mixamorig:RightHand"
                right_hand_bone = right_arm_chain[-1]
                map_descendants(right_hand_bone, "mixamorig:Right")
                
            return mapping
            
        mapping = generate_mixamo_mapping(target_arm)
        for old_name, new_name in mapping.items():
            if old_name in target_arm.data.bones:
                target_arm.data.bones[old_name].name = new_name

    # Remove Icosphere from the model
    for obj in list(bpy.data.objects):
        if "icosphere" in obj.name.lower():
            bpy.data.objects.remove(obj, do_unlink=True)

    print(f"Exporting final clean base FBX: {output_file}")
    bpy.ops.export_scene.fbx(
        filepath=output_file,
        check_existing=False,
        bake_anim=False,
        path_mode="AUTO",
        embed_textures=False,
    )
    print("Base FBX export complete!")

except Exception as e:
    import traceback
    print(f"ERROR: {e}", file=sys.stderr)
    traceback.print_exc()
    sys.exit(1)
"""

@app.cls(
    image=trellis_image,
    gpu="L4", # L4 provides 24GB VRAM at 72% lower cost than A100
    volumes={"/weights": weights_vol, "/outputs": outputs_vol},
    secrets=secrets,
    timeout=600,
    scaledown_window=60, # Shut down container after 1 minute of inactivity to save idle costs
    max_containers=1 # Limit to exactly 1 active GPU container during development stage
)
class TrellisAPI:
    @modal.enter()
    def setup(self):
        print("Initializing TRELLIS.2 Backend...")
        import sys
        sys.path.append("/root/TRELLIS.2")
        import torch
        if not hasattr(torch, "float8_e8m0fnu"):
            setattr(torch, "float8_e8m0fnu", torch.float32)
            
        import huggingface_hub
        hf_token = os.environ.get("HF_TOKEN")
        if hf_token:
            huggingface_hub.login(token=hf_token)
            
        from trellis2.pipelines import Trellis2ImageTo3DPipeline
        
        # Load the model directly from the weights volume
        self.pipeline = Trellis2ImageTo3DPipeline.from_pretrained("/weights/TRELLIS.2-4B")
        self.pipeline.cuda()
        print("TRELLIS.2 Model Loaded and Ready!")

    @modal.method()
    def warmup(self):
        print("Warmup triggered. Model is loaded and ready in memory.")
        return {"status": "ready"}

    @modal.method()
    def process_image(self, image_data: bytes, output_filename: str, remove_bg: bool = True, animal: str = None, theme: str = None):
        import sys
        import os
        import re
        import random
        import tempfile
        import subprocess
        import time
        import json
        sys.path.append("/root/TRELLIS.2")
        import torch
        if not hasattr(torch, "float8_e8m0fnu"):
            setattr(torch, "float8_e8m0fnu", torch.float32)
            
        import huggingface_hub
        hf_token = os.environ.get("HF_TOKEN")
        if hf_token:
            huggingface_hub.login(token=hf_token)
            
        from PIL import Image
        import io
        import o_voxel
        
        uid = os.path.splitext(output_filename)[0]
        
        def write_status(message: str, status_state: str = "processing"):
            try:
                status_file = f"/outputs/{uid}_status.json"
                with open(status_file, "w") as f:
                    json.dump({"status": status_state, "message": message}, f)
                outputs_vol.commit()
                print(f"[STATUS] {message}", flush=True)
            except Exception as e:
                print(f"Error writing status: {e}", flush=True)

        write_status("3D model is in progress...")

        print("Running TRELLIS.2 pipeline...")
        # Load image
        img = Image.open(io.BytesIO(image_data))
        
        # Remove background if requested
        if remove_bg:
            print("Removing background using rembg...")
            from rembg import remove
            img = remove(img)
        
        # Run inference
        mesh = self.pipeline.run(img)[0]
        
        # Simplify mesh if needed
        mesh.simplify(16777216)
        
        # --- GLB Naming Setup ---
        animal_val = animal if animal else "animal"
        theme_val = theme if theme else "custom"
        animal_clean = re.sub(r'[^a-zA-Z0-9_]', '', animal_val.replace(" ", "_")).lower()
        theme_clean = re.sub(r'[^a-zA-Z0-9_]', '', theme_val.replace(" ", "_")).lower()
        
        rand_num = random.randint(10000, 99999)
        proper_glb_name = f"{animal_clean}_{theme_clean}_{rand_num}.glb"
        proper_glb_path = f"/outputs/{proper_glb_name}"
        
        temp_proper_glb_name = f"temp_{proper_glb_name}"
        temp_proper_glb_path = f"/outputs/{temp_proper_glb_name}"
        
        print(f"Exporting raw GLB to Modal storage: {temp_proper_glb_path}...")
        glb = o_voxel.postprocess.to_glb(
            vertices            =   mesh.vertices,
            faces               =   mesh.faces,
            attr_volume         =   mesh.attrs,
            coords              =   mesh.coords,
            attr_layout         =   mesh.layout,
            voxel_size          =   mesh.voxel_size,
            aabb                =   [[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target   =   1000000,
            texture_size        =   4096,
            remesh              =   True,
            remesh_band         =   1,
            remesh_project      =   0,
            verbose             =   True
        )
        glb.export(temp_proper_glb_path, extension_webp=False)
        
        if not os.path.exists(temp_proper_glb_path):
            raise Exception("GLB export silently failed. Output file not found.")
        
        # Commit the temporary unrigged GLB to make it visible to other apps
        outputs_vol.commit()
        print(f"Raw GLB exported and committed: {temp_proper_glb_path}")
        
        write_status("3D model is ready")
        time.sleep(2)
        write_status("Preparing model for animation")
        
        # Call the SkinTokens rigging backend automatically
        try:
            print("Auto-Rigging: Invoking SkinTokens rigging backend...", flush=True)
            rig_fn = modal.Function.from_name("skintokens-deployment", "rig_glb")
            
            # This calls rig_glb in the skintokens-deployment app
            rig_fn.remote(temp_proper_glb_name, proper_glb_name)
            
            # Reload outputs volume to fetch the rigged GLB written by SkinTokens
            outputs_vol.reload()
            
            if os.path.exists(proper_glb_path):
                print(f"Auto-Rigging: Model successfully rigged! Saved to {proper_glb_path}", flush=True)
                # Clean up the temporary unrigged file
                try:
                    os.remove(temp_proper_glb_path)
                    outputs_vol.commit()
                except Exception:
                    pass
            else:
                print("Warning: Rigged model not found on volume. Falling back to unrigged model.", flush=True)
                os.rename(temp_proper_glb_path, proper_glb_path)
                outputs_vol.commit()
                
        except Exception as e:
            # Fallback gracefully to the unrigged model if rigging fails (e.g. if SkinTokens is not deployed)
            print(f"Warning: Auto-rigging failed ({e}). Falling back to unrigged model.", flush=True)
            os.rename(temp_proper_glb_path, proper_glb_path)
            outputs_vol.commit()
            
        # --- GLB to FBX & Texture Extraction ---
        fbx_filename = f"{animal_clean}_{theme_clean}_{rand_num}.fbx"
        texture_filename = f"{animal_clean}_{theme_clean}_{rand_num}_texture.png"
        fbx_path = f"/outputs/{fbx_filename}"
        
        print(f"Converting final GLB to FBX: {proper_glb_path} -> {fbx_path}")
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(BLENDER_SCRIPT)
            script_path = f.name
            
        try:
            BLENDER = "/opt/blender/blender-4.2.0-linux-x64/blender"
            result = subprocess.run(
                [BLENDER, "--background", "--python", script_path, "--", proper_glb_path, fbx_path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            print(result.stdout)
            if result.returncode != 0:
                print(f"Error: Blender failed with exit code {result.returncode}")
            else:
                print(f"FBX successfully exported to {fbx_path}")
        except Exception as e:
            print(f"Error during Blender GLB to FBX conversion: {e}")
        finally:
            try:
                os.remove(script_path)
            except Exception:
                pass
                
        # Commit outputs volume to ensure FBX and texture are saved
        outputs_vol.commit()
        
        write_status("3D model updated")
        
        response_dict = {
            "status": "success",
            "model_url": f"/download/{proper_glb_name}"
        }
        
        # Add urls if the files were generated successfully
        if os.path.exists(fbx_path):
            response_dict["fbx_url"] = f"/download/{fbx_filename}"
        if os.path.exists(f"/outputs/{texture_filename}"):
            response_dict["texture_url"] = f"/download/{texture_filename}"
            
        return response_dict


# API Routes for FastAPI
class Generate2DRequest(BaseModel):
    animal: str
    category_id: int
    theme_index: int

@fastapi_app.get("/health")
def health():
    return {"status": "ok"}

@fastapi_app.post("/warmup")
def warmup():
    TrellisAPI().warmup.remote()
    return {"status": "warmed_up"}

@fastapi_app.post("/api/generate-2d")
def generate_2d(req: Generate2DRequest):
    import openai
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not set.")
        
    categories = get_themes()
    cat = categories.get(req.category_id)
    if not cat:
        raise HTTPException(status_code=400, detail="Invalid category_id")
    if req.theme_index < 0 or req.theme_index >= len(cat["themes"]):
        raise HTTPException(status_code=400, detail="Invalid theme_index")
        
    theme = cat["themes"][req.theme_index]
    animal = req.animal.strip().title() if req.animal.strip() else "Creature"
    
    master_prompt = (
        f"An adorable, ultra-cute 3D humanoid cartoon {animal} character, standing upright on two legs, "
        f"designed in a distinct hyper-chibi anime aesthetic. Extreme proportional emphasis on an oversized, "
        f"giant round head with large expressive eyes, paired with a tiny, small, stylized body. The character "
        f"is completely empty-handed with open palms, absolutely not holding anything in its hands, keeping both "
        f"hands completely free and visible. The character is themed as a {theme['name']}, dressed in a "
        f"stylized outfit using a curated {theme['palette']} color scheme, wearing a prominent "
        f"{theme['accessory']}. Beautiful smooth surfaces, clean outer outlines, vibrant high-contrast "
        f"professional color combinations. Perfect symmetrical game-ready 3D character asset, relaxed standard "
        f"A-pose, set against a solid pure black background, isolated professional studio lighting, high-quality "
        f"detailed 3D rendering, incredibly cute, charming, and cool vinyl toy aesthetic."
    )
    
    try:
        client = openai.OpenAI(timeout=120)
        response = client.images.generate(
            model="gpt-image-2",
            prompt=master_prompt,
            size="1024x1024",
            quality="high",
            n=1,
        )
        return {"url": response.data[0].url, "image_url": response.data[0].url, "prompt": master_prompt}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@fastapi_app.get("/api/themes")
def get_themes():
    # Keep the same themes data from previous version for frontend compatibility
    categories = {
        1: {
            "name": "Original 10",
            "themes": [
                {"name": "Classic Detective", "accessory": "oversized houndstooth detective hat and a tiny matching buttoned trench coat", "palette": "dark espresso brown, warm cream, and sharp mustard yellow"},
                {"name": "Cyberpunk Netrunner", "accessory": "glowing neon futuristic visor and a high-collar techwear jacket", "palette": "matte black, electric cyan, and hot magenta"},
                {"name": "Steampunk Aviator", "accessory": "brass welding goggles perched on its forehead and a leather bomber jacket with tiny gears", "palette": "deep copper, brushed bronze, and weathered leather brown"},
                {"name": "Royal Knight", "accessory": "shiny oversized silver helmet with a plush red plume and a small chest plate", "palette": "royal blue, polished silver, and crimson red"},
                {"name": "Streetwear Hypebeast", "accessory": "chunky retro sneakers, a backward snapback cap, and an oversized hoodie", "palette": "off-white, vibrant orange, and slate gray"},
                {"name": "Space Astronaut", "accessory": "tinted bubble glass space helmet and a bulky tech suit with patches", "palette": "pure white, nasa blue, and safety orange accents"},
                {"name": "Ancient Wizard", "accessory": "crooked pointed sorcerer's hat embroidered with tiny stars and a flowing robe", "palette": "deep amethyst purple, midnight blue, and metallic gold"},
                {"name": "Retro Sushi Chef", "accessory": "traditional hachimaki headband and a clean minimalist chef tunic", "palette": "crisp white, salmon pink, and dark nori seaweed green"},
                {"name": "Desert Nomad", "accessory": "flowing desert headscarf (shemagh) and a draped poncho with tribal patterns", "palette": "sand beige, terracotta clay, and deep sage green"},
                {"name": "Deep Sea Diver", "accessory": "vintage brass diving helmet with a round window and heavy weighted boots", "palette": "patina teal, dark navy, and industrial yellow"}
            ]
        },
        2: {
            "name": "Fantasy & Adventure",
            "themes": [
                {"name": "Forest Ranger", "accessory": "feathered archer slouch hat and a leafy wrapped leather tunic", "palette": "moss green, autumn amber, and bark brown"},
                {"name": "Viking Berserker", "accessory": "oversized twin-horned iron helmet and a thick fur-lined shoulder mantle", "palette": "steel gray, frosted white, and deep oxblood red"},
                {"name": "Shadow Ninja", "accessory": "wrapped face mask showing only the eyes and a sleek shinobi outfit with tied sashes", "palette": "charcoal black, dark violet, and striking crimson accents"},
                {"name": "High-Seas Pirate", "accessory": "massive tricorn pirate hat with a skull emblem and a tattered captain's coat", "palette": "deep navy blue, weathered crimson, and tarnished gold"},
                {"name": "Ancient Pharaoh", "accessory": "large striped Nemes headdress and a wide jeweled collar plate", "palette": "royal lapis lazuli blue, radiant gold, and turquoise teal"}
            ]
        },
        3: {
            "name": "Modern & Urban Culture",
            "themes": [
                {"name": "Graffiti Artist", "accessory": "tilted bucket hat, a respirator mask hanging around the neck, and paint-splattered overalls", "palette": "acid lime green, dark violet, and asphalt gray"},
                {"name": "DJ Soundwave", "accessory": "huge glowing over-ear headphones and a neon-accented track jacket", "palette": "midnight black, electric violet, and toxic neon green"},
                {"name": "Techwear Urbanite", "accessory": "tactical chest rig harness, cargo jogger pants, and structural straps", "palette": "stealth matte black, olive drab, and clean slate gray"},
                {"name": "Retro Arcade Gamer", "accessory": "pixelated pixel-art sunglasses and a vibrant color-blocked 90s windbreaker", "palette": "hot pink, electric purple, and bright arcade teal"},
                {"name": "BMX Rider", "accessory": "sleek full-face mountain bike helmet and padded riding jerseys", "palette": "vibrant yellow, charcoal gray, and matte white"}
            ]
        },
        4: {
            "name": "Sci-Fi & Future",
            "themes": [
                {"name": "Mecha Pilot", "accessory": "sleek sci-fi armored helmet with a glowing V-shaped visor and angular shoulder pads", "palette": "gundam white, striking crimson, and cobalt blue"},
                {"name": "Synthwave Cruiser", "accessory": "retro-futuristic wireframe shutter shades and a glowing neon grid leather jacket", "palette": "sunset magenta, deep indigo, and laser cyan"},
                {"name": "Alien Explorer", "accessory": "three-eyed biomechanical headpiece and a metallic skin-tight space suit", "palette": "iridescent pearl, toxic lime green, and deep obsidian"},
                {"name": "Interstellar Bounty Hunter", "accessory": "battle-damaged Mandalorian-style helmet and a rugged poncho over high-tech armor", "palette": "weathered steel gray, muted olive green, and dull hazard orange"}
            ]
        },
        5: {
            "name": "Professions & Sports",
            "themes": [
                {"name": "Formula Racer", "accessory": "aerodynamic racing helmet with a dark visor and a sponsors-patched racing jumpsuit", "palette": "fiery F1 red, gloss black, and crisp racing white"},
                {"name": "Lucha Libre Wrestler", "accessory": "intricately patterned Mexican wrestling mask and a flashy champion belt buckle", "palette": "emerald green, bright sunburst yellow, and vivid scarlet"},
                {"name": "Firefighter Hero", "accessory": "heavy yellow firefighter helmet and a reflective turn-out jacket with high-vis stripes", "palette": "dark charcoal, safety neon yellow, and fire engine red"},
                {"name": "Cyber-Medic", "accessory": "glowing cross-emblem tactical mask and a clean futuristic lab coat with tech vials", "palette": "sterile white, soft cyan light, and clean slate blue"},
                {"name": "Safari Explorer", "accessory": "classic pith helmet, a utility vest loaded with pockets, and a tiny rolled-up map pouch", "palette": "khaki tan, olive green, and dark chocolate brown"}
            ]
        },
        6: {
            "name": "Whimsical & Pop Culture",
            "themes": [
                {"name": "Cozy Barista", "accessory": "oversized hipster beanie, a neat tied barista apron, and thick-rimmed glasses", "palette": "roasted coffee bean brown, warm milk cream, and soft sage green"},
                {"name": "Candy Land King", "accessory": "sparkling crown shaped like hard candy and a striped peppermint-swirl regal cape", "palette": "bubblegum pink, sweet pastel blue, and mint green"},
                {"name": "Post-Apocalyptic Scavenger", "accessory": "spiked football shoulder pads, a rusted gas mask, and asymmetrical patchwork clothing", "palette": "rust orange, dusty desert brown, and industrial iron gray"},
                {"name": "Ice Hockey Enforcer", "accessory": "vintage grid-style hockey mask, heavy shoulder pads, and a baggy sports jersey", "palette": "ice white, deep maple maroon, and sharp navy blue"},
                {"name": "Magical Druid", "accessory": "antlered crown woven with fresh flowers and a flowing cape made of leaves", "palette": "rich forest green, floral lavender, and soft birch wood white"},
                {"name": "Corporate Cyber-CEO", "accessory": "glowing futuristic monocle and a sharp, high-collar asymmetrical corporate suit jacket", "palette": "executive corporate navy, crisp platinum silver, and minimalist white"}
            ]
        }
    }
    return categories

@fastapi_app.post("/generate")
def generate_3d(
    image: UploadFile = File(...), 
    remove_bg: bool = Form(True),
    animal: str = Form(None),
    theme: str = Form(None)
):
    try:
        contents = image.file.read()
        uid = str(uuid.uuid4())
        filename = f"{uid}.glb"
        
        # Spawn asynchronously to avoid HTTP timeouts during the 7-minute generation
        call = TrellisAPI().process_image.spawn(contents, filename, remove_bg, animal=animal, theme=theme)
        
        # Write call_id -> uid map file to volume
        map_filename = f"map_{call.object_id}.txt"
        with open(f"/outputs/{map_filename}", "w") as f:
            f.write(uid)
        outputs_vol.commit()
        
        return JSONResponse(content={
            "success": True,
            "uid": uid,
            "call_id": call.object_id
        })
    except Exception as e:
        print("Error in 3D generation:", e)
        raise HTTPException(status_code=500, detail=str(e))

@fastapi_app.get("/status/{call_id}")
def check_status(call_id: str):
    from modal.functions import FunctionCall
    import json
    
    outputs_vol.reload()
    uid = call_id  # fallback
    
    map_filename = f"map_{call_id}.txt"
    map_path = f"/outputs/{map_filename}"
    if os.path.exists(map_path):
        try:
            with open(map_path, "r") as f:
                uid = f.read().strip()
        except Exception:
            pass
            
    status_msg = "3D model is in progress..."
    status_file = f"/outputs/{uid}_status.json"
    if os.path.exists(status_file):
        try:
            with open(status_file, "r") as f:
                status_data = json.load(f)
                status_msg = status_data.get("message", status_msg)
        except Exception:
            pass

    try:
        call = FunctionCall.from_id(call_id)
        # timeout=0 means we return immediately if not finished
        result = call.get(timeout=0)
        
        # Clean up the map and status files
        try:
            if os.path.exists(map_path):
                os.remove(map_path)
            if os.path.exists(status_file):
                os.remove(status_file)
            outputs_vol.commit()
        except Exception:
            pass
            
        return {
            "status": "success",
            "asset_url": result["model_url"],
            "fbx_url": result.get("fbx_url"),
            "texture_url": result.get("texture_url")
        }
    except TimeoutError:
        # Still processing
        return {
            "status": "processing",
            "message": status_msg
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@fastapi_app.get("/download/{filename}")
def download_file(filename: str):
    outputs_vol.reload()
    file_path = f"/outputs/{filename}"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Requested asset file not found")
    
    # Use FileResponse to stream large files iteratively to bypass the 16MB Modal HTTP limit
    from fastapi.responses import FileResponse
    return FileResponse(file_path, media_type="application/octet-stream", filename=filename)

@fastapi_app.delete("/cleanup")
def cleanup_outputs():
    try:
        outputs_vol.reload()
        for filename in os.listdir("/outputs"):
            os.remove(os.path.join("/outputs", filename))
        outputs_vol.commit()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.function(image=trellis_image, volumes={"/outputs": outputs_vol}, secrets=secrets, memory=2048)
@modal.asgi_app()
def fastapi():
    return fastapi_app
