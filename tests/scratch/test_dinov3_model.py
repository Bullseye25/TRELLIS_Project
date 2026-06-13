import modal

app = modal.App("test-dinov3")
image = modal.Image.debian_slim().apt_install("git").pip_install("torch", "git+https://github.com/huggingface/transformers.git")

@app.function(image=image)
def f():
    from transformers import DINOv3ViTConfig, DINOv3ViTModel
    config = DINOv3ViTConfig()
    model = DINOv3ViTModel(config)
    print("DINOv3ViTModel attributes:", [k for k in dir(model) if not k.startswith('_')])
    if hasattr(model, 'encoder'):
        print("Encoder attributes:", [k for k in dir(model.encoder) if not k.startswith('_')])

