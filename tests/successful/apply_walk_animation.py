import os
import sys
import subprocess
import modal

app = modal.App("glb-animation-retargeter")

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

BLENDER_RETARGET_SCRIPT = """
import bpy, sys, os, addon_utils

MAP_34 = {
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
    "bone_33": "mixamorig:RightToeBase",
}

MAP_22 = {
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
    "bone_21": "mixamorig:RightToeBase",
}

MAP_19 = {
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

try:
    target_mesh_path = sys.argv[-3]
    source_anim_path = sys.argv[-2]
    output_fbx_path  = sys.argv[-1]

    addon_utils.enable("io_scene_gltf2", default_set=True)
    addon_utils.enable("io_scene_fbx",   default_set=True)

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

    # 2. Import source animation (FBX or GLB)
    print(f"Importing source animation: {source_anim_path}")
    if source_anim_path.lower().endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=source_anim_path)
    else:
        bpy.ops.import_scene.gltf(filepath=source_anim_path)
        
    # Identify source armature
    source_armatures = [obj for obj in bpy.data.objects if obj.type == 'ARMATURE' and obj.name != "TargetArmature"]
    if not source_armatures:
        raise RuntimeError("No armature found in source animation.")
    source_arm = source_armatures[0]
    source_arm.name = "SourceArmature"
    print(f"Source armature loaded: {source_arm.name}")

    # Determine mapping dictionary
    if num_bones == 34:
        mapping = MAP_34
    elif num_bones == 22:
        mapping = MAP_22
    elif num_bones == 19:
        mapping = MAP_19
    else:
        # Fallback dynamic mapping if bone count varies
        print(f"Warning: Unexpected bone count {num_bones}. Attempting fallback index-based mapping.")
        mapping = {}
        if num_bones < 22:
            base_map = MAP_19
        elif num_bones < 34:
            base_map = MAP_22
        else:
            base_map = MAP_34
            
        for i in range(num_bones):
            bone_name = f"bone_{i}"
            if bone_name in base_map:
                mapping[bone_name] = base_map[bone_name]

    # 3. Add bone constraints from target bones to source bones
    bpy.context.view_layer.objects.active = target_arm
    bpy.ops.object.mode_set(mode='POSE')

    # Select all pose bones in target
    bpy.ops.pose.select_all(action='SELECT')
    
    for bone_name in target_arm.pose.bones.keys():
        if bone_name in mapping:
            src_bone_name = mapping[bone_name]
            # Verify bone exists in source armature
            if src_bone_name in source_arm.pose.bones:
                pbone = target_arm.pose.bones[bone_name]
                
                # Copy rotation
                con_rot = pbone.constraints.new(type='COPY_ROTATION')
                con_rot.target = source_arm
                con_rot.subtarget = src_bone_name
                con_rot.target_space = 'POSE'
                con_rot.owner_space = 'POSE'
                
                # Copy Hips position (translation) for bobbing and forward walking movement
                if bone_name == "bone_0":
                    con_loc = pbone.constraints.new(type='COPY_LOCATION')
                    con_loc.target = source_arm
                    con_loc.subtarget = src_bone_name
                    con_loc.target_space = 'POSE'
                    con_loc.owner_space = 'POSE'
                    print("Added copy location to hips/root.")
                    
                print(f"Constrained: {bone_name} -> {src_bone_name}")

    # 4. Bake constraints to target armature keyframes
    # Find frame range
    start_frame = 1
    end_frame = 250
    if source_arm.animation_data and source_arm.animation_data.action:
        act = source_arm.animation_data.action
        start_frame = int(act.frame_range[0])
        end_frame = int(act.frame_range[1])
        print(f"Baking frames: {start_frame} to {end_frame} from source action '{act.name}'")

    bpy.ops.nla.bake(
        frame_start=start_frame,
        frame_end=end_frame,
        step=1,
        only_selected=False,
        visual_keying=True,
        clear_constraints=True,
        bake_types={'POSE'}
    )
    print("Baking completed successfully.")

    # 5. Clean up source armature to prevent exporting it
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.data.objects.remove(source_arm, do_unlink=True)

    # 6. Select only target character for export
    for obj in bpy.data.objects:
        obj.select_set(False)

    target_arm.select_set(True)
    for child in target_arm.children:
        child.select_set(True)

    bpy.context.view_layer.objects.active = target_arm

    # 7. Export animated FBX
    print(f"Exporting animated FBX: {output_fbx_path}")
    bpy.ops.export_scene.fbx(
        filepath=output_fbx_path,
        use_selection=True,
        bake_anim=True,
        bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=False,
        add_leaf_bones=False,
        path_mode='COPY',
        embed_textures=True
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
def retarget_glb_animation(mesh_glb: str, anim_file: str) -> bytes:
    import tempfile, os, subprocess

    trellis_outputs_vol.reload()
    
    target_path = f"/outputs/{mesh_glb}"
    source_path = f"/outputs/{anim_file}"
    base_name = os.path.splitext(mesh_glb)[0]
    output_path = f"/cache/{base_name}_animated.fbx"
    
    if not os.path.exists(target_path):
        raise FileNotFoundError(f"Target model {mesh_glb} not found on outputs volume.")
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Animation file {anim_file} not found on outputs volume.")

    print(f"Retargeting {anim_file} onto {mesh_glb}...")
    
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(BLENDER_RETARGET_SCRIPT)
        script = f.name

    try:
        process = subprocess.Popen(
            [BLENDER, "--background", "--python", script, "--", target_path, source_path, output_path],
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
def list_volume_files():
    trellis_outputs_vol.reload()
    return sorted(os.listdir("/outputs"))

@app.local_entrypoint()
def main(char: int = -1, anim: int = -1):
    # 1. Fetch file list first to trigger Modal initialization and mount logs before banner/prompts
    print("Initializing Modal connection and listing files on volume...")
    try:
        files = list_volume_files.remote()
    except Exception as e:
        print(f"Error connecting to Modal: {e}")
        return

    print("==================================================")
    print("  Modal AI Humanoid GLB Animation Retargeter      ")
    print("==================================================")
    
    characters = [
        f for f in files
        if f.lower().endswith(".glb")
    ]

    animations = [
        f for f in files
        if f.lower().endswith((".fbx", ".glb"))
    ]
    
    if not characters:
        print("No rigged character GLB files found on the volume.")
        return
        
    if not animations:
        print("No animation files found on the volume.")
        return
        
    # 2. Select Rigged Character Mesh
    if char != -1 and 0 <= char < len(characters):
        selected_char = characters[char]
        print(f"Selected Character (from argument): {selected_char}")
    else:
        print("\nAvailable Rigged Character GLB Files:")
        for idx, f in enumerate(characters):
            print(f"  [{idx}] {f}")
            
        target_idx = input("\nSelect the Rigged character GLB (enter number): ").strip()
        if not target_idx.isdigit() or not (0 <= int(target_idx) < len(characters)):
            print("Invalid character selection.")
            return
        selected_char = characters[int(target_idx)]
    
    # 3. Select Mixamo Animation File
    if anim != -1 and 0 <= anim < len(animations):
        selected_anim = animations[anim]
        print(f"Selected Animation (from argument): {selected_anim}")
    else:
        print("\nAvailable Animation Files (FBX or GLB):")
        for idx, f in enumerate(animations):
            print(f"  [{idx}] {f}")
            
        anim_idx = input("\nSelect the Mixamo walk animation file on volume (enter number): ").strip()
        if not anim_idx.isdigit() or not (0 <= int(anim_idx) < len(animations)):
            print("Invalid animation selection.")
            return
        selected_anim = animations[int(anim_idx)]
    
    print(f"\nProcessing Retargeting...")
    print(f"Character: {selected_char}")
    print(f"Animation: {selected_anim}")
    
    try:
        # 4. Trigger Retargeting on Modal
        with modal.enable_output():
            animated_bytes = retarget_glb_animation.remote(selected_char, selected_anim)
        
        # 5. Save to macOS Downloads folder
        dl_dir = os.path.expanduser("~/Downloads")
        os.makedirs(dl_dir, exist_ok=True)
        
        model_id = os.path.splitext(selected_char)[0]
        output_name = f"{model_id}_animated.fbx"
        output_path = os.path.join(dl_dir, output_name)
        
        with open(output_path, "wb") as f:
            f.write(animated_bytes)
            
        print(f"\n[+] SUCCESS! Animated FBX saved to: {output_path} ({len(animated_bytes):,} bytes)")
        print("==================================================")
        
    except Exception as e:
        print(f"\n[-] Animation retargeting failed: {e}")

if __name__ == "__main__":
    main()
