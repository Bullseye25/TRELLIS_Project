import os
import sys
import subprocess
import modal

app = modal.App("animation-merger")

trellis_outputs_vol = modal.Volume.from_name("trellis-outputs", create_if_missing=True)
convert_cache_vol  = modal.Volume.from_name("test-blender-cache", create_if_missing=True)

# Define CUDA container with Blender 4.2.0 installed
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

BLENDER_MERGE_SCRIPT = """
import bpy, sys, os, addon_utils

try:
    walk_path = sys.argv[-4]
    idle_path = sys.argv[-3]
    thinking_path = sys.argv[-2]
    output_path = sys.argv[-1]

    print(f"Merging animations:\\n  Walk: {walk_path}\\n  Idle: {idle_path}\\n  Thinking: {thinking_path}\\n  Output: {output_path}")

    addon_utils.enable("io_scene_fbx", default_set=True)

    # Clear scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Helper to rename action and set fake user
    def import_and_extract_action(fbx_path, action_name):
        pre_existing = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=fbx_path)
        
        imported_objs = [obj for obj in bpy.data.objects if obj not in pre_existing]
        imported_armatures = [obj for obj in imported_objs if obj.type == 'ARMATURE']
        
        if not imported_armatures:
            raise RuntimeError(f"No armature found in {fbx_path}")
            
        arm = imported_armatures[0]
        
        action = None
        if arm.animation_data and arm.animation_data.action:
            action = arm.animation_data.action
            action.name = action_name
            action.use_fake_user = True
            print(f"Extracted action '{action_name}' from {fbx_path}")
        else:
            print(f"WARNING: No active action found on armature in {fbx_path}")
            
        # Delete imported objects safely
        for obj in imported_objs:
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except ReferenceError:
                pass
                
        return action

    # 1. Import walk animation and keep its mesh and armature
    bpy.ops.import_scene.fbx(filepath=walk_path)
    armatures = [obj for obj in bpy.data.objects if obj.type == 'ARMATURE']
    if not armatures:
        raise RuntimeError("No armature found in walk FBX")
    base_arm = armatures[0]
    base_arm.name = "TargetArmature"

    meshes = [child for child in base_arm.children if child.type == 'MESH']
    if not meshes:
        raise RuntimeError("No mesh found parented to armature in walk FBX")
    base_mesh = meshes[0]
    base_mesh.name = "TargetMesh"

    # Rename active action to Walk
    if base_arm.animation_data and base_arm.animation_data.action:
        walk_action = base_arm.animation_data.action
        walk_action.name = "Walk"
        walk_action.use_fake_user = True
    else:
        if bpy.data.actions:
            walk_action = list(bpy.data.actions)[0]
            walk_action.name = "Walk"
            walk_action.use_fake_user = True
        else:
            walk_action = None

    # Delete all other meshes and children parented to armature safely
    children_to_delete = [child for child in base_arm.children if child.type == 'MESH' and child != base_mesh]
    for child in children_to_delete:
        try:
            bpy.data.objects.remove(child, do_unlink=True)
        except ReferenceError:
            pass

    # 2. Extract action from Idle FBX
    idle_action = import_and_extract_action(idle_path, "Idle")

    # 3. Extract action from Thinking FBX
    thinking_action = import_and_extract_action(thinking_path, "Thinking")

    # 4. Clean up parent objects of base_arm
    if base_arm.parent:
        print(f"Removing parent of armature: {base_arm.parent.name}")
        matrix_world = base_arm.matrix_world.copy()
        base_arm.parent = None
        base_arm.matrix_world = matrix_world
        
    # Remove any other non-armature, non-mesh objects safely
    to_remove = [obj for obj in bpy.data.objects if obj != base_arm and obj != base_mesh]
    for obj in to_remove:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except ReferenceError:
            pass

    # 5. Push all three actions to the NLA tracks of the base armature
    if not base_arm.animation_data:
        base_arm.animation_data_create()
        
    base_arm.animation_data.action = None

    # Remove existing NLA tracks
    for track in list(base_arm.animation_data.nla_tracks):
        base_arm.animation_data.nla_tracks.remove(track)

    # Add Walk NLA strip
    if walk_action:
        track = base_arm.animation_data.nla_tracks.new()
        track.name = "Walk"
        track.strips.new("Walk", 1, walk_action)

    # Add Idle NLA strip
    if idle_action:
        track = base_arm.animation_data.nla_tracks.new()
        track.name = "Idle"
        track.strips.new("Idle", 1, idle_action)

    # Add Thinking NLA strip
    if thinking_action:
        track = base_arm.animation_data.nla_tracks.new()
        track.name = "Thinking"
        track.strips.new("Thinking", 1, thinking_action)

    # Make sure base_mesh is parented to base_arm and has armature modifier
    base_mesh.parent = base_arm
    has_armature_mod = False
    for mod in base_mesh.modifiers:
        if mod.type == 'ARMATURE':
            mod.object = base_arm
            has_armature_mod = True
            break
    if not has_armature_mod:
        mod = base_mesh.modifiers.new(name="Armature", type='ARMATURE')
        mod.object = base_arm

    # Export to FBX
    bpy.ops.export_scene.fbx(
        filepath=output_path,
        check_existing=False,
        bake_anim=True,
        bake_anim_use_all_actions=False,
        bake_anim_use_nla_strips=True,
        path_mode="AUTO",
        embed_textures=False
    )
    print("Successfully merged FBX on Modal!")
    
    # Export to GLB (contains all NLA strips/animations)
    glb_output_path = os.path.splitext(output_path)[0] + ".glb"
    bpy.ops.export_scene.gltf(
        filepath=glb_output_path,
        export_format='GLB',
        export_animations=True
    )
    print("Successfully exported merged GLB on Modal!")

except Exception as e:
    import traceback
    print(f"ERROR: {e}")
    traceback.print_exc()
    sys.exit(1)
"""

