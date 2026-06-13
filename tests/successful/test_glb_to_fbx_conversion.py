import os
import modal

app = modal.App("glb-to-fbx-converter")

trellis_outputs_vol = modal.Volume.from_name("trellis-outputs", create_if_missing=True)
convert_cache_vol  = modal.Volume.from_name("test-blender-cache", create_if_missing=True)

convert_image = (
    modal.Image.from_registry("nvidia/cuda:12.1.1-devel-ubuntu22.04", add_python="3.11")
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

BLENDER_SCRIPT = """
import bpy, sys, os, addon_utils

try:
    input_file  = sys.argv[-2]
    output_file = sys.argv[-1]

    addon_utils.enable("io_scene_gltf2", default_set=True)
    addon_utils.enable("io_scene_fbx",   default_set=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=input_file)

    # --- Extract specifically the Base Color / albedo texture ---
    output_dir = os.path.dirname(output_file)
    model_id   = os.path.splitext(os.path.basename(output_file))[0]

    albedo_image = None

    # Walk every material and look for the Base Color input on a Principled BSDF
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
                        albedo_image = link.from_node.image
                        print(f"Found Base Color image: {albedo_image.name}")
                        break
            if albedo_image:
                break
        if albedo_image:
            break

    # Fallback: pick the first non-utility image if no BSDF base color was found
    if albedo_image is None:
        SKIP = {"Render Result", "Viewer Node"}
        for img in bpy.data.images:
            if img.name not in SKIP and img.size[0] > 0:
                albedo_image = img
                print(f"Fallback: using first available image: {img.name}")
                break

    if albedo_image:
        tex_out = os.path.join(output_dir, f"{model_id}_texture.png")

        # Force proper PNG encoding via save_render.
        # img.save() can silently write raw WebP bytes (from the GLB source)
        # with a .png extension, producing a file Unity cannot read.
        # save_render() always fully decodes then re-encodes to the target format.
        scene = bpy.context.scene
        scene.render.image_settings.file_format  = "PNG"
        scene.render.image_settings.color_mode   = "RGBA"
        scene.render.image_settings.color_depth  = "8"
        albedo_image.save_render(filepath=tex_out, scene=scene)
        print(f"Saved Base Color texture (proper PNG): {tex_out}")
    else:
        print("WARNING: No texture image found in the scene.")

    bpy.ops.export_scene.fbx(
        filepath=output_file,
        check_existing=False,
        path_mode="AUTO",
        embed_textures=False,
    )
    print("FBX export complete.")
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
"""

@app.function(
    image=convert_image,
    gpu=None,           # no GPU needed for Blender conversion
    volumes={
        "/trellis_outputs": trellis_outputs_vol,
        "/convert_cache":   convert_cache_vol,
    },
    timeout=300,
)
def convert() -> tuple[str, bytes, str, bytes]:
    import subprocess, tempfile

    trellis_outputs_vol.reload()

    glb_files = sorted(f for f in os.listdir("/trellis_outputs") if f.endswith(".glb"))
    if not glb_files:
        raise ValueError("No .glb files found in trellis-outputs volume!")

    src_glb      = glb_files[0]
    src_glb_path = f"/trellis_outputs/{src_glb}"
    model_id     = src_glb.replace(".glb", "")
    fbx_name     = f"{model_id}.fbx"
    fbx_path     = f"/convert_cache/{fbx_name}"
    tex_name     = f"{model_id}_texture.png"
    tex_path     = f"/convert_cache/{tex_name}"

    print(f"Converting: {src_glb_path} → {fbx_path}")

    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(BLENDER_SCRIPT)
        script = f.name

    try:
        result = subprocess.run(
            [BLENDER, "--background", "--python", script, "--", src_glb_path, fbx_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        print(result.stdout)
        if result.returncode != 0:
            raise RuntimeError(f"Blender exited with code {result.returncode}")
        if not os.path.exists(fbx_path):
            raise RuntimeError("FBX file not created!")
    finally:
        os.remove(script)

    convert_cache_vol.commit()

    fbx_bytes = open(fbx_path, "rb").read()
    tex_bytes = open(tex_path, "rb").read() if os.path.exists(tex_path) else b""

    return fbx_name, fbx_bytes, tex_name, tex_bytes


@app.local_entrypoint()
def main():
    print("Running GLB → FBX conversion on Modal...")
    fbx_name, fbx_bytes, tex_name, tex_bytes = convert.remote()

    dl = os.path.expanduser("~/Downloads")

    fbx_out = os.path.join(dl, fbx_name)
    with open(fbx_out, "wb") as f:
        f.write(fbx_bytes)
    print(f"[+] FBX  saved → {fbx_out}  ({len(fbx_bytes):,} bytes)")

    if tex_bytes:
        tex_out = os.path.join(dl, tex_name)
        with open(tex_out, "wb") as f:
            f.write(tex_bytes)
        print(f"[+] PNG  saved → {tex_out}  ({len(tex_bytes):,} bytes)")
