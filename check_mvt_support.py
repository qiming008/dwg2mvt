import httpx
import sys
import xml.etree.ElementTree as ET

# User provided server URL
GEOSERVER_URL = "http://172.24.3.58:8080/geoserver"

def check_mvt_support():
    print(f"Checking GeoServer at {GEOSERVER_URL}...")
    
    # 1. Check WMS Capabilities for vector tiles support
    wms_url = f"{GEOSERVER_URL}/wms?service=WMS&version=1.1.1&request=GetCapabilities"
    print(f"Fetching WMS Capabilities: {wms_url}")
    
    try:
        r = httpx.get(wms_url, timeout=10)
        if r.status_code != 200:
            print(f"Error fetching WMS capabilities: {r.status_code}")
            return
            
        root = ET.fromstring(r.content)
        # Look for GetMap formats
        formats = []
        for fmt in root.findall(".//Request/GetMap/Format"):
            formats.append(fmt.text)
            
        if "application/vnd.mapbox-vector-tile" in formats:
            print("[OK] Vector Tiles (MVT) format found in WMS Capabilities.")
        else:
            print("[ERROR] Vector Tiles (MVT) format NOT found in WMS Capabilities!")
            print("Please install the GeoServer Vector Tiles extension.")
            print("Available formats:", formats[:5], "...")
            
    except Exception as e:
        print(f"Exception checking WMS: {e}")

    # 2. Check GWC Capabilities
    wmts_url = f"{GEOSERVER_URL}/gwc/service/wmts?request=GetCapabilities"
    print(f"\nFetching WMTS Capabilities: {wmts_url}")
    try:
        r = httpx.get(wmts_url, timeout=10)
        if r.status_code != 200:
            print(f"Error fetching WMTS capabilities: {r.status_code}")
            return
            
        if b"application/vnd.mapbox-vector-tile" in r.content:
             print("[OK] Vector Tiles format mentioned in WMTS Capabilities.")
        else:
             print("[WARNING] Vector Tiles format NOT found in WMTS Capabilities.")
             
    except Exception as e:
        print(f"Exception checking WMTS: {e}")

if __name__ == "__main__":
    check_mvt_support()
