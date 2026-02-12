import httpx
from app.config import settings
import sys

def check_raster():
    base_url = settings.geoserver_url.rstrip("/")
    ws = settings.geoserver_workspace
    auth = (settings.geoserver_user, settings.geoserver_password)
    
    print(f"GeoServer: {base_url}, Workspace: {ws}")
    
    # 1. List layers to find one matching the job
    # The log showed layer name containing 'd8ad19e8'
    try:
        r = httpx.get(f"{base_url}/rest/workspaces/{ws}/layers.json", auth=auth)
        if r.status_code != 200:
            print(f"Failed to list layers: {r.status_code}")
            return
            
        layers = r.json().get("layers", {}).get("layer", [])
        target_layer = None
        for l in layers:
            if "d8ad19e8" in l["name"]:
                target_layer = l["name"]
                break
        
        if not target_layer:
            print("Target layer for job d8ad19e8 not found.")
            # Print first 5 layers just in case
            print("Available layers:", [l["name"] for l in layers[:5]])
            return
            
        print(f"Found layer: {target_layer}")
        
        # 2. Check layer styles
        r_layer = httpx.get(f"{base_url}/rest/workspaces/{ws}/layers/{target_layer}.json", auth=auth)
        if r_layer.status_code == 200:
            styles = r_layer.json().get("layer", {}).get("styles", {})
            print(f"Layer styles: {styles}")
        
        # 3. Try WMS GetMap (Raster)
        # ... (keep existing WMS check) ...
        
        # 4. Try WMTS GetTile (Raster) mimics frontend
        print("\n--- Testing WMTS ---")
        # Construct WMTS URL
        # TileMatrix=EPSG:900913:0, TileRow=0, TileCol=0
        
        wmts_url = f"{base_url}/gwc/service/wmts"
        params_wmts = {
            "layer": f"{ws}:{target_layer}",
            "style": f"{ws}:dwg_raster_style",
            "tilematrixset": "EPSG:900913",
            "Service": "WMTS",
            "Request": "GetTile",
            "Version": "1.0.0",
            "Format": "image/png",
            "TileMatrix": "EPSG:900913:0",
            "TileCol": "0",
            "TileRow": "0"
        }
        
        print(f"Requesting WMTS: {wmts_url} with params {params_wmts}")
        r_wmts = httpx.get(wmts_url, params=params_wmts, auth=auth, timeout=30.0)
        
        print(f"WMTS Status: {r_wmts.status_code}")
        if r_wmts.status_code != 200:
            print(f"WMTS Error content: {r_wmts.text[:500]}")
        else:
            print("WMTS Success! Image received.")

            
    except Exception as e:
        print(f"Error: {e}")

def inspect_gwc():
    base_url = settings.geoserver_url.rstrip("/")
    ws = settings.geoserver_workspace
    auth = (settings.geoserver_user, settings.geoserver_password)
    
    # Need layer name again
    # Quick hack: duplicate logic or just hardcode if we found it
    # Let's search again briefly
    r = httpx.get(f"{base_url}/rest/workspaces/{ws}/layers.json", auth=auth)
    layers = r.json().get("layers", {}).get("layer", [])
    target_layer = None
    for l in layers:
        if "d8ad19e8" in l["name"]:
            target_layer = l["name"]
            break
            
    if not target_layer:
        print("Layer not found for inspection")
        return

    full_layer = f"{ws}:{target_layer}"
    url = f"{base_url}/gwc/rest/layers/{full_layer}.xml"
    print(f"\nFetching GWC Config for: {url}")
    
    r = httpx.get(url, auth=auth)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        print("XML Content:")
        print(r.text)
    else:
        print(f"Error: {r.text}")

if __name__ == "__main__":
    check_raster()
    inspect_gwc()
