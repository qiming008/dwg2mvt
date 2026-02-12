import sqlite3
import httpx
import base64
from pathlib import Path
import time

# Configuration
JOB_ID = "c83b131f99ed46bfa8bcd018025c4593"
NEW_STORE_NAME = f"ds_{JOB_ID}"
LAYER_NAME = "anteen"
GEOSERVER_URL = "http://localhost:8080/geoserver"
WORKSPACE = "dwg"
USER = "admin"
PASSWORD = "geoserver"
BACKEND_PATH = Path(r"D:\project\LibreDWG\backend")
GPKG_PATH = BACKEND_PATH / "data" / "jobs" / JOB_ID / "anteen.gpkg"

def get_auth_headers():
    raw = f"{USER}:{PASSWORD}"
    token = base64.b64encode(raw.encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

def fix_text_size_units():
    """
    Check if text_size is disproportionately large compared to drawing bounds (e.g. mm vs m).
    If so, scale it down by 1000.
    """
    print(f"Checking text size scaling in {GPKG_PATH}...")
    try:
        conn = sqlite3.connect(GPKG_PATH)
        
        # Mock SpatiaLite functions to satisfy triggers
        def mock_bool(*args): return 0
        def mock_float(*args): return 0.0
        def mock_str(*args): return ""
        conn.create_function("ST_IsEmpty", 1, mock_bool)
        conn.create_function("ST_MinX", 1, mock_float)
        conn.create_function("ST_MaxX", 1, mock_float)
        conn.create_function("ST_MinY", 1, mock_float)
        conn.create_function("ST_MaxY", 1, mock_float)
        conn.create_function("ST_GeometryType", 1, mock_str)
        conn.create_function("ST_Srid", 1, mock_float) # Sometimes needed

        c = conn.cursor()
        
        # Get BBOX width
        c.execute("SELECT max_x - min_x FROM gpkg_contents WHERE table_name='entities'")
        row = c.fetchone()
        if not row:
            print("Could not determine bbox.")
            return
        
        bbox_width = row[0]
        if bbox_width is None or bbox_width <= 0:
            print(f"Invalid bbox width: {bbox_width}")
            return
            
        # Get Max Text Size
        c.execute("SELECT MAX(text_size) FROM entities")
        row = c.fetchone()
        if not row or row[0] is None:
            print("No text size found.")
            return
            
        max_text_size = row[0]
        
        ratio = max_text_size / bbox_width
        print(f"BBox Width: {bbox_width:.4f}, Max Text Size: {max_text_size:.4f}, Ratio: {ratio:.2f}")
        
        # Threshold: if text is > 10x larger than drawing, assume unit mismatch
        if ratio > 10:
            print("Detected unit mismatch (Text >> Geometry). Scaling text_size by 0.001...")
            c.execute("UPDATE entities SET text_size = text_size * 0.001 WHERE text_size IS NOT NULL")
            conn.commit()
            print(f"Updated {c.rowcount} rows.")
        else:
            print("Text size seems reasonable (or already fixed).")
            
        conn.close()
    except Exception as e:
        print(f"Failed to fix text sizes: {e}")

def update_styles():
    print("Updating SLD styles...")
    
    # Import from backend
    import sys
    if str(BACKEND_PATH) not in sys.path:
        sys.path.append(str(BACKEND_PATH))
        
    try:
        from app.services.geoserver_client import DWG_SLD, DWG_RASTER_SLD
    except ImportError as e:
        print(f"Import failed: {e}. Cannot update styles.")
        return

    client = httpx.Client(timeout=10)
    headers = get_auth_headers()
    headers["Content-Type"] = "application/vnd.ogc.sld+xml"
    
    # Update dwg_raster_style
    url = f"{GEOSERVER_URL}/rest/workspaces/{WORKSPACE}/styles/dwg_raster_style"
    resp = client.put(url, content=DWG_RASTER_SLD, headers=headers)
    if resp.status_code in (200, 201):
        print("Style dwg_raster_style updated.")
    else:
        print(f"Failed to update dwg_raster_style: {resp.status_code} {resp.text}")

def ensure_datastore():
    print(f"Ensuring datastore {NEW_STORE_NAME} exists...")
    client = httpx.Client(timeout=10)
    headers = get_auth_headers()
    
    # Check if exists
    url = f"{GEOSERVER_URL}/rest/workspaces/{WORKSPACE}/datastores/{NEW_STORE_NAME}"
    resp = client.get(url, headers=headers)
    
    if resp.status_code == 200:
        print(f"Datastore {NEW_STORE_NAME} exists.")
        return
        
    # Create
    print(f"Creating datastore {NEW_STORE_NAME} pointing to {GPKG_PATH}...")
    data = {
        "dataStore": {
            "name": NEW_STORE_NAME,
            "connectionParameters": {
                "entry": [
                    {"@key": "database", "$": str(GPKG_PATH)},
                    {"@key": "dbtype", "$": "geopkg"}
                ]
            }
        }
    }
    url = f"{GEOSERVER_URL}/rest/workspaces/{WORKSPACE}/datastores"
    resp = client.post(url, json=data, headers=headers)
    if resp.status_code == 201:
        print("Datastore created.")
    else:
        print(f"Failed to create datastore: {resp.status_code} {resp.text}")

def publish_layer():
    print(f"Publishing layer {LAYER_NAME}...")
    client = httpx.Client(timeout=10)
    headers = get_auth_headers()
    
    # Check if exists
    url = f"{GEOSERVER_URL}/rest/workspaces/{WORKSPACE}/datastores/{NEW_STORE_NAME}/featuretypes/{LAYER_NAME}"
    resp = client.get(url, headers=headers)
    if resp.status_code == 200:
        print(f"Layer {LAYER_NAME} already exists.")
        # We might want to refresh it?
        return

    # Publish
    data = {
        "featureType": {
            "name": LAYER_NAME,
            "nativeName": LAYER_NAME,
            "title": LAYER_NAME,
            "srs": "EPSG:4326",
            "enabled": True
        }
    }
    url = f"{GEOSERVER_URL}/rest/workspaces/{WORKSPACE}/datastores/{NEW_STORE_NAME}/featuretypes"
    resp = client.post(url, json=data, headers=headers)
    if resp.status_code == 201:
        print("FeatureType published successfully.")
    else:
        print(f"Failed to publish FeatureType: {resp.status_code} {resp.text}")

def truncate_gwc_cache(layer_name):
    print(f"Truncating GWC cache for {layer_name}...")
    # GeoWebCache REST API
    # POST /geoserver/gwc/rest/masstruncate
    # <truncateLayer><layerName>dwg:anteen</layerName></truncateLayer>
    
    client = httpx.Client(timeout=10)
    headers = get_auth_headers()
    headers["Content-Type"] = "text/xml"
    
    xml = f"<truncateLayer><layerName>{WORKSPACE}:{layer_name}</layerName></truncateLayer>"
    url = f"{GEOSERVER_URL}/gwc/rest/masstruncate"
    
    resp = client.post(url, content=xml, headers=headers)
    if resp.status_code == 200:
        print("Cache truncated.")
    else:
        print(f"Failed to truncate cache: {resp.status_code} {resp.text}")

def main():
    # 1. Fix data
    fix_text_size_units()
    
    # 2. Update styles
    update_styles()
    
    # 3. Ensure datastore
    ensure_datastore()
    
    # 4. Publish layer
    publish_layer()
    
    # 5. Clear cache
    truncate_gwc_cache(LAYER_NAME)
    
    print("All fixes applied.")

if __name__ == "__main__":
    main()
