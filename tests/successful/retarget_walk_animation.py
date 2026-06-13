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

    # 2. Rename bones to corrected Mixamo naming structure
    if num_bones == 34:
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
        # Dynamic fallback search if bone count varies
        print(f"Warning: Unexpected bone count {num_bones}. Attempting fallback index-based mapping.")
        mapping = {}
        if num_bones < 22:
            base_map = {
                0: "mixamorig:Hips", 1: "mixamorig:Spine", 2: "mixamorig:Spine2",
                3: "mixamorig:Neck", 4: "mixamorig:Head", 5: "mixamorig:LeftArm",
                6: "mixamorig:LeftForeArm", 7: "mixamorig:LeftHand", 8: "mixamorig:LeftHandIndex1",
                9: "mixamorig:RightArm", 10: "mixamorig:RightForeArm", 11: "mixamorig:RightHand",
                12: "mixamorig:RightHandIndex1", 13: "mixamorig:LeftUpLeg", 14: "mixamorig:LeftLeg",
                15: "mixamorig:LeftFoot", 16: "mixamorig:RightUpLeg", 17: "mixamorig:RightLeg",
                18: "mixamorig:RightFoot"
            }
        else:
            base_map = {
                0: "mixamorig:Hips", 1: "mixamorig:Spine", 2: "mixamorig:Spine1",
                3: "mixamorig:Spine2", 4: "mixamorig:Neck", 5: "mixamorig:Head",
                6: "mixamorig:LeftArm", 7: "mixamorig:LeftForeArm", 8: "mixamorig:LeftHand",
                9: "mixamorig:LeftHandIndex1", 10: "mixamorig:RightArm", 11: "mixamorig:RightForeArm",
                12: "mixamorig:RightHand", 13: "mixamorig:RightHandIndex1", 14: "mixamorig:LeftUpLeg",
                15: "mixamorig:LeftLeg", 16: "mixamorig:LeftFoot", 17: "mixamorig:LeftToeBase",
                18: "mixamorig:RightUpLeg", 19: "mixamorig:RightLeg", 20: "mixamorig:RightFoot",
                21: "mixamorig:RightToeBase"
            }
        for i in range(num_bones):
            bone_name = f"bone_{i}"
            if i in base_map:
                mapping[bone_name] = base_map[i]

    # Rename target bones
    for old_name, new_name in mapping.items():
        if old_name in target_arm.data.bones:
            target_arm.data.bones[old_name].name = new_name

    # Remove Icosphere from the model before exporting
    print("Removing Icosphere from target scene...")
    removed_count = 0
    for obj in list(bpy.data.objects):
        if "icosphere" in obj.name.lower():
            print(f"Removing object: {obj.name}")
            bpy.data.objects.remove(obj, do_unlink=True)
            removed_count += 1
    print(f"Removed {removed_count} Icosphere objects.")

    # 3. Import source animation (Walking.fbx)
    print(f"Importing source animation: {source_anim_path}")
    bpy.ops.import_scene.fbx(filepath=source_anim_path)

    # Identify source armature
    source_armatures = [obj for obj in bpy.data.objects if obj.type == 'ARMATURE' and obj.name != "TargetArmature"]
    if not source_armatures:
        raise RuntimeError("No source armature found.")
    source_arm = source_armatures[0]
    source_arm.name = "SourceArmature"
    print(f"Source armature loaded: {source_arm.name}")

    # Ensure rotation mode is Quaternion for retargeting math
    for pbone in target_arm.pose.bones:
        pbone.rotation_mode = 'QUATERNION'
    for pbone in source_arm.pose.bones:
        pbone.rotation_mode = 'QUATERNION'

    # Determine frame range
    start_frame = 1
    end_frame = 250
    if source_arm.animation_data and source_arm.animation_data.action:
        act = source_arm.animation_data.action
        start_frame = int(act.frame_range[0])
        end_frame = int(act.frame_range[1])
    print(f"Animation frame range: {start_frame} to {end_frame}")

    # Clear target animation data
    if target_arm.animation_data:
        target_arm.animation_data_clear()

    # Go to rest pose to capture default locations
    bpy.context.scene.frame_start = start_frame
    bpy.context.scene.frame_end = end_frame
    bpy.context.scene.frame_set(start_frame)
    bpy.context.view_layer.update()

    # Store rest local locations for all bones to prevent stretching
    rest_locations = {}
    for pbone in target_arm.pose.bones:
        rest_locations[pbone.name] = pbone.location.copy()
        
    tgt_hips_rest_loc = rest_locations["mixamorig:Hips"]
    print(f"Target Hips Rest local position: {tgt_hips_rest_loc}")

    # Helper function for Swing-Twist decomposition that preserves static 180-degree roll flips
    def damp_dynamic_twist_y(q, twist_scale=0.0):
        if q.w < 0:
            q = -q
        w, x, y, z = q.w, q.x, q.y, q.z
        mag = (w*w + y*y)**0.5
        if mag > 1e-6:
            q_twist = mathutils.Quaternion((w/mag, 0.0, y/mag, 0.0))
        else:
            q_twist = mathutils.Quaternion((1.0, 0.0, 0.0, 0.0))
        
        q_swing = q @ q_twist.inverted()
        
        # If twist is closer to 180 degrees (abs(y) > abs(w)), preserve the flip
        if abs(q_twist.y) > abs(q_twist.w):
            q180 = mathutils.Quaternion((0.0, 0.0, 1.0, 0.0))
            q_twist_rel = q_twist @ q180.inverted()
            if q_twist_rel.w < 0:
                q_twist_rel = -q_twist_rel
            q_twist_rel_damped = mathutils.Quaternion((1.0, 0.0, 0.0, 0.0)).slerp(q_twist_rel, twist_scale)
            q_twist_final = q_twist_rel_damped @ q180
        else:
            q_twist_final = mathutils.Quaternion((1.0, 0.0, 0.0, 0.0)).slerp(q_twist, twist_scale)
            
        return q_swing @ q_twist_final

    # Helper function to dynamically measure character torso/belly radius from meshes
    def measure_torso_radius(target_arm):
        hips_bone = target_arm.data.bones.get("mixamorig:Hips")
        neck_bone = target_arm.data.bones.get("mixamorig:Neck")
        if hips_bone and neck_bone:
            z_hips = (target_arm.matrix_world @ hips_bone.head).z
            z_neck = (target_arm.matrix_world @ neck_bone.head).z
        else:
            z_hips = 0.2
            z_neck = 0.8
            
        torso_vertices_r = []
        for obj in bpy.data.objects:
            if obj.type == 'MESH':
                matrix = obj.matrix_world
                for v in obj.data.vertices:
                    v_world = matrix @ v.co
                    if z_hips <= v_world.z <= z_neck:
                        r = (v_world.x**2 + v_world.y**2)**0.5
                        torso_vertices_r.append(r)
                        
        torso_radius = max(torso_vertices_r) if torso_vertices_r else 0.30
        # Safe bounds to prevent unreasonable values from stray vertices
        torso_radius = min(0.45, max(0.20, torso_radius))
        print(f"Dynamically measured Torso Radius: {torso_radius:.4f} meters.")
        return torso_radius

    # Helper function to dynamically scale arm spread offset to avoid body collision
    def get_dynamic_arm_spread(target_arm, side, M_parent_pose, L_rest_arm, rot_arm_orig, L_rest_forearm, rot_forearm, L_rest_hand, rot_hand, torso_radius, clearance, base_spread):
        arm_bone_name = f"mixamorig:{side}Arm"
        forearm_bone_name = f"mixamorig:{side}ForeArm"
        
        arm_len = target_arm.data.bones[arm_bone_name].length
        forearm_len = target_arm.data.bones[forearm_bone_name].length
        total_len = arm_len + forearm_len if (arm_len + forearm_len) > 0.05 else 0.25
        
        # Test hand position under base spread
        offset = base_spread if side == 'Left' else -base_spread
        rot_spread = mathutils.Quaternion((0.0, 0.0, 1.0), offset)
        rot_arm_test = rot_arm_orig @ rot_spread
        
        M_arm = M_parent_pose @ L_rest_arm @ rot_arm_test.to_matrix().to_4x4()
        M_forearm = M_arm @ L_rest_forearm @ rot_forearm.to_matrix().to_4x4()
        M_hand = M_forearm @ L_rest_hand @ rot_hand.to_matrix().to_4x4()
        
        P_hand = M_hand.to_translation()
        r_hand = (P_hand.x**2 + P_hand.y**2)**0.5
        
        if r_hand < torso_radius + clearance:
            extra_spread = (torso_radius + clearance) - r_hand
            angle_adj = extra_spread / total_len
            # Cap maximum spread to 65 degrees (1.13 rad) to avoid T-posing
            spread_angle = base_spread + min(1.13 - base_spread, max(0.0, angle_adj))
        else:
            spread_angle = base_spread
            
        return spread_angle

    # Measure target torso/belly radius
    torso_radius = measure_torso_radius(target_arm)
    clearance = 0.03 # 3cm clearance from the torso boundary

    # Perform mathematical world space relative retargeting frame-by-frame
    print("Retargeting frames...")
    bpy.context.view_layer.objects.active = target_arm
    bpy.ops.object.mode_set(mode='POSE')

    # Chibi tuning parameters
    BOB_SCALE = 0.45          # Scale down vertical hips bobbing
    LEG_SWING_SCALE = 0.40    # Scale down thigh swing (smaller steps)
    SHIN_SWING_SCALE = 0.40   # Scale down shin swing
    FOOT_SWING_SCALE = 0.40   # Scale down foot/ankle swing
    TOE_SWING_SCALE = 0.40    # Scale down toe bending
    ARM_SPREAD_OFFSET = 0.45  # Radians (~25 degrees) base spread to clear larger head
    ARM_SWING_SCALE = 0.3     # Soften arm swing to prevent clipping into body/guts
    FOREARM_SWING_SCALE = 0.4 # Soften forearm elbow bend
    HAND_SWING_SCALE = 0.5    # Soften hand rotation
    FINGER_SWING_SCALE = 0.5  # Soften finger rotation to keep them relaxed

    # Helper to sort bones by depth in hierarchy so parents are processed before their children
    def get_bone_depth(bone):
        depth = 0
        while bone.parent:
            depth += 1
            bone = bone.parent
        return depth

    sorted_pose_bones = sorted(target_arm.pose.bones, key=lambda b: get_bone_depth(target_arm.data.bones[b.name]))

    for frame in range(start_frame, end_frame + 1):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        
        # Pass 1: Compute relative rotations for all bones (independent of parent pose)
        frame_rotations = {}
        for tgt_pbone in sorted_pose_bones:
            bone_name = tgt_pbone.name
            if bone_name in source_arm.pose.bones:
                src_pbone = source_arm.pose.bones[bone_name]
                
                # Get world matrices
                M_src_pose = source_arm.matrix_world @ src_pbone.matrix
                M_src_rest = source_arm.matrix_world @ source_arm.data.bones[bone_name].matrix_local
                M_tgt_rest = target_arm.matrix_world @ target_arm.data.bones[bone_name].matrix_local
                
                # Calculate relative transformation relative to target rest
                L_diff = M_tgt_rest.inverted() @ M_src_pose @ M_src_rest.inverted() @ M_tgt_rest
                loc, rot, scale = L_diff.decompose()
                
                # Damp twist (eliminate dynamic twist along Y axis, preserving roll flip)
                if bone_name in [
                    "mixamorig:LeftArm", "mixamorig:RightArm",
                    "mixamorig:LeftForeArm", "mixamorig:RightForeArm",
                    "mixamorig:LeftHand", "mixamorig:RightHand"
                ] or any(word in bone_name.lower() for word in ["index", "thumb", "middle", "ring", "pinky"]):
                    rot = damp_dynamic_twist_y(rot, twist_scale=0.0)
                    
                # Apply swing softening scaling
                if bone_name in ["mixamorig:LeftUpLeg", "mixamorig:RightUpLeg"]:
                    rot = rot.slerp(mathutils.Quaternion((1.0, 0.0, 0.0, 0.0)), 1.0 - LEG_SWING_SCALE)
                elif bone_name in ["mixamorig:LeftLeg", "mixamorig:RightLeg"]:
                    rot = rot.slerp(mathutils.Quaternion((1.0, 0.0, 0.0, 0.0)), 1.0 - SHIN_SWING_SCALE)
                elif bone_name in ["mixamorig:LeftFoot", "mixamorig:RightFoot"]:
                    rot = rot.slerp(mathutils.Quaternion((1.0, 0.0, 0.0, 0.0)), 1.0 - FOOT_SWING_SCALE)
                elif bone_name in ["mixamorig:LeftToeBase", "mixamorig:RightToeBase"]:
                    rot = rot.slerp(mathutils.Quaternion((1.0, 0.0, 0.0, 0.0)), 1.0 - TOE_SWING_SCALE)
                elif bone_name in ["mixamorig:LeftArm", "mixamorig:RightArm"]:
                    rot = rot.slerp(mathutils.Quaternion((1.0, 0.0, 0.0, 0.0)), 1.0 - ARM_SWING_SCALE)
                elif bone_name in ["mixamorig:LeftForeArm", "mixamorig:RightForeArm"]:
                    rot = rot.slerp(mathutils.Quaternion((1.0, 0.0, 0.0, 0.0)), 1.0 - FOREARM_SWING_SCALE)
                elif bone_name in ["mixamorig:LeftHand", "mixamorig:RightHand"]:
                    rot = rot.slerp(mathutils.Quaternion((1.0, 0.0, 0.0, 0.0)), 1.0 - HAND_SWING_SCALE)
                elif any(word in bone_name.lower() for word in ["index", "thumb", "middle", "ring", "pinky"]):
                    rot = rot.slerp(mathutils.Quaternion((1.0, 0.0, 0.0, 0.0)), 1.0 - FINGER_SWING_SCALE)
                    
                frame_rotations[bone_name] = rot
            else:
                frame_rotations[bone_name] = mathutils.Quaternion((1.0, 0.0, 0.0, 0.0))

        # Pass 2: Apply rotations and accumulate world pose matrices to resolve child dependencies
        tgt_pose_matrices = {}
        for tgt_pbone in sorted_pose_bones:
            bone_name = tgt_pbone.name
            
            if bone_name in source_arm.pose.bones:
                src_pbone = source_arm.pose.bones[bone_name]
                
                # Get world matrices
                M_src_pose = source_arm.matrix_world @ src_pbone.matrix
                M_src_rest = source_arm.matrix_world @ source_arm.data.bones[bone_name].matrix_local
                M_tgt_rest = target_arm.matrix_world @ target_arm.data.bones[bone_name].matrix_local
                
                M_tgt_pose = M_src_pose @ M_src_rest.inverted() @ M_tgt_rest
                
                # Relative translation and rest matrices
                if tgt_pbone.parent:
                    parent_name = tgt_pbone.parent.name
                    M_parent_pose = tgt_pose_matrices[parent_name]
                    M_parent_rest = target_arm.matrix_world @ target_arm.data.bones[parent_name].matrix_local
                    
                    L_pose = M_parent_pose.inverted() @ M_tgt_pose
                    L_rest = M_parent_rest.inverted() @ M_tgt_rest
                else:
                    L_pose = target_arm.matrix_world.inverted() @ M_tgt_pose
                    L_rest = target_arm.matrix_world.inverted() @ M_tgt_rest
                    
                L_diff = L_rest.inverted() @ L_pose
                loc, rot, scale = L_diff.decompose()
                
                # Use pre-computed, twist-damped and swing-scaled rotation
                rot = frame_rotations[bone_name]
                
                # Dynamic arm collision avoidance (Left and Right Arm bones)
                if bone_name in ["mixamorig:LeftArm", "mixamorig:RightArm"]:
                    side = "Left" if bone_name == "mixamorig:LeftArm" else "Right"
                    parent_name = tgt_pbone.parent.name
                    M_parent_pose = tgt_pose_matrices[parent_name]
                    
                    L_rest_arm = L_rest
                    
                    forearm_name = f"mixamorig:{side}ForeArm"
                    hand_name = f"mixamorig:{side}Hand"
                    
                    M_forearm_rest = target_arm.matrix_world @ target_arm.data.bones[forearm_name].matrix_local
                    M_hand_rest = target_arm.matrix_world @ target_arm.data.bones[hand_name].matrix_local
                    
                    L_rest_forearm = M_tgt_rest.inverted() @ M_forearm_rest
                    L_rest_hand = M_forearm_rest.inverted() @ M_hand_rest
                    
                    rot_forearm = frame_rotations.get(forearm_name, mathutils.Quaternion((1.0, 0.0, 0.0, 0.0)))
                    rot_hand = frame_rotations.get(hand_name, mathutils.Quaternion((1.0, 0.0, 0.0, 0.0)))
                    
                    spread_angle = get_dynamic_arm_spread(
                        target_arm, side, M_parent_pose, L_rest_arm, rot, 
                        L_rest_forearm, rot_forearm, L_rest_hand, rot_hand, 
                        torso_radius, clearance, base_spread=ARM_SPREAD_OFFSET
                    )
                    
                    offset = spread_angle if side == 'Left' else -spread_angle
                    rot_spread = mathutils.Quaternion((0.0, 0.0, 1.0), offset)
                    rot = rot @ rot_spread
                    
                # Set rotation quaternion
                tgt_pbone.rotation_quaternion = rot
                
                # Handle hips location bobbing (lock X and Y translations)
                if bone_name == "mixamorig:Hips":
                    src_hips = source_arm.pose.bones["mixamorig:Hips"]
                    V_src_pose = (source_arm.matrix_world @ src_hips.matrix).to_translation()
                    V_src_rest = (source_arm.matrix_world @ source_arm.data.bones["mixamorig:Hips"].matrix_local).to_translation()
                    disp = V_src_pose - V_src_rest
                    
                    tgt_pbone.location = mathutils.Vector((0.0, 0.0, disp.z * BOB_SCALE))
                else:
                    tgt_pbone.location = rest_locations[bone_name]
                    
                # Re-compute actual pose matrix in world space for child bones
                L_basis = mathutils.Matrix.Translation(tgt_pbone.location) @ rot.to_matrix().to_4x4()
                if tgt_pbone.parent:
                    tgt_pose_matrices[bone_name] = tgt_pose_matrices[tgt_pbone.parent.name] @ L_rest @ L_basis
                else:
                    tgt_pose_matrices[bone_name] = target_arm.matrix_world @ L_rest @ L_basis
            else:
                # If target bone is not in source armature, keep at rest
                M_tgt_rest = target_arm.matrix_world @ target_arm.data.bones[bone_name].matrix_local
                tgt_pose_matrices[bone_name] = M_tgt_rest
                tgt_pbone.rotation_quaternion = mathutils.Quaternion((1.0, 0.0, 0.0, 0.0))
                tgt_pbone.location = rest_locations[bone_name]
        
        # Keyframe everything
        for tgt_pbone in sorted_pose_bones:
            tgt_pbone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
            if tgt_pbone.name == "mixamorig:Hips":
                tgt_pbone.keyframe_insert(data_path="location", frame=frame)

    print("Retargeting complete.")

    # 4. Clean up source armature to prevent exporting it
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.data.objects.remove(source_arm, do_unlink=True)

    # 5. Export target mesh with baked animations to FBX
    print(f"Exporting final FBX: {output_fbx_path}")
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
 def retarget_walk_anim(mesh_glb: str, anim_fbx: str) -> bytes:
     import tempfile, os, subprocess
 
     trellis_outputs_vol.reload()
     
     target_path = f"/outputs/{mesh_glb}"
     source_path = f"/outputs/{anim_fbx}"
     output_path = f"/cache/walk_retargeted_{mesh_glb.replace('.glb', '.fbx')}"
     
     if not os.path.exists(target_path):
         raise FileNotFoundError(f"Target model {mesh_glb} not found on volume.")
     if not os.path.exists(source_path):
         raise FileNotFoundError(f"Source animation {anim_fbx} not found on volume.")
 
     print(f"Retargeting walk animation {anim_fbx} onto {mesh_glb}...")
     
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
     print("   Modal Chibi GLB walk.fbx Animation Retargeter  ")
     print("==================================================")
     
     glbs = [f for f in files if f.endswith(".glb")]
     fbxs = [f for f in files if f.endswith(".fbx")]
     
     if not glbs:
         print("No GLB files found on volume.")
         return
     if not fbxs:
         print("No FBX animation files found on volume.")
         return
         
     # 2. Select Rigged Character Mesh
     if char != -1 and 0 <= char < len(glbs):
         selected_char = glbs[char]
         print(f"Selected Character (from argument): {selected_char}")
     else:
         print("\nAvailable Rigged Chibi GLB Files:")
         for idx, f in enumerate(glbs):
             print(f"  [{idx}] {f}")
         target_idx = input("\nSelect the Rigged character GLB (enter number): ").strip()
         if not target_idx.isdigit() or not (0 <= int(target_idx) < len(glbs)):
             print("Invalid character selection.")
             return
         selected_char = glbs[int(target_idx)]
     
     # 3. Select Mixamo Animation File
     if anim != -1 and 0 <= anim < len(fbxs):
         selected_anim = fbxs[anim]
         print(f"Selected Animation (from argument): {selected_anim}")
     else:
         print("\nAvailable FBX Animation Files:")
         for idx, f in enumerate(fbxs):
             print(f"  [{idx}] {f}")
         anim_idx = input("\nSelect the animation FBX (enter number): ").strip()
         if not anim_idx.isdigit() or not (0 <= int(anim_idx) < len(fbxs)):
             print("Invalid animation selection.")
             return
         selected_anim = fbxs[int(anim_idx)]
     
     print(f"\nRetargeting {selected_anim} onto {selected_char}...")
     
     try:
         with modal.enable_output():
             animated_bytes = retarget_walk_anim.remote(selected_char, selected_anim)
             
         dl_dir = os.path.expanduser("~/Downloads")
         os.makedirs(dl_dir, exist_ok=True)
         
         model_id = os.path.splitext(selected_char)[0]
         output_name = f"{model_id}_walk_retargeted.fbx"
         output_path = os.path.join(dl_dir, output_name)
         
         with open(output_path, "wb") as f:
             f.write(animated_bytes)
             
         print(f"\n[+] SUCCESS! Retargeted FBX saved to: {output_path} ({len(animated_bytes):,} bytes)")
         print("==================================================")
         
     except Exception as e:
         print(f"\n[-] Animation retargeting failed: {e}")
 
 if __name__ == "__main__":
     main()
