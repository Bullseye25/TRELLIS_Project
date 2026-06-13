import modal
app = modal.App("test-ovoxel")
image = modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.10").apt_install("git", "build-essential", "ninja-build").pip_install("torch==2.6.0", "torchvision==0.21.0", "torchaudio==2.6.0", index_url="https://download.pytorch.org/whl/cu124").env({"TORCH_CUDA_ARCH_LIST": "8.0", "CC": "gcc", "CXX": "g++"}).pip_install("packaging", "ninja", "wheel", "setuptools").run_commands("git clone https://github.com/microsoft/TRELLIS.git /root/TRELLIS", "pip install -v /root/TRELLIS/o-voxel")
@app.function(image=image)
def f(): pass
