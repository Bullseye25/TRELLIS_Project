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

    # Helper to check for arm/shoulder/hand/finger bones to freeze them completely
    def is_arm_bone(name):
        return any(k in name for k in ["Shoulder", "Arm", "ForeArm", "Hand", "Finger"]) or is_finger_bone(name)

    # 2. Rename bones to corrected Mixamo naming structure if they aren't already renamed
    has_mixamo = any("mixamorig" in b.name.lower() for b in target_arm.data.bones)
    if not has_mixamo:
        print("Bones do not have Mixamo naming. Applying conversion mapping...")
        
        def generate_mixamo_mapping(target_arm):
            mapping = {}
            bones = target_arm.data.bones
            all_bones = [b for b in bones if not b.name.endswith("_end")]

            # Find root bone (no parent)
            roots = [b for b in all_bones if b.parent is None]
            if not roots:
                return {}
            root = roots[0]
            mapping[root.name] = "mixamorig:Hips"
            rx = root.head_local.x  # X reference for left/right detection

            # Walk the FULL center spine upward to the head.
            # At each step: pick the child most central to root-X that goes upward in Z.
            # This correctly skips leg branches (which go down) off the hips.
            full_spine = [root]
            cur = root
            while True:
                kids = [c for c in cur.children if not c.name.endswith("_end")]
                upward_center = [c for c in kids
                                 if c.head_local.z >= cur.head_local.z - 0.01
                                 and abs(c.head_local.x - rx) < 0.05]
                if not upward_center:
                    break
                next_bone = min(upward_center, key=lambda c: abs(c.head_local.x - rx))
                full_spine.append(next_bone)
                cur = next_bone

            # Label the spine chain: Head is always the last bone, Neck is its parent, and others are Spines
            if len(full_spine) >= 2:
                head_bone = full_spine[-1]
                neck_bone = full_spine[-2]
                mapping[head_bone.name] = "mixamorig:Head"
                mapping[neck_bone.name] = "mixamorig:Neck"
                
                # Label intermediate bones as Spine, Spine1, Spine2
                intermediate_spines = full_spine[1:-2]
                spine_labels = ["mixamorig:Spine", "mixamorig:Spine1", "mixamorig:Spine2"]
                for i, b in enumerate(intermediate_spines):
                    if i < len(spine_labels):
                        mapping[b.name] = spine_labels[i]
                    else:
                        mapping[b.name] = "mixamorig:Spine2"

            # Identify chest: first spine bone that has lateral arm branches (|x-rx| > 0.02)
            chest = full_spine[-1]
            for b in full_spine[1:]:
                arm_branches = [c for c in b.children
                                if not c.name.endswith("_end")
                                and abs(c.head_local.x - rx) > 0.02]
                if arm_branches:
                    chest = b
                    break

            # Helper: follow a linear chain of bones and assign labels
            def follow_chain(start, labels):
                chain = [start]
                cur2 = start
                while len(chain) < len(labels):
                    kids = [c for c in cur2.children
                            if not c.name.endswith("_end") and c.name not in mapping]
                    if not kids:
                        break
                    cur2 = min(kids, key=lambda c: len(c.children))
                    chain.append(cur2)
                for i, b in enumerate(chain):
                    if i < len(labels):
                        mapping[b.name] = labels[i]

            # Arms from chest (positive X = left, negative X = right)
            chest_kids = [c for c in chest.children
                          if not c.name.endswith("_end") and c.name not in mapping]
            left_sh  = sorted([c for c in chest_kids if c.head_local.x > rx + 0.01],
                              key=lambda c: -c.head_local.x)
            right_sh = sorted([c for c in chest_kids if c.head_local.x < rx - 0.01],
                              key=lambda c:  c.head_local.x)
            if left_sh:
                follow_chain(left_sh[0], ["mixamorig:LeftShoulder", "mixamorig:LeftArm",
                                           "mixamorig:LeftForeArm",  "mixamorig:LeftHand"])
            if right_sh:
                follow_chain(right_sh[0], ["mixamorig:RightShoulder", "mixamorig:RightArm",
                                            "mixamorig:RightForeArm",  "mixamorig:RightHand"])

            # Legs from root (positive X = left, negative X = right)
            hip_kids = [c for c in root.children
                        if not c.name.endswith("_end") and c.name not in mapping]
            left_leg  = sorted([c for c in hip_kids if c.head_local.x > rx + 0.01],
                               key=lambda c: -c.head_local.x)
            right_leg = sorted([c for c in hip_kids if c.head_local.x < rx - 0.01],
                               key=lambda c:  c.head_local.x)
            if left_leg:
                follow_chain(left_leg[0], ["mixamorig:LeftUpLeg", "mixamorig:LeftLeg",
                                            "mixamorig:LeftFoot",  "mixamorig:LeftToeBase"])
            if right_leg:
                follow_chain(right_leg[0], ["mixamorig:RightUpLeg", "mixamorig:RightLeg",
                                             "mixamorig:RightFoot",  "mixamorig:RightToeBase"])

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
    clearance = 0.15 # 15cm safety clearance (increased to prevent body meshing)
    
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

    ARM_SPREAD_OFFSET = 0.85  # Radians (~49 degrees) base spread to clear larger head
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
            
            # Exclude arm/hand/finger bones completely from the retargeting copy pass
            if is_arm_bone(bone_name):
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
            
            # Exclude arm/shoulder/hand/finger bones - lock completely at rest/identity rotation or custom arm pose
            if is_arm_bone(bone_name):
                if bone_name == "mixamorig:LeftArm":
                    tgt_pbone.rotation_quaternion = mathutils.Quaternion((20.0, -2.5, 10.0, -4.5)).normalized()
                elif bone_name == "mixamorig:RightArm":
                    tgt_pbone.rotation_quaternion = mathutils.Quaternion((20.0, -2.5, -10.0, 4.5)).normalized()
                else:
                    tgt_pbone.rotation_quaternion = mathutils.Quaternion((1.0, 0.0, 0.0, 0.0))
                continue
            
            # Exclude Neck and Head from rotation overrides in Pass 2 to prevent stale accumulation
            if bone_name in ["mixamorig:Neck", "mixamorig:Head"]:
                continue
            
            # Get current rotation to adjust
            rot = tgt_pbone.rotation_quaternion.copy()
            
            # Apply scaling for legs
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
                
            tgt_pbone.rotation_quaternion = rot
        
        # Update Blender view layer after Pass 2 so Pass 4 queries fresh bone matrices
        # Pass 3 (dynamic arm spread/collision avoidance) is removed to keep the arms completely frozen in their rest pose
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
        
        # Pass 5: Add look left & right look-around overlay animation (loopable, smooth, no accumulation)
        # Update view layer first to get the correct head bone position after hip translation
        bpy.context.view_layer.update()
        
        p_head = target_arm.pose.bones.get("mixamorig:Head")
        if p_head:
            idx = frame - start_frame + 1
            
            # Timeline sequence (smooth look left/right & nod down):
            # 1-30: Look straight (0.0)
            # 30-60: Look Left (Y goes from 0.0 to 0.5)
            # 60-80: Hold Left (Y = 0.5)
            # 80-110: Y goes from 0.5 back to 0.0
            # 110-130: Hold at Center
            # 130-160: Look Right (Y goes from 0.0 to -0.5)
            # 160-185: Hold Y at -0.5, X goes from 0.0 to -0.25
            # 185-210: Hold Y at -0.5, X at -0.25
            # 210-245: Y goes from -0.5 back to 0.0 (X stays at -0.25)
            # 245-280: X goes from -0.25 back to 0.0 (Y stays at 0.0)
            # 280-301: Look straight
            
            yaw = 0.0
            pitch = 0.0
            
            if 30 <= idx < 60:
                t = (idx - 30) / 30.0
                t_smooth = t * t * (3 - 2 * t)
                yaw = t_smooth * 0.5
            elif 60 <= idx < 80:
                yaw = 0.5
            elif 80 <= idx < 110:
                t = (idx - 80) / 30.0
                t_smooth = t * t * (3 - 2 * t)
                yaw = (1.0 - t_smooth) * 0.5
            elif 110 <= idx < 130:
                yaw = 0.0
            elif 130 <= idx < 160:
                t = (idx - 130) / 30.0
                t_smooth = t * t * (3 - 2 * t)
                yaw = t_smooth * -0.5
            elif 160 <= idx < 185:
                yaw = -0.5
                t = (idx - 160) / 25.0
                t_smooth = t * t * (3 - 2 * t)
                pitch = t_smooth * -0.25
            elif 185 <= idx < 210:
                yaw = -0.5
                pitch = -0.25
            elif 210 <= idx < 245:
                t = (idx - 210) / 35.0
                t_smooth = t * t * (3 - 2 * t)
                yaw = (1.0 - t_smooth) * -0.5
                pitch = -0.25
            elif 245 <= idx < 280:
                yaw = 0.0
                t = (idx - 245) / 35.0
                t_smooth = t * t * (3 - 2 * t)
                pitch = (1.0 - t_smooth) * -0.25
                
            # Calculate the head's rest pose matrix in armature space relative to parent's current pose (from scratch!)
            b_head = target_arm.data.bones.get("mixamorig:Head")
            if p_head.parent and b_head and b_head.parent:
                L_rest_head = b_head.parent.matrix_local.inverted() @ b_head.matrix_local
                M_rest_armature = p_head.parent.matrix @ L_rest_head
            elif b_head:
                M_rest_armature = b_head.matrix_local.copy()
            else:
                M_rest_armature = p_head.matrix.copy()
                
            # Rotate in armature space around armature Z (yaw) and X (pitch) axes at the head's pivot
            P_head_head = M_rest_armature.to_translation()
            M_trans = mathutils.Matrix.Translation(P_head_head)
            
            R_yaw = mathutils.Quaternion((0.0, 0.0, 1.0), yaw)
            R_pitch = mathutils.Quaternion((1.0, 0.0, 0.0), pitch)
            R_total = R_yaw @ R_pitch
            
            M_rot = M_trans @ R_total.to_matrix().to_4x4() @ M_trans.inverted()
            p_head.matrix = M_rot @ M_rest_armature

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
    # Disabled to avoid deleting active GLB assets
    return []

