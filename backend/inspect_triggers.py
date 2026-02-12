import sys
import os
from pathlib import Path
import sqlite3

# Setup Environment for GDAL and LibreDWG
tools_dir = r"D:\project\LibreDWG\backend\tools"
# Add tools_dir for dwg2dxf.exe
os.environ["PATH"] = f"{tools_dir};{tools_dir}\\gdal\\bin\\gdal\\apps;{tools_dir}\\gdal\\bin;{os.environ['PATH']}"
os.environ["GDAL_DATA"] = f"{tools_dir}\\gdal\\bin\\gdal-data"
os.environ["PROJ_LIB"] = f"{tools_dir}\\gdal\\bin\\proj9\\share"

gpkg_path = Path(r"D:\project\LibreDWG\backend\data\jobs\eb9baa721885d3f0fe07dbc7c7d12fe4\新景公司15号煤层采掘工程平面图(2025年3月).gpkg")

if gpkg_path.exists():
    print(f"Inspecting {gpkg_path}...")
    conn = sqlite3.connect(gpkg_path)
    conn.text_factory = lambda b: b.decode(errors="ignore")
    c = conn.cursor()
    
    c.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'entities'")
    triggers = c.fetchall()
    for name, sql in triggers:
        print(f"Trigger {name}: {sql}")
        
    conn.close()
else:
    print("GPKG not found")
