import os
import sys
import subprocess
import modal

app = modal.App("universal-chibi-idle-animator")

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
import bpy, sys, os, addon_utils, mathutils

try:
    target_mesh_path = sys.argv[-3]
    source_anim_path = sys.argv[-2]
    output_fbx_path  = sys.argv[-1]

    addon_utils.enable("io_scene_gltf2", default_set=True)
    addon_utils.enable("io_scene_fbx",   default_set=True)

    # Clear scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # 1. Import target rigged FBX model
    print(f"Importing target model: {target_mesh_path}")
    bpy.ops.import_scene.fbx(filepath=target_mesh_path)
    
    # Identify target armature
    target_armatures = [obj for obj in bpy.data.objects if obj.type == 'ARMATURE']
    if not target_armatures:
        raise RuntimeError("No armature found in target model.")
    target_arm = target_armatures[0]
    target_arm.name = "TargetArmature"
    num_bones = len(target_arm.data.bones)
    print(f"Target armature loaded with {num_bones} bones.")

    # Helper to check for finger bones
    def is_finger_bone(name):
        keywords = ["index", "thumb", "middle", "ring", "pinky", "finger"]
        return any(k in name.lower() for k in keywords)

    # 2. Rename bones to corrected Mixamo naming structure if they aren't already renamed
    has_mixamo = any("mixamorig" in b.name.lower() for b in target_arm.data.bones)
    if not has_mixamo:
        print("Bones do not have Mixamo naming. Applying conversion mapping...")
        
        def generate_mixamo_mapping(target_arm):
            bones = target_arm.data.bones
            mapping = {}
            
            # Identify Center, Left, and Right bones
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
                    
            # Sort Center bones by Z coordinate (bottom to top)
            center_bones = sorted(center_bones, key=lambda b: b.head_local.z)
            
            # Filter out root/ground locator bone at the origin
            if len(center_bones) > 1:
                first = center_bones[0]
                second = center_bones[1]
                if not first.parent and len(first.children) == 1 and first.children[0] == second:
                    center_bones.pop(0)
                    
            if not center_bones:
                return {}
                
            hips_bone = center_bones[0]
            mapping[hips_bone.name] = "mixamorig:Hips"
            
            # The remaining center bones sorted by Z: Spine, Spine1, Spine2, Neck, Head
            head_bone = center_bones[-1]
            mapping[head_bone.name] = "mixamorig:Head"
            
            neck_bone = head_bone.parent
            if neck_bone and neck_bone in center_bones:
                mapping[neck_bone.name] = "mixamorig:Neck"
            else:
                neck_bone = center_bones[-2] if len(center_bones) > 2 else None
                if neck_bone:
                    mapping[neck_bone.name] = "mixamorig:Neck"
                    
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
                    
            # Identify legs (below hips Z)
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
                
            # Identify arms and fingers
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
                    for extra in left_arm_chain[4:]:
                        mapping[extra.name] = "mixamorig:LeftHand"
                elif len(left_arm_chain) == 3:
                    mapping[left_arm_chain[0].name] = "mixamorig:LeftArm"
                    mapping[left_arm_chain[1].name] = "mixamorig:LeftForeArm"
                    mapping[left_arm_chain[2].name] = "mixamorig:LeftHand"
                elif len(left_arm_chain) == 2:
                    mapping[left_arm_chain[0].name] = "mixamorig:LeftArm"
                    mapping[left_arm_chain[1].name] = "mixamorig:LeftHand"
                    
                left_hand_bone = left_arm_chain[3] if len(left_arm_chain) >= 4 else (left_arm_chain[2] if len(left_arm_chain) == 3 else left_arm_chain[-1])
                
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
                    for extra in right_arm_chain[4:]:
                        mapping[extra.name] = "mixamorig:RightHand"
                elif len(right_arm_chain) == 3:
                    mapping[right_arm_chain[0].name] = "mixamorig:RightArm"
                    mapping[right_arm_chain[1].name] = "mixamorig:RightForeArm"
                    mapping[right_arm_chain[2].name] = "mixamorig:RightHand"
                elif len(right_arm_chain) == 2:
                    mapping[right_arm_chain[0].name] = "mixamorig:RightArm"
                    mapping[right_arm_chain[1].name] = "mixamorig:RightHand"
                    
                right_hand_bone = right_arm_chain[3] if len(right_arm_chain) >= 4 else (right_arm_chain[2] if len(right_arm_chain) == 3 else right_arm_chain[-1])
                map_descendants(right_hand_bone, "mixamorig:Right")
                
            return mapping
            
        mapping = generate_mixamo_mapping(target_arm)
        print("Generated smart bone mapping:", mapping)
        
        # Rename target bones
        for old_name, new_name in mapping.items():
            if old_name in target_arm.data.bones:
                target_arm.data.bones[old_name].name = new_name

    # Remove Icosphere from the model
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

    # Set rotation mode to Quaternion for math
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

    # Helper function to dynamically measure character torso and head radius from meshes
    def measure_mesh_radii(target_arm):
        hips_bone = target_arm.data.bones.get("mixamorig:Hips")
        neck_bone = target_arm.data.bones.get("mixamorig:Neck")
        
        z_hips = (target_arm.matrix_world @ hips_bone.head).z if hips_bone else 0.2
        z_neck = (target_arm.matrix_world @ neck_bone.head).z if neck_bone else 0.8
        
        torso_r_list = []
        head_r_list = []
        
        for obj in bpy.data.objects:
            if obj.type == 'MESH':
                matrix = obj.matrix_world
                for v in obj.data.vertices:
                    v_world = matrix @ v.co
                    r = (v_world.x**2 + v_world.y**2)**0.5
                    if z_hips <= v_world.z <= z_neck:
                        torso_r_list.append(r)
                    elif v_world.z > z_neck:
                        head_r_list.append(r)
                        
        torso_radius = max(torso_r_list) if torso_r_list else 0.30
        head_radius = max(head_r_list) if head_r_list else 0.45
        
        # Safe bounds to prevent unreasonable values from stray vertices
        torso_radius = min(0.45, max(0.20, torso_radius))
        head_radius = min(0.60, max(0.25, head_radius))
        
        print(f"Torso Radius: {torso_radius:.4f}m, Head Radius: {head_radius:.4f}m")
        return torso_radius, head_radius

    # Helper function to dynamically scale arm spread offset to avoid torso and head collision
    def get_dynamic_arm_spread(target_arm, side, M_parent_pose, L_rest_arm, rot_arm_orig, L_rest_forearm, rot_forearm, L_rest_hand, rot_hand, torso_radius, head_radius, z_neck, clearance, base_spread):
        arm_bone_name = f"mixamorig:{side}Arm"
        forearm_bone_name = f"mixamorig:{side}ForeArm"
        
        arm_len = target_arm.data.bones[arm_bone_name].length
        forearm_len = target_arm.data.bones[forearm_bone_name].length
        total_len = arm_len + forearm_len if (arm_len + forearm_len) > 0.05 else 0.25
        
        # Test hand and elbow position under base spread (local X rotation is the true spread axis)
        rot_spread = mathutils.Quaternion((1.0, 0.0, 0.0), base_spread)
        rot_arm_test = rot_arm_orig @ rot_spread
        
        M_arm = M_parent_pose @ L_rest_arm @ rot_arm_test.to_matrix().to_4x4()
        M_forearm = M_arm @ L_rest_forearm @ rot_forearm.to_matrix().to_4x4()
        M_hand = M_forearm @ L_rest_hand @ rot_hand.to_matrix().to_4x4()
        
        P_elbow = M_forearm.to_translation()
        P_hand = M_hand.to_translation()
        
        # Hand distance from center
        r_hand = (P_hand.x**2 + P_hand.y**2)**0.5
        # Elbow distance from center
        r_elbow = (P_elbow.x**2 + P_elbow.y**2)**0.5
        
        # Decide target radius based on Z heights
        t_rad_hand = head_radius if P_hand.z >= z_neck else torso_radius
        t_rad_elbow = head_radius if P_elbow.z >= z_neck else torso_radius
        
        # Calculate extra spread needed
        extra_hand = (t_rad_hand + clearance) - r_hand
        extra_elbow = (t_rad_elbow + clearance) - r_elbow
        
        max_extra = max(0.0, extra_hand, extra_elbow)
        
        if max_extra > 0.0:
            angle_adj = max_extra / total_len
            # Cap maximum spread to 75 degrees (1.31 rad) to handle very large heads
            spread_angle = base_spread + min(1.31 - base_spread, max(0.0, angle_adj))
        else:
            spread_angle = base_spread
            
        return spread_angle

    # Measure target torso/belly and head radius
    torso_radius, head_radius = measure_mesh_radii(target_arm)
    clearance = 0.01 # 1cm safety clearance (arms touch/barely touch body)
    
    # Store neck height
    neck_bone = target_arm.data.bones.get("mixamorig:Neck")
    z_neck = (target_arm.matrix_world @ neck_bone.head).z if neck_bone else 0.8

    # Perform mathematical world space relative retargeting frame-by-frame
    print("Retargeting frames...")
    bpy.context.view_layer.objects.active = target_arm
    bpy.ops.object.mode_set(mode='POSE')

    # Dynamic scale detection based on leg proportions
    src_hips = source_arm.data.bones.get("mixamorig:Hips")
    src_foot = source_arm.data.bones.get("mixamorig:LeftFoot")
    src_leg_len_raw = 0.85
    if src_hips and src_foot:
        src_leg_len_raw = (src_hips.head_local - src_foot.head_local).length
        
    src_leg_len = src_leg_len_raw
    if src_leg_len > 10.0:
        src_leg_len = src_leg_len / 100.0  # Normalize to meters
        
    tgt_hips = target_arm.data.bones.get("mixamorig:Hips")
    tgt_foot = target_arm.data.bones.get("mixamorig:LeftFoot")
    tgt_leg_len = 0.30
    if tgt_hips and tgt_foot:
        tgt_leg_len = (tgt_hips.head_local - tgt_foot.head_local).length
        
    leg_scale = tgt_leg_len / src_leg_len
    # No leg amplification for idle (keep it 1.0)
    leg_amplification = 1.0
    
    BOB_SCALE = 1.0
    SWAY_SCALE = 1.0
    
    print(f"Dynamic Scale: Target Leg={tgt_leg_len:.4f}m, Source Leg Raw={src_leg_len_raw:.4f}m, Normalized={src_leg_len:.4f}m, Leg Scale={leg_scale:.4f}")
    print(f"Applying Amplification: {leg_amplification:.4f}x")

    ARM_SPREAD_OFFSET = 0.0  # Radians base spread for idle close arms
    ARM_SWING_SCALE = 0.70    # Natural idle breathing arm swing
    FOREARM_SWING_SCALE = 0.70 # Natural forearm bend
    HAND_SWING_SCALE = 0.70   # Natural hand follow-through

    # Helper to sort bones by depth in hierarchy so parents are processed before their children
    def get_bone_depth(bone):
        depth = 0
        while bone.parent:
            depth += 1
            bone = bone.parent
        return depth

    sorted_pose_bones = sorted(target_arm.pose.bones, key=lambda b: get_bone_depth(target_arm.data.bones[b.name]))

    # Hand rotation offsets to untwist hands and fingers (in radians)
    # Pitch (X), Roll/Twist (Y), Yaw (Z)
    L_HAND_OFFSET = mathutils.Euler((0.0, -0.6, 0.4))  # Untwist Left Hand
    R_HAND_OFFSET = mathutils.Euler((0.0, 0.6, -0.4))   # Untwist Right Hand

    # 4. Rest Local parents configuration for dynamic spread
    p_left_arm = target_arm.pose.bones.get("mixamorig:LeftArm")
    p_left_forearm = target_arm.pose.bones.get("mixamorig:LeftForeArm")
    p_left_hand = target_arm.pose.bones.get("mixamorig:LeftHand")
    
    L_rest_left_arm = mathutils.Matrix.Identity(4)
    L_rest_left_forearm = mathutils.Matrix.Identity(4)
    L_rest_left_hand = mathutils.Matrix.Identity(4)
    
    if p_left_arm:
        b_left_arm = target_arm.data.bones.get("mixamorig:LeftArm")
        b_left_forearm = target_arm.data.bones.get("mixamorig:LeftForeArm")
        b_left_hand = target_arm.data.bones.get("mixamorig:LeftHand")
        L_rest_left_arm = b_left_arm.parent.matrix_local.inverted() @ b_left_arm.matrix_local if (b_left_arm and b_left_arm.parent) else b_left_arm.matrix_local
        L_rest_left_forearm = b_left_arm.matrix_local.inverted() @ b_left_forearm.matrix_local
        L_rest_left_hand = b_left_forearm.matrix_local.inverted() @ b_left_hand.matrix_local

    p_right_arm = target_arm.pose.bones.get("mixamorig:RightArm")
    p_right_forearm = target_arm.pose.bones.get("mixamorig:RightForeArm")
    p_right_hand = target_arm.pose.bones.get("mixamorig:RightHand")
    
    L_rest_right_arm = mathutils.Matrix.Identity(4)
    L_rest_right_forearm = mathutils.Matrix.Identity(4)
    L_rest_right_hand = mathutils.Matrix.Identity(4)
    
    if p_right_arm:
        b_right_arm = target_arm.data.bones.get("mixamorig:RightArm")
        b_right_forearm = target_arm.data.bones.get("mixamorig:RightForeArm")
        b_right_hand = target_arm.data.bones.get("mixamorig:RightHand")
        L_rest_right_arm = b_right_arm.parent.matrix_local.inverted() @ b_right_arm.matrix_local if (b_right_arm and b_right_arm.parent) else b_right_arm.matrix_local
        L_rest_right_forearm = b_right_arm.matrix_local.inverted() @ b_right_forearm.matrix_local
        L_rest_right_hand = b_right_forearm.matrix_local.inverted() @ b_right_hand.matrix_local

    for frame in range(start_frame, end_frame + 1):
        # Set frame
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        
        # Pass 1: Apply world orientation matrices in hierarchy-safe order
        for tgt_pbone in sorted_pose_bones:
            bone_name = tgt_pbone.name
            
            # Exclude finger bones completely from the retargeting copy pass
            if is_finger_bone(bone_name):
                continue
                
            if bone_name in source_arm.pose.bones:
                src_pbone = source_arm.pose.bones[bone_name]
                
                # Get world matrices
                M_src_rest = source_arm.matrix_world @ source_arm.data.bones[bone_name].matrix_local
                M_tgt_rest = target_arm.matrix_world @ target_arm.data.bones[bone_name].matrix_local
                M_src_pose = source_arm.matrix_world @ src_pbone.matrix
                
                # Relative matrix formula
                M_tgt_pose = M_src_pose @ M_src_rest.inverted() @ M_tgt_rest
                
                # Apply pose matrix
                tgt_pbone.matrix = target_arm.matrix_world.inverted() @ M_tgt_pose
                
                # CRITICAL: Update Blender's view layer after setting EACH bone.
                bpy.context.view_layer.update()
                
        # Pass 2: Lock bone locations and apply chibi rotation & hand untwisting offsets
        for tgt_pbone in target_arm.pose.bones:
            bone_name = tgt_pbone.name
            
            # Lock position to rest pose to prevent stretching (applied to all non-Hips bones first)
            if bone_name != "mixamorig:Hips":
                tgt_pbone.location = rest_locations[bone_name]
            
            # Exclude fingers - lock at relaxed/identity rotation
            if is_finger_bone(bone_name):
                tgt_pbone.rotation_quaternion = mathutils.Quaternion((1.0, 0.0, 0.0, 0.0))
                continue
            
            # Lock shoulders to rest pose rotation (identity) to keep arm base wide and stable
            if bone_name in ["mixamorig:LeftShoulder", "mixamorig:RightShoulder"]:
                tgt_pbone.rotation_quaternion = mathutils.Quaternion((1.0, 0.0, 0.0, 0.0))
                continue
            
            # Get current rotation to adjust
            rot = tgt_pbone.rotation_quaternion.copy()
            
            # Damp dynamic twist
            if bone_name in [
                "mixamorig:LeftArm", "mixamorig:RightArm",
                "mixamorig:LeftForeArm", "mixamorig:RightForeArm",
                "mixamorig:LeftHand", "mixamorig:RightHand"
            ]:
                rot = damp_dynamic_twist_y(rot, twist_scale=0.0)
            
            # Apply scaling
            if bone_name in ["mixamorig:LeftUpLeg", "mixamorig:RightUpLeg"]:
                # Keep original thigh swing for idle
                euler = rot.to_euler('XYZ')
                euler.x *= leg_amplification
                euler.z *= leg_amplification
                rot = euler.to_quaternion()
            elif bone_name in ["mixamorig:LeftLeg", "mixamorig:RightLeg", "mixamorig:LeftFoot", "mixamorig:RightFoot", "mixamorig:LeftToeBase", "mixamorig:RightToeBase"]:
                # Keep original leg/knee/foot bends
                euler = rot.to_euler('XYZ')
                euler.x *= leg_amplification
                rot = euler.to_quaternion()
            elif bone_name == "mixamorig:Hips":
                # Keep original hips rotation for idle
                pass
            elif bone_name == "mixamorig:LeftArm":
                # Override LeftArm rotation to point down and remain still
                rot = mathutils.Euler((-1.4, 0.0, 0.0), 'XYZ').to_quaternion()
            elif bone_name == "mixamorig:RightArm":
                # Override RightArm rotation to point down and remain still
                rot = mathutils.Euler((-1.4, 0.0, 0.0), 'XYZ').to_quaternion()
            elif bone_name == "mixamorig:LeftForeArm":
                # Slight elbow bend for relaxed stance
                rot = mathutils.Euler((0.15, 0.0, 0.0), 'XYZ').to_quaternion()
            elif bone_name == "mixamorig:RightForeArm":
                # Slight elbow bend for relaxed stance
                rot = mathutils.Euler((0.15, 0.0, 0.0), 'XYZ').to_quaternion()
            elif bone_name in ["mixamorig:LeftHand", "mixamorig:RightHand"]:
                # Relaxed straight hand
                rot = mathutils.Quaternion((1.0, 0.0, 0.0, 0.0))
                
            tgt_pbone.rotation_quaternion = rot
        
        # Update Blender view layer after Pass 2 so Pass 3 queries fresh bone matrices
        bpy.context.view_layer.update()

        # Pass 3: Dynamically calculate and apply arm spread offsets for collision avoidance
        if p_left_arm and p_left_forearm and p_left_hand:
            M_left_parent = p_left_arm.parent.matrix if p_left_arm.parent else mathutils.Matrix.Identity(4)
            spread_left = get_dynamic_arm_spread(
                target_arm, 'Left', M_left_parent, 
                L_rest_left_arm, p_left_arm.rotation_quaternion.copy(),
                L_rest_left_forearm, p_left_forearm.rotation_quaternion.copy(),
                L_rest_left_hand, p_left_hand.rotation_quaternion.copy(),
                torso_radius, head_radius, z_neck, clearance, ARM_SPREAD_OFFSET
            )
            # Apply spread rotation in quaternion space directly to local X axis
            rot_spread = mathutils.Quaternion((1.0, 0.0, 0.0), spread_left)
            p_left_arm.rotation_quaternion = p_left_arm.rotation_quaternion @ rot_spread
            
        if p_right_arm and p_right_forearm and p_right_hand:
            M_right_parent = p_right_arm.parent.matrix if p_right_arm.parent else mathutils.Matrix.Identity(4)
            spread_right = get_dynamic_arm_spread(
                target_arm, 'Right', M_right_parent, 
                L_rest_right_arm, p_right_arm.rotation_quaternion.copy(),
                L_rest_right_forearm, p_right_forearm.rotation_quaternion.copy(),
                L_rest_right_hand, p_right_hand.rotation_quaternion.copy(),
                torso_radius, head_radius, z_neck, clearance, ARM_SPREAD_OFFSET
            )
            # Apply spread rotation in quaternion space directly to local X axis
            rot_spread = mathutils.Quaternion((1.0, 0.0, 0.0), spread_right)
            p_right_arm.rotation_quaternion = p_right_arm.rotation_quaternion @ rot_spread

        bpy.context.view_layer.update()
        
        # Pass 4: Handle Hips vertical bobbing and sway translation
        p_hips = target_arm.pose.bones.get("mixamorig:Hips")
        src_hips = source_arm.pose.bones.get("mixamorig:Hips")
        if p_hips and src_hips:
            V_src_pose = (source_arm.matrix_world @ src_hips.matrix).to_translation()
            V_src_rest = (source_arm.matrix_world @ source_arm.data.bones["mixamorig:Hips"].matrix_local).to_translation()
            disp = V_src_pose - V_src_rest
            
            # Normalize displacement to meters if source armature is in cm
            if src_leg_len_raw > 10.0:
                disp = disp / 100.0
                
            p_hips.location.x = tgt_hips_rest_loc.x + (disp.x * leg_scale)
            p_hips.location.y = tgt_hips_rest_loc.y + (disp.y * leg_scale)
            p_hips.location.z = tgt_hips_rest_loc.z + (disp.z * leg_scale)
        
        # Pass 5: Add look left & right look-around overlay animation (loopable, smooth)
        p_neck = target_arm.pose.bones.get("mixamorig:Neck")
        p_head = target_arm.pose.bones.get("mixamorig:Head")
        if p_neck or p_head:
            idx = frame - start_frame + 1
            
            # Idle sequence:
            # 1-50: Straight (0.0)
            # 50-90: Look Left
            # 90-130: Hold Left
            # 130-170: Look Straight
            # 170-210: Look Right
            # 210-250: Hold Right
            # 250-290: Look Straight
            # 290-301: Look Straight
            
            yaw = 0.0
            pitch = 0.0
            roll = 0.0
            
            max_yaw = 0.50   # ~29 degrees
            tilt_roll = 0.08 # cute tilt
            
            if 50 <= idx < 90:
                t = (idx - 50) / 40.0
                t = t * t * (3 - 2 * t)
                yaw = t * max_yaw
                roll = t * -tilt_roll
            elif 90 <= idx < 130:
                yaw = max_yaw
                roll = -tilt_roll
            elif 130 <= idx < 170:
                t = (idx - 130) / 40.0
                t = t * t * (3 - 2 * t)
                yaw = (1.0 - t) * max_yaw
                roll = (1.0 - t) * -tilt_roll
            elif 170 <= idx < 210:
                t = (idx - 170) / 40.0
                t = t * t * (3 - 2 * t)
                yaw = t * -max_yaw
                roll = t * tilt_roll
            elif 210 <= idx < 250:
                yaw = -max_yaw
                roll = tilt_roll
            elif 250 <= idx < 290:
                t = (idx - 250) / 40.0
                t = t * t * (3 - 2 * t)
                yaw = (1.0 - t) * -max_yaw
                roll = (1.0 - t) * tilt_roll
                
            if p_neck:
                rot_neck_add = mathutils.Euler((pitch * 0.35, yaw * 0.35, roll * 0.35), 'YXZ').to_quaternion()
                p_neck.rotation_quaternion = p_neck.rotation_quaternion @ rot_neck_add
            if p_head:
                rot_head_add = mathutils.Euler((pitch * 0.65, yaw * 0.65, roll * 0.65), 'YXZ').to_quaternion()
                p_head.rotation_quaternion = p_head.rotation_quaternion @ rot_head_add

        # Keyframe everything
        for tgt_pbone in target_arm.pose.bones:
            tgt_pbone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
            if tgt_pbone.name == "mixamorig:Hips":
                tgt_pbone.keyframe_insert(data_path="location", frame=frame)

    print("Retargeting complete.")

    # 3.5. Apply F-Curve smoothing filter to remove high-frequency jitter
    print("Smoothing animation F-Curves...")
    def smooth_fcurves(armature, window_size_default=3, window_size_arms=9):
        if not armature.animation_data or not armature.animation_data.action:
            return
        action = armature.animation_data.action
        for fcurve in action.fcurves:
            if "scale" in fcurve.data_path:
                continue
                
            # Use window size 9 for arms/hands to filter out jitter, and 3 for legs/hips
            w_size = window_size_default
            if any(name in fcurve.data_path for name in ["Arm", "ForeArm", "Hand"]):
                w_size = window_size_arms
                
            kp = fcurve.keyframe_points
            n = len(kp)
            if n <= w_size:
                continue
            
            smoothed_values = []
            half_w = w_size // 2
            for i in range(n):
                # Periodic wrap-around for loop continuity
                vals = []
                for offset in range(-half_w, half_w + 1):
                    idx = (i + offset) % n
                    vals.append(kp[idx].co[1])
                smoothed_values.append(sum(vals) / len(vals))
                
            for i in range(n):
                kp[i].co[1] = smoothed_values[i]
                kp[i].handle_left[1] = smoothed_values[i]
                kp[i].handle_right[1] = smoothed_values[i]
                
            # Explicitly match the last frame to the first frame for a perfect loop
            kp[-1].co[1] = kp[0].co[1]
            kp[-1].handle_left[1] = kp[0].handle_left[1]
            kp[-1].handle_right[1] = kp[0].handle_right[1]
                
    smooth_fcurves(target_arm, window_size_default=3, window_size_arms=9)
    print("Animation smoothing complete.")

    # 4. Clean up source armature
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.data.objects.remove(source_arm, do_unlink=True)

    # 5. Export final target FBX
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
def retarget_idle_anim(mesh_fbx: str, anim_fbx: str) -> bytes:
    import tempfile, os, subprocess

    trellis_outputs_vol.reload()
    
    target_path = f"/outputs/{mesh_fbx}"
    source_path = f"/outputs/{anim_fbx}"
    
    # Save the output directly into /outputs/animation/
    output_dir = "/outputs/animation"
    os.makedirs(output_dir, exist_ok=True)
    model_id = os.path.splitext(mesh_fbx)[0]
    output_path = os.path.join(output_dir, f"{model_id}_idle.fbx")
    
    if not os.path.exists(target_path):
        raise FileNotFoundError(f"Target model {mesh_fbx} not found on volume.")
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source animation {anim_fbx} not found on volume.")

    print(f"Retargeting idle animation {anim_fbx} onto {mesh_fbx}...")
    
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
        
    trellis_outputs_vol.commit()
    return open(output_path, "rb").read()

