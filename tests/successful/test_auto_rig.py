import os
import sys
import modal
import subprocess

def main():
    print("================================================================")
    print("   UniRig / SkinTokens Auto-Rigging Integration Unit Test")
    print("================================================================")
    
    app_name = "skintokens-deployment"
    fn_name = "rig_glb"
    
    # 1. Lookup the deployed Modal function
    try:
        print(f"[1/4] Looking up remote function '{fn_name}' in deployed app '{app_name}'...")
        rig_fn = modal.Function.from_name(app_name, fn_name)
        print("      Found remote function successfully!")
    except Exception as e:
        print(f"\n[-] Error: Could not look up remote function. Details: {e}")
        print("    Please make sure 'deploy_skintokens.py' is deployed and running.")
        sys.exit(1)
        
    input_file = "7048d62e-ed69-4668-8add-734c0b0bc327.glb"
    output_file = "7048d62e-ed69-4668-8add-734c0b0bc327_rigged.glb"
    
    # 2. Trigger the remote rigging function
    print(f"[2/4] Invoking remote '{fn_name}' function...")
    print(f"      Input GLB:  {input_file}")
    print(f"      Output GLB: {output_file}")
    print("      (This may take a minute or two as the GPU container starts up and processes the mesh...)")
    
    try:
        result_filename = rig_fn.remote(input_file, output_file)
        print(f"[3/4] Remote execution completed successfully! Returned filename: {result_filename}")
    except Exception as e:
        print(f"\n[-] Error during remote rigging execution: {e}")
        print("    Please verify the skintokens-deployment logs and check if the input file exists on the volume.")
        sys.exit(1)
        
    # 3. Verify output file exists on volume and download it
    downloads_dir = os.path.expanduser("~/Downloads")
    local_output_path = os.path.join(downloads_dir, output_file)
    print(f"[4/4] Downloading rigged model from volume 'trellis-outputs' to '{local_output_path}'...")
    
    try:
        # Check volume contents to make sure the file was written
        vol_ls_res = subprocess.run([
            "python3", "-m", "modal", "volume", "ls", "trellis-outputs"
        ], capture_output=True, text=True, check=True)
        
        if output_file not in vol_ls_res.stdout:
            raise FileNotFoundError(f"Output file {output_file} was not found in 'trellis-outputs' volume listing.")
            
        subprocess.run([
            "python3", "-m", "modal", "volume", "get", "trellis-outputs", output_file, local_output_path
        ], check=True)
        
        file_size = os.path.getsize(local_output_path)
        print(f"\n[+] SUCCESS! Rigged model downloaded to: {local_output_path} ({file_size:,} bytes)")
        print("================================================================")
        
    except Exception as e:
        print(f"\n[-] Error verifying/downloading rigged model: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