@app.function(volumes={"/outputs": trellis_outputs_vol})
def clean_volume(keep_fbx: str):
    import os
    if not keep_fbx:
        print("[clean_volume] No keep_fbx provided. Skipping volume cleanup to protect outputs.")
        return []
    trellis_outputs_vol.reload()
    
    # Extract base prefix (e.g. dog_retro_arcade_gamer_11735)
    base_prefix = os.path.splitext(keep_fbx)[0] if keep_fbx else ""
    
    deleted = []
    for f in os.listdir("/outputs"):
        if f.lower() in ["walking.fbx", "idle.fbx", "animation"]:
            continue
        if base_prefix and f.startswith(base_prefix):
            continue
        if f == keep_fbx:
            continue
        if f.endswith(".glb") or f.endswith(".fbx") or f.endswith(".png"):
            try:
                os.remove(os.path.join("/outputs", f))
                deleted.append(f)
            except Exception as e:
                print(f"Error removing {f}: {e}")
    if deleted:
        trellis_outputs_vol.commit()
        print(f"[clean_volume] Deleted: {deleted}")
    return deleted

@app.function(image=inspect_image, volumes={"/outputs": trellis_outputs_vol, "/cache": convert_cache_vol}, timeout=300)
def merge_anims(mesh_fbx: str, walk_fbx: str, idle_fbx: str, thinking_fbx: str, output_fbx: str):
    import subprocess, tempfile, os
    
    trellis_outputs_vol.reload()
    convert_cache_vol.reload()
    
    # Paths on volume
    walk_path = f"/cache/{walk_fbx}"
    idle_path = f"/outputs/animation/{idle_fbx}"
    thinking_path = f"/outputs/animation/{thinking_fbx}"
    output_path = f"/outputs/{output_fbx}"
    
    # Verify existences
    if not os.path.exists(walk_path):
        raise FileNotFoundError(f"Walk FBX not found: {walk_path}")
    if not os.path.exists(idle_path):
        raise FileNotFoundError(f"Idle FBX not found: {idle_path}")
    if not os.path.exists(thinking_path):
        raise FileNotFoundError(f"Thinking FBX not found: {thinking_path}")
        
    print(f"[merge_anims] Inputs: {walk_path}, {idle_path}, {thinking_path}")
    print(f"[merge_anims] Output: {output_path}")
    
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(BLENDER_MERGE_SCRIPT)
        script_path = f.name
        
    try:
        res = subprocess.run([
            BLENDER, "--background", "--python", script_path, "--",
            walk_path, idle_path, thinking_path, output_path
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        print(res.stdout)
        if res.returncode != 0:
            raise RuntimeError(f"Blender merge failed with code {res.returncode}")
    finally:
        os.remove(script_path)
        
    trellis_outputs_vol.commit()
    print(f"[merge_anims] Saved merged FBX on volume: {output_fbx}")
    return True

@app.function(volumes={"/outputs": trellis_outputs_vol, "/cache": convert_cache_vol})
def cleanup_intermediates(walk_fbx: str, idle_fbx: str, thinking_fbx: str):
    import os
    trellis_outputs_vol.reload()
    convert_cache_vol.reload()
    deleted = []
    
    # 1. Clean walk animation in /cache/ or /outputs/animation/
    for path in [f"/cache/{walk_fbx}", f"/outputs/animation/{walk_fbx}"]:
        if os.path.exists(path):
            try:
                os.remove(path)
                deleted.append(path)
            except Exception as e:
                print(f"Error removing {path}: {e}")
                
    # 2. Clean idle animation in /outputs/animation/
    idle_path = f"/outputs/animation/{idle_fbx}"
    if os.path.exists(idle_path):
        try:
            os.remove(idle_path)
            deleted.append(idle_path)
        except Exception as e:
            print(f"Error removing {idle_path}: {e}")
            
    # 3. Clean thinking animation in /outputs/animation/
    thinking_path = f"/outputs/animation/{thinking_fbx}"
    if os.path.exists(thinking_path):
        try:
            os.remove(thinking_path)
            deleted.append(thinking_path)
        except Exception as e:
            print(f"Error removing {thinking_path}: {e}")
            
    if deleted:
        trellis_outputs_vol.commit()
        convert_cache_vol.commit()
        print(f"[cleanup_intermediates] Deleted intermediate files: {deleted}")
    return deleted

@app.local_entrypoint()
def main(keep_fbx: str = None, merge: bool = False, walk_fbx: str = None, idle_fbx: str = None, thinking_fbx: str = None, output_fbx: str = None, cleanup: bool = False):
    if keep_fbx:
        print(f"Cleaning volume except {keep_fbx}...")
        clean_volume.remote(keep_fbx)
    if merge and walk_fbx and idle_fbx and thinking_fbx and output_fbx:
        print("Merging animations on Modal...")
        merge_anims.remote("", walk_fbx, idle_fbx, thinking_fbx, output_fbx)
    if cleanup and walk_fbx and idle_fbx and thinking_fbx:
        print("Cleaning up intermediate animation files on Modal...")
        cleanup_intermediates.remote(walk_fbx, idle_fbx, thinking_fbx)
