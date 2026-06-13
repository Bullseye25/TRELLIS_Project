import modal
app = modal.App("list-trellis")
image = modal.Image.from_registry("ubuntu:22.04").apt_install("git").run_commands("git clone https://github.com/microsoft/TRELLIS.2.git /root/TRELLIS.2")
@app.function(image=image)
def f():
    import os
    print(os.listdir("/root/TRELLIS.2"))
    if os.path.exists("/root/TRELLIS.2/requirements.txt"):
        with open("/root/TRELLIS.2/requirements.txt") as f: print(f.read())
    elif os.path.exists("/root/TRELLIS.2/environment.yml"):
        with open("/root/TRELLIS.2/environment.yml") as f: print(f.read())
