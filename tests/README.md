# TRELLIS Project — Test Scripts

## Directory Structure

```
tests/
├── successful/          # Scripts that have been verified working end-to-end
│   ├── test_2d_character_generator.py
│   ├── test_glb_to_fbx_conversion.py
│   ├── test_glb_unirig_rigging.py
│   └── download_glb_from_volume.py
│
└── scratch/             # Early exploration / one-off debug scripts
    ├── test_ovoxel_import.py
    ├── test_dinov3_model.py
    └── list_trellis_repo.py
```

---

## ✅ Successful Tests

### `test_2d_character_generator.py`
**What it does:** Calls the OpenAI `gpt-image-2` model with the master character prompt
to generate a 1024×1024 PNG of a stylized 3D chibi character.
Handles both `url` and `b64_json` response formats.

**How to run:**
```bash
python3 tests/successful/test_2d_character_generator.py
```
*Requires: OpenAI API key at `TripoSplat_Project/poster generator/api_key.txt`*

---

### `test_glb_to_fbx_conversion.py`
**What it does:** Picks the first `.glb` from the `trellis-outputs` Modal volume,
runs a Blender 4.2 headless conversion, extracts the Base Color texture
as a proper PNG (via `save_render`), and downloads both to `~/Downloads`.

**How to run:**
```bash
python3 -m modal run tests/successful/test_glb_to_fbx_conversion.py
```

---

### `test_glb_unirig_rigging.py`
**What it does:** Full GLB → FBX → UniRig pipeline on Modal (A10G GPU).
Runs skeleton prediction, skin weight prediction, and mesh merging using
the VAST-AI UniRig model. Downloads unrigged FBX, rigged FBX, and texture PNG
to `~/Downloads`.

**How to run:**
```bash
python3 -m modal run tests/successful/test_glb_unirig_rigging.py
```
*Requires: `triposplat-model-weights` volume with UniRig weights pre-cached.*

---

### `download_glb_from_volume.py`
**What it does:** Interactive CLI script — prompts for a GLB filename and
downloads it directly from the `trellis-outputs` Modal volume to `~/Downloads`.

**How to run:**
```bash
python3 tests/successful/download_glb_from_volume.py
```

---

## 🗂 Scratch Tests

These were written during early exploration and are kept for reference only.

| Script | Purpose |
|--------|---------|
| `test_ovoxel_import.py` | Verified that `o-voxel` could be installed from the TRELLIS repo |
| `test_dinov3_model.py` | Inspected DINOv3 model attributes via HuggingFace transformers |
| `list_trellis_repo.py` | Listed contents of the TRELLIS.2 repo and printed its requirements |