@app.local_entrypoint()
def main(choice: str = None, no_download: bool = False):
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
    
    # Clean up local GLB files in Downloads folder on start - DISABLED
    # print("[+] Cleaning up local GLB files in Downloads folder...")
    # if os.path.exists(downloads_dir):
    #     for f in os.listdir(downloads_dir):
    #         if f.endswith(".glb"):
    #             try:
    #                 os.remove(os.path.join(downloads_dir, f))
    #                 print(f"[+] Deleted local GLB: {f}")
    #             except Exception:
    #                 pass
                    
    if use_modal:
        # Delete any GLB files on the volume - DISABLED
        # print("[+] Checking and deleting GLB files on volume...")
        # try:
        #     deleted_glbs = delete_glb_files.remote()
        #     if deleted_glbs:
        #         print(f"[+] Cleaned up GLB files: {deleted_glbs}")
        # except Exception as e:
        #     print(f"[-] Warning: Failed to clean GLB files on volume: {e}")
        pass
            
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
                    if not no_download:
                        with open(local_dest, "wb") as f:
                            f.write(animated_bytes)
                        print(f"[+] Success! Downloaded to: {local_dest} ({len(animated_bytes):,} bytes)")
                    else:
                        print(f"[+] Success! Retargeted idle animation saved on Modal outputs volume.")
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
