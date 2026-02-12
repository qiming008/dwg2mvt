import httpx
import sys

# Config
GS_URL = "http://localhost:8080/geoserver/dwg/wms"
USER = "admin"
PASS = "geoserver"
LAYER = "dwg:anteen"
BBOX = "-0.42,-0.25,0.42,0.25" # Slightly larger than extent
WIDTH = 1024
HEIGHT = 768
SRS = "EPSG:4326"

params = {
    "service": "WMS",
    "version": "1.1.1",
    "request": "GetMap",
    "layers": LAYER,
    "bbox": BBOX,
    "width": WIDTH,
    "height": HEIGHT,
    "srs": SRS,
    "styles": "dwg_raster_style",
    "format": "image/png"
}

auth = (USER, PASS)

print(f"Requesting {GS_URL} with params: {params}")
try:
    r = httpx.get(GS_URL, params=params, auth=auth, timeout=60.0)
    print(f"Status: {r.status_code}")
    if r.status_code != 200:
        print("Error content:")
        print(r.text[:2000])
    else:
        print(f"Success! Image received ({len(r.content)} bytes).")
except Exception as e:
    print(f"Request failed: {e}")
