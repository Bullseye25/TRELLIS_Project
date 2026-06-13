# Chibi 3D Studio: 2D-to-3D Generation & Animation Pipeline

Chibi 3D Studio is an end-to-end generative pipeline that transforms a 2D text prompt or reference image into a fully rigged, animated 3D chibi character. 

The system automatically generates a 3D mesh, applies professional skeletal rigging, retargets three customized game-ready animation clips (**Walk**, **Idle**, and **Thinking**), and exports everything into a single, multi-take FBX file with a separate high-resolution albedo texture download.

---

## 🚀 Key Features

*   **Prompt-to-3D Generation**: Utilizes **TRELLIS.2** for outstanding mesh quality, geometry details, and texture generation.
*   **Instant Auto-Rigging**: Integrated with **SkinTokens** to auto-rig the generated humanoid mesh within seconds.
*   **Procedural Animation Retargeting**: Headless Blender bakes custom animation cycles onto the rigged armature:
    *   **Walk**: Seamlessly loops with waddle sway and periodic loop boundary smoothing to prevent popping.
    *   **Idle**: Breathing cycle with locked arm rotations and randomized natural look-around head offsets.
    *   **Thinking**: Breathing cycle with parallel right arm transition, local forearm translation, and customized head nodding/shaking.
*   **Multi-Take FBX Export**: Exports all three animations as cleanly named takes (`Walk`, `Idle`, `Thinking`) in a single FBX file.
*   **Separated Texture Downloads**: Extracts the albedo map to download separately from the FBX, simplifying game engine import (Unity, Unreal, Godot).

---

## 🛠️ Technology Stack

1.  **3D Generation**: [TRELLIS.2](https://github.com/microsoft/TRELLIS) - SOTA sparse structure guidance pipeline.
2.  **Auto-Rigging**: [SkinTokens](https://github.com/VAST-AI-Research/SkinTokens) - Deep learning skinning framework.
3.  **Animation & Retargeting Subprocess**: Headless Blender (v4.2.0) running inside serverless GPU containers.
4.  **Cloud Infrastructure**: [Modal](https://modal.com/) - Serverless GPU platform for cost-efficient, on-demand scaling.
5.  **Local Web Server**: Python 3 standard library `http.server` & `FastAPI`.
6.  **Web Interface**: Vanilla HTML5, CSS3, and JavaScript utilizing Three.js/Model-Viewer for 3D preview.

---

## 💰 Cost Comparison: Serverless vs. Dedicated Instance

Running generative 3D models on dedicated cloud instances is highly expensive due to idle time. Here is why serverless deployment on Modal is significantly superior:

| Feature / Metric | Dedicated GPU Instance (AWS g5.xlarge / A10G) | Modal Serverless L4 GPU |
| :--- | :--- | :--- |
| **Hourly Rate** | ~$1.00 / hour | ~$0.43 / hour (only when active) |
| **Monthly Idle Cost** | **$720.00 / month** (always on) | **$0.00 / month** |
| **Scaledown Policy** | Manual or complex auto-scale | Auto-shuts down after 60s of inactivity |
| **Cost Per Character** | N/A (paying constantly) | **~$0.04 - $0.05** per run (~6 mins) |

---

## 💻 Step-by-Step Setup Guide (macOS)

### 1. Prerequisites
Ensure you have the following installed on your Mac:
*   Python 3.9+
*   Git

### 2. Clone the Repository
```bash
git clone <your-repo-url>
cd TRELLIS_Project
```

### 3. Install Python Dependencies
Install Modal and other required local launcher dependencies:
```bash
pip install modal fastapi python-multipart
```

### 4. Authenticate with Modal
If you don't have a Modal account, sign up at [modal.com](https://modal.com/). Then run:
```bash
python3 -m modal setup
```

### 5. Using Your Own Servers & Accounts (Credentials Reset)
By default, the project might contain cached API urls or tokens in `credentials.txt`. To use your own Modal account, Hugging Face Token, or OpenAI keys, delete the credentials file before launching:
```bash
rm credentials.txt
```
When you start the launcher, it will automatically prompt you for:
*   Your **Hugging Face Token** (required to pull TRELLIS weights).
*   Your **OpenAI API Key** (optional, used for the 2D prompt generator).

### 6. Launch the application
Run the local launcher script:
```bash
python3 start.py
```
From the interactive menu:
1. Select option **`1`** (**Full Flow**) if running for the first time. This caches weights, deploys backends to Modal, and opens the frontend.
2. Select option **`6`** (**Skip Deploy**) on subsequent runs to start the web interface instantly using cached endpoints.

---

## ⏱️ Time Estimates (What to Expect)

Setting up and running deep learning pipelines takes time during the initial caching phases. Here is a timeline breakdown:

*   **Pre-caching Model Weights (First run only)**: **~15 - 20 minutes**  
    Downloads and caches ~15 GB of model weights (TRELLIS.2 + SkinTokens) from Hugging Face into Modal persistent volumes. Subsequent deployments bypass this stage entirely.
*   **Backend API Deployments**: **~1 - 2 minutes**  
    Builds the GPU container images and deploys endpoints to your Modal account.
*   **Backend Cold Start / Warmup**: **~2 - 3 minutes**  
    Pre-loads the weights from the cloud volumes into GPU VRAM on container startup.
*   **Character Generation Flow**: **~5 - 7 minutes**  
    *   *2D-to-3D Generation*: ~4 - 5 minutes
    *   *Auto-Rigging*: ~30 seconds
    *   *Animation Retargeting & FBX Export*: ~30 seconds
