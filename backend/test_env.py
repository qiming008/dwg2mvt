from pathlib import Path
import os

BACKEND_DIR = Path(__file__).resolve().parent
GDAL_BIN_DIR = BACKEND_DIR / "tools" / "gdal" / "bin"
print(f"BACKEND_DIR: {BACKEND_DIR}")
print(f"GDAL_BIN_DIR: {GDAL_BIN_DIR}")
print(f"Exists: {GDAL_BIN_DIR.exists()}")

proj_lib = GDAL_BIN_DIR / "proj9" / "share"
print(f"Checking {proj_lib}: {proj_lib.exists()}")

if not proj_lib.exists():
    proj_lib = GDAL_BIN_DIR / "proj" / "share"
    print(f"Checking {proj_lib}: {proj_lib.exists()}")

proj_db = proj_lib / "proj.db"
print(f"Checking {proj_db}: {proj_db.exists()}")