@app.function(volumes={"/outputs": trellis_outputs_vol})
def list_volume_files():
    trellis_outputs_vol.reload()
    return sorted(os.listdir("/outputs"))

@app.function(volumes={"/outputs": trellis_outputs_vol})
def upload_file_to_volume(filename: str, file_bytes: bytes):
    import os
    with open(f"/outputs/{filename}", "wb") as f:
        f.write(file_bytes)
    trellis_outputs_vol.commit()
    print(f"[+] Uploaded {filename} to Modal volume successfully.")

@app.function(volumes={"/outputs": trellis_outputs_vol})
def delete_glb_files():
    import os
    trellis_outputs_vol.reload()
    deleted = []
    for f in os.listdir("/outputs"):
        if f.endswith(".glb"):
            try:
                os.remove(os.path.join("/outputs", f))
                deleted.append(f)
            except Exception:
                pass
    if deleted:
        trellis_outputs_vol.commit()
        print(f"[+] Deleted GLB files from volume: {deleted}")
    return deleted

@app.local_entrypoint()
def main(choice: str = None):
    print("==================================================")
    print("     Universal Chibi Idle Animation Generator     ")
    print("==================================================")
    
    # Try to connect to Modal volume
    try:
        files = list_volume_files.remote()
        use_modal = True
        print("[+] Connected to Modal server successfully.")
    except Exception as e:
        print(f"\n[!] Could not connect to Modal server: {e}")
        print("[!] Falling back to LOCAL mode using macOS Blender and local files...")
        use_modal = False
        
    downloads_dir = os.path.expanduser("~/Downloads")
    anim_filename = "idle.fbx"
    
    # Clean up local GLB files in Downloads folder on start
    print("[+] Cleaning up local GLB files in Downloads folder...")
    if os.path.exists(downloads_dir):
        for f in os.listdir(downloads_dir):
            if f.endswith(".glb"):
                try:
                    os.remove(os.path.join(downloads_dir, f))
                    print(f"[+] Deleted local GLB: {f}")
                except Exception:
                    pass
                    
    if use_modal:
        # Delete any GLB files on the volume
        print("[+] Checking and deleting GLB files on volume...")
        try:
            deleted_glbs = delete_glb_files.remote()
            if deleted_glbs:
                print(f"[+] Cleaned up GLB files: {deleted_glbs}")
        except Exception as e:
            print(f"[-] Warning: Failed to clean GLB files on volume: {e}")
            
        # Refresh volume file list
        files = list_volume_files.remote()
        
        # Scan for FBX files, excluding idle.fbx, walking.fbx, and output idle files
        fbxs = [f for f in files if f.endswith(".fbx") and f.lower() not in ["idle.fbx", "walking.fbx"] and not f.endswith("_idle.fbx") and not "/animation/" in f]
        
        if anim_filename not in files:
            print(f"[!] {anim_filename} not found on the trellis-outputs volume.", flush=True)
            # Try to find it locally
            local_anim_path = os.path.join(downloads_dir, "Characters", anim_filename)
            if not os.path.exists(local_anim_path):
                local_anim_path = os.path.join(downloads_dir, anim_filename)
                
            if os.path.exists(local_anim_path):
                print(f"[+] Found local {anim_filename} at {local_anim_path}. Uploading to Modal volume...", flush=True)
                with open(local_anim_path, "rb") as f:
                    file_bytes = f.read()
                upload_file_to_volume.remote(anim_filename, file_bytes)
                # Reload files list
                files = list_volume_files.remote()
                fbxs = [f for f in files if f.endswith(".fbx") and f.lower() not in ["idle.fbx", "walking.fbx"] and not f.endswith("_idle.fbx") and not "/animation/" in f]
            else:
                print(f"[-] Error: {anim_filename} not found locally in ~/Downloads/ or ~/Downloads/Characters/.")
                print("    Please download the animation and place it in ~/Downloads/ to auto-upload.")
                return
        if not fbxs:
            print("[-] No target FBX files found on the trellis-outputs volume.")
            return
    else:
        local_blender = "/Applications/Blender.app/Contents/MacOS/Blender"
        if not os.path.exists(local_blender):
            print(f"[-] Error: Local Blender not found at {local_blender}")
            print("    Please ensure Blender is installed at /Applications/Blender.app")
            return
            
        fbxs = [f for f in os.listdir(downloads_dir) if f.endswith(".fbx") and f.lower() not in ["idle.fbx", "walking.fbx"] and not f.endswith("_idle.fbx")]
        anim_path = os.path.join(downloads_dir, "Characters", anim_filename)
        if not os.path.exists(anim_path):
            anim_path = os.path.join(downloads_dir, anim_filename)
            
        if not os.path.exists(anim_path):
            print(f"[-] Error: {anim_filename} not found in ~/Downloads/Characters/ or ~/Downloads/")
            return
        if not fbxs:
            print(f"[-] No target FBX files found in local ~/Downloads/ folder.")
            return

    print(f"\nTarget Rigged FBX Models found: {len(fbxs)}")
    print("  [a] Process ALL models")
    for idx, f in enumerate(fbxs):
        print(f"  [{idx}] {f}")
        
    if choice is None:
        choice = input("\nSelect a model index to process, or 'a' for all: ").strip().lower()
    else:
        choice = choice.strip().lower()
        print(f"\nProcessing automatically using choice: {choice}")
    
    if choice == 'a':
        selected_fbxs = fbxs
        print("\n[+] Triggering retargeting for ALL models...")
    elif choice.isdigit() and 0 <= int(choice) < len(fbxs):
        selected_fbxs = [fbxs[int(choice)]]
        print(f"\n[+] Triggering retargeting for {selected_fbxs[0]}...")
    else:
        print("[-] Invalid selection.")
        return
        
    os.makedirs(downloads_dir, exist_ok=True)
    
    if use_modal:
        # Cloud run
        with modal.enable_output():
            for mesh_fbx in selected_fbxs:
                model_id = os.path.splitext(mesh_fbx)[0]
                output_name = f"{model_id}_idle.fbx"
                local_dest = os.path.join(downloads_dir, output_name)
                
                print(f"\n>>> Processing {mesh_fbx} -> {output_name}...")
                try:
                    animated_bytes = retarget_idle_anim.remote(mesh_fbx, anim_filename)
                    with open(local_dest, "wb") as f:
                        f.write(animated_bytes)
                    print(f"[+] Success! Downloaded to: {local_dest} ({len(animated_bytes):,} bytes)")
                except Exception as e:
                    print(f"[-] Failed to process {mesh_fbx}: {e}")
    else:
        # Local run using local Blender on Mac
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(BLENDER_RETARGET_SCRIPT)
            script_path = f.name
            
        try:
            for mesh_fbx in selected_fbxs:
                model_id = os.path.splitext(mesh_fbx)[0]
                output_name = f"{model_id}_idle.fbx"
                local_fbx_path = os.path.join(downloads_dir, mesh_fbx)
                local_dest = os.path.join(downloads_dir, output_name)
                
                print(f"\n>>> Local Processing {mesh_fbx} -> {output_name}...")
                try:
                    res = subprocess.run([
                        local_blender, "--background", "--python", script_path, "--",
                        local_fbx_path, anim_path, local_dest
                    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    print(res.stdout)
                    if res.returncode != 0:
                        raise RuntimeError(f"Blender exited with code {res.returncode}")
                    print(f"[+] Success! Saved local file to: {local_dest}")
                except Exception as e:
                    print(f"[-] Failed to process {mesh_fbx} locally: {e}")
        finally:
            os.remove(script_path)
                
    print("\n==================================================")
    print("   All universal chibi idle animations completed! ")
    print("==================================================")
