import os
import sys
import subprocess
import modal

app = modal.App("glb-procedural-animator")

trellis_outputs_vol = modal.Volume.from_name("trellis-outputs", create_if_missing=True)
convert_cache_vol  = modal.Volume.from_name("test-blender-cache", create_if_missing=True)

inspect_image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.11")
    .apt_install("wget", "tar", "xz-utils", "libgl1-mesa-glx", "libglib2.0-0",
                 "libxrender1", "libxxf86vm1", "libxfixes3", "libxi6",
                 "libxkbcommon0", "libsm6", "libegl1")
    .run_commands(
        "mkdir -p /opt/blender",
        "wget -q https://download.blender.org/release/Blender4.2/blender-4.2.0-linux-x64.tar.xz -O /tmp/blender.tar.xz",
        "tar -xf /tmp/blender.tar.xz -C /opt/blender",
        "rm /tmp/blender.tar.xz"
    )
)

BLENDER = "/opt/blender/blender-4.2.0-linux-x64/blender"

BLENDER_PROCEDURAL_SCRIPT = """
import bpy, sys, os, addon_utils, math

try:
    target_mesh_path = sys.argv[-2]
    output_fbx_path  = sys.argv[-1]

    addon_utils.enable("io_scene_gltf2", default_set=True)

    # Clear scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # 1. Import target rigged GLB model
    print(f"Importing target model: {target_mesh_path}")
    bpy.ops.import_scene.gltf(filepath=target_mesh_path)
    
    # Identify target armature
    target_armatures = [obj for obj in bpy.data.objects if obj.type == 'ARMATURE']
    if not target_armatures:
        raise RuntimeError("No armature found in target model.")
    target_arm = target_armatures[0]
    target_arm.name = "TargetArmature"
    num_bones = len(target_arm.data.bones)
    print(f"Target armature loaded with {num_bones} bones.")

    # 2. Define bone mapping and rename bones
    if num_bones == 34:
        # Bear Rig
        mapping = {
            "bone_0": "mixamorig:Hips",
            "bone_1": "mixamorig:Spine",
            "bone_2": "mixamorig:Spine1",
            "bone_3": "mixamorig:Spine2",
            "bone_4": "mixamorig:Neck",
            "bone_5": "mixamorig:Head",
            "bone_6": "mixamorig:LeftShoulder",
            "bone_7": "mixamorig:LeftArm",
            "bone_8": "mixamorig:LeftForeArm",
            "bone_9": "mixamorig:LeftHand",
            "bone_10": "mixamorig:LeftHandIndex1",
            "bone_11": "mixamorig:LeftHandIndex2",
            "bone_12": "mixamorig:LeftHandIndex3",
            "bone_13": "mixamorig:LeftHandThumb1",
            "bone_14": "mixamorig:LeftHandThumb2",
            "bone_15": "mixamorig:LeftHandThumb3",
            "bone_16": "mixamorig:RightShoulder",
            "bone_17": "mixamorig:RightArm",
            "bone_18": "mixamorig:RightForeArm",
            "bone_19": "mixamorig:RightHand",
            "bone_20": "mixamorig:RightHandIndex1",
            "bone_21": "mixamorig:RightHandIndex2",
            "bone_22": "mixamorig:RightHandIndex3",
            "bone_23": "mixamorig:RightHandThumb1",
            "bone_24": "mixamorig:RightHandThumb2",
            "bone_25": "mixamorig:RightHandThumb3",
            "bone_26": "mixamorig:LeftUpLeg",
            "bone_27": "mixamorig:LeftLeg",
            "bone_28": "mixamorig:LeftFoot",
            "bone_29": "mixamorig:LeftToeBase",
            "bone_30": "mixamorig:RightUpLeg",
            "bone_31": "mixamorig:RightLeg",
            "bone_32": "mixamorig:RightFoot",
            "bone_33": "mixamorig:RightToeBase"
        }
    elif num_bones == 22:
        # Lion Rig
        mapping = {
            "bone_0": "mixamorig:Hips",
            "bone_1": "mixamorig:Spine",
            "bone_2": "mixamorig:Spine1",
            "bone_3": "mixamorig:Spine2",
            "bone_4": "mixamorig:Neck",
            "bone_5": "mixamorig:Head",
            "bone_6": "mixamorig:LeftArm",
            "bone_7": "mixamorig:LeftForeArm",
            "bone_8": "mixamorig:LeftHand",
            "bone_9": "mixamorig:LeftHandIndex1",
            "bone_10": "mixamorig:RightArm",
            "bone_11": "mixamorig:RightForeArm",
            "bone_12": "mixamorig:RightHand",
            "bone_13": "mixamorig:RightHandIndex1",
            "bone_14": "mixamorig:LeftUpLeg",
            "bone_15": "mixamorig:LeftLeg",
            "bone_16": "mixamorig:LeftFoot",
            "bone_17": "mixamorig:LeftToeBase",
            "bone_18": "mixamorig:RightUpLeg",
            "bone_19": "mixamorig:RightLeg",
            "bone_20": "mixamorig:RightFoot",
            "bone_21": "mixamorig:RightToeBase"
        }
    elif num_bones == 19:
        # 19-bone Rig (Humanoid without fingers/toes)
        mapping = {
            "bone_0": "mixamorig:Hips",
            "bone_1": "mixamorig:Spine",
            "bone_2": "mixamorig:Spine2",
            "bone_3": "mixamorig:Neck",
            "bone_4": "mixamorig:Head",
            "bone_5": "mixamorig:LeftArm",
            "bone_6": "mixamorig:LeftForeArm",
            "bone_7": "mixamorig:LeftHand",
            "bone_8": "mixamorig:LeftHandIndex1",
            "bone_9": "mixamorig:RightArm",
            "bone_10": "mixamorig:RightForeArm",
            "bone_11": "mixamorig:RightHand",
            "bone_12": "mixamorig:RightHandIndex1",
            "bone_13": "mixamorig:LeftUpLeg",
            "bone_14": "mixamorig:LeftLeg",
            "bone_15": "mixamorig:LeftFoot",
            "bone_16": "mixamorig:RightUpLeg",
            "bone_17": "mixamorig:RightLeg",
            "bone_18": "mixamorig:RightFoot",
        }
    else:
        raise RuntimeError(f"Unsupported bone count {num_bones}. Must be 19, 22, or 34.")

    # Rename bones in target armature object data
    for old_name, new_name in mapping.items():
        if old_name in target_arm.data.bones:
            target_arm.data.bones[old_name].name = new_name
            
    # Set up variables pointing to Mixamo names for the animation loop
    hips = "mixamorig:Hips"
    spine = "mixamorig:Spine"
    left_up_leg = "mixamorig:LeftUpLeg"
    left_leg = "mixamorig:LeftLeg"
    left_foot = "mixamorig:LeftFoot"
    right_up_leg = "mixamorig:RightUpLeg"
    right_leg = "mixamorig:RightLeg"
    right_foot = "mixamorig:RightFoot"
    left_arm = "mixamorig:LeftArm"
    left_forearm = "mixamorig:LeftForeArm"
    right_arm = "mixamorig:RightArm"
    right_forearm = "mixamorig:RightForeArm"

    # 3. Apply procedural walk cycle frame-by-frame
    bpy.context.view_layer.objects.active = target_arm
    bpy.ops.object.mode_set(mode='POSE')

    # Clear any existing animation data
    if target_arm.animation_data:
        target_arm.animation_data_clear()

    # Set rotation mode to XYZ for procedural math
    animated_bones = [hips, spine, left_up_leg, left_leg, left_foot, right_up_leg, right_leg, right_foot, left_arm, left_forearm, right_arm, right_forearm]
    for b_name in animated_bones:
        if b_name in target_arm.pose.bones:
            target_arm.pose.bones[b_name].rotation_mode = 'XYZ'

    start_frame = 1
    end_frame = 32
    bpy.context.scene.frame_start = start_frame
    bpy.context.scene.frame_end = end_frame

    # Set knee and elbow bending multipliers (based on target skeletal roll orientation)
    # Knees bend backwards, elbows bend forwards/inwards
    KNEE_DIR = 1.0
    ELBOW_DIR = 1.0

    print("Generating walk cycle keyframes...")
    for frame in range(start_frame, end_frame + 1):
        bpy.context.scene.frame_set(frame)
        
        # Calculate phase (0 to 2*pi)
        phi = 2.0 * math.pi * (frame - start_frame) / (end_frame - start_frame)
        
        # --- 1. HIPS BOBBING & SWAYING ---
        p_hips = target_arm.pose.bones[hips]
        p_hips.location.z = -0.04 * abs(math.sin(phi))  # Up-down bobbing twice per cycle
        p_hips.location.x = 0.015 * math.sin(phi)       # Slight side-to-side hip sway
        p_hips.location.y = 0.0                         # Keep strictly in-place (no forward movement)
        p_hips.keyframe_insert(data_path="location", frame=frame)
        
        p_hips.rotation_euler.x = 0.04 * math.sin(phi)  # Slight pitch tilt
        p_hips.rotation_euler.z = -0.05 * math.cos(phi) # Slight yaw twist
        p_hips.rotation_euler.y = 0.0
        p_hips.keyframe_insert(data_path="rotation_euler", frame=frame)
        
        # --- 2. SPINE TWISTING ---
        p_spine = target_arm.pose.bones[spine]
        p_spine.rotation_euler.z = 0.05 * math.cos(phi) # Twist chest opposite to hips
        p_spine.rotation_euler.x = -0.02 * math.sin(phi)
        p_spine.keyframe_insert(data_path="rotation_euler", frame=frame)
        
        # --- 3. THIGHS (LEG SWING) ---
        l_thigh_x = 0.35 * math.sin(phi)
        r_thigh_x = -0.35 * math.sin(phi)
        
        p_l_upl = target_arm.pose.bones[left_up_leg]
        p_l_upl.rotation_euler.x = l_thigh_x
        p_l_upl.rotation_euler.y = -0.05               # Spread thigh outward slightly
        p_l_upl.keyframe_insert(data_path="rotation_euler", frame=frame)
        
        p_r_upl = target_arm.pose.bones[right_up_leg]
        p_r_upl.rotation_euler.x = r_thigh_x
        p_r_upl.rotation_euler.y = 0.05                # Spread thigh outward
        p_r_upl.keyframe_insert(data_path="rotation_euler", frame=frame)
        
        # --- 4. KNEES (LEG BEND) ---
        # Knees bend only backward (when the leg is lifting/swinging backward)
        # Left leg swings backward when cos(phi) < 0
        l_knee_x = 0.5 * (1.0 + math.sin(phi - math.pi/2.0)) if math.cos(phi) < 0 else 0.0
        r_knee_x = 0.5 * (1.0 - math.sin(phi - math.pi/2.0)) if math.cos(phi) > 0 else 0.0
        
        p_l_leg = target_arm.pose.bones[left_leg]
        p_l_leg.rotation_euler.x = KNEE_DIR * l_knee_x
        p_l_leg.keyframe_insert(data_path="rotation_euler", frame=frame)
        
        p_r_leg = target_arm.pose.bones[right_leg]
        p_r_leg.rotation_euler.x = KNEE_DIR * r_knee_x
        p_r_leg.keyframe_insert(data_path="rotation_euler", frame=frame)
        
        # --- 5. FEET (ANKLE ROTATION) ---
        # Counter-rotate ankles so feet stay parallel to the floor during contact
        p_l_foot = target_arm.pose.bones[left_foot]
        p_l_foot.rotation_euler.x = -l_thigh_x - (0.5 * l_knee_x)
        p_l_foot.keyframe_insert(data_path="rotation_euler", frame=frame)
        
        p_r_foot = target_arm.pose.bones[right_foot]
        p_r_foot.rotation_euler.x = -r_thigh_x - (0.5 * r_knee_x)
        p_r_foot.keyframe_insert(data_path="rotation_euler", frame=frame)
        
        # --- 6. SHOULDERS (ARM SWING) ---
        # Arms swing in opposition to legs
        l_arm_x = -0.25 * math.sin(phi)
        r_arm_x = 0.25 * math.sin(phi)
        
        p_l_arm = target_arm.pose.bones[left_arm]
        p_l_arm.rotation_euler.x = l_arm_x
        p_l_arm.rotation_euler.z = 0.25                # Keep arms outward from wide chibi head
        p_l_arm.keyframe_insert(data_path="rotation_euler", frame=frame)
        
        p_r_arm = target_arm.pose.bones[right_arm]
        p_r_arm.rotation_euler.x = r_arm_x
        p_r_arm.rotation_euler.z = -0.25               # Keep arms outward
        p_r_arm.keyframe_insert(data_path="rotation_euler", frame=frame)
        
        # --- 7. FOREARMS (ELBOW BEND) ---
        # Elbows remain slightly bent, bending further on arm backswing
        p_l_fore = target_arm.pose.bones[left_forearm]
        p_l_fore.rotation_euler.x = ELBOW_DIR * (0.35 + 0.15 * math.cos(phi))
        p_l_fore.keyframe_insert(data_path="rotation_euler", frame=frame)
        
        p_r_fore = target_arm.pose.bones[right_forearm]
        p_r_fore.rotation_euler.x = ELBOW_DIR * (0.35 - 0.15 * math.cos(phi))
        p_r_fore.keyframe_insert(data_path="rotation_euler", frame=frame)

    # 4. Save and Export target model with baked procedural animation
    bpy.ops.object.mode_set(mode='OBJECT')
    
    print(f"Exporting procedural walk FBX to: {output_fbx_path}")
    bpy.ops.export_scene.fbx(
        filepath=output_fbx_path,
        check_existing=False,
        bake_anim=True,
        path_mode='AUTO',
        embed_textures=False
    )
    print("FBX export complete.")
except Exception as e:
    import traceback
    print("ERROR:", e)
    traceback.print_exc()
    sys.exit(1)
"""

@app.function(
    image=inspect_image,
    volumes={"/outputs": trellis_outputs_vol, "/cache": convert_cache_vol},
    timeout=300,
)
def generate_walk_anim(mesh_glb: str) -> bytes:
    import tempfile, os, subprocess

    trellis_outputs_vol.reload()
    
    target_path = f"/outputs/{mesh_glb}"
    output_path = f"/cache/walk_procedural_{mesh_glb.replace('.glb', '.fbx')}"
    
    if not os.path.exists(target_path):
        raise FileNotFoundError(f"Target model {mesh_glb} not found on volume.")

    print(f"Generating procedural walk animation on {mesh_glb}...")
    
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(BLENDER_PROCEDURAL_SCRIPT)
        script = f.name

    try:
        process = subprocess.Popen(
            [BLENDER, "--background", "--python", script, "--", target_path, output_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        for line in process.stdout:
            print(line, end="", flush=True)
        process.wait()
        if process.returncode != 0:
            raise RuntimeError(f"Blender exited with code {process.returncode}")
        if not os.path.exists(output_path):
            raise RuntimeError("Animated FBX was not exported.")
    finally:
        os.remove(script)
        
    convert_cache_vol.commit()
    return open(output_path, "rb").read()

@app.function(volumes={"/outputs": trellis_outputs_vol})
def list_glb_files():
    trellis_outputs_vol.reload()
    return sorted(f for f in os.listdir("/outputs") if f.endswith(".glb"))

@app.local_entrypoint()
def main(char: int = -1):
    # 1. Fetch file list first to trigger Modal initialization and mount logs before banner/prompts
    print("Initializing Modal connection and listing files on volume...")
    try:
        files = list_glb_files.remote()
    except Exception as e:
        print(f"Error connecting to Modal: {e}")
        return

    print("==================================================")
    print("   Modal Chibi GLB Procedural Walk Generator      ")
    print("==================================================")
    
    if not files:
        print("No GLB files found on the volume.")
        return
        
    # 2. Select Rigged Character Mesh
    if char != -1 and 0 <= char < len(files):
        selected_char = files[char]
        print(f"Selected Character (from argument): {selected_char}")
    else:
        print("\nAvailable Rigged Chibi GLB Files:")
        for idx, f in enumerate(files):
            print(f"  [{idx}] {f}")
            
        target_idx = input("\nSelect the Rigged character GLB (enter number): ").strip()
        if not target_idx.isdigit() or not (0 <= int(target_idx) < len(files)):
            print("Invalid character selection.")
            return
        selected_char = files[int(target_idx)]
    
    print(f"\nGenerating walk cycle for: {selected_char}")
    
    try:
        # 3. Trigger Retargeting on Modal
        with modal.enable_output():
            animated_bytes = generate_walk_anim.remote(selected_char)
            
        # 4. Save to macOS Downloads folder
        dl_dir = os.path.expanduser("~/Downloads")
        os.makedirs(dl_dir, exist_ok=True)
        
        model_id = os.path.splitext(selected_char)[0]
        output_name = f"{model_id}_walk_procedural.fbx"
        output_path = os.path.join(dl_dir, output_name)
        
        with open(output_path, "wb") as f:
            f.write(animated_bytes)
            
        print(f"\n[+] SUCCESS! Procedural walk FBX saved to: {output_path} ({len(animated_bytes):,} bytes)")
        print("==================================================")
        
    except Exception as e:
        print(f"\n[-] Procedural walk generation failed: {e}")

if __name__ == "__main__":
    main()
