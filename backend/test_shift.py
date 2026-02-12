import os
import sqlite3
from pathlib import Path
from app.services.conversion import _run, settings

def test_shift():
    src = Path("test_src.gpkg")
    if src.exists(): src.unlink()
    
    with open("test.csv", "w") as f:
        f.write("id,name,wkt\n1,test,POINT(100 100)")
        
    ogr2ogr = settings.ogr2ogr_cmd
    cmd = [ogr2ogr, "-f", "GPKG", str(src), "test.csv", "-oo", "GEOM_POSSIBLE_NAMES=wkt", "-a_srs", "EPSG:4326"]
    _run(cmd)
    os.remove("test.csv")
    
    dst = Path("test_dst.gpkg")
    if dst.exists(): dst.unlink()
    
    # Try float args
    sql = "SELECT ST_Translate(geom, -10.0, -10.0) as geom, * FROM test"
    print(f"Trying: {sql}")
    
    cmd = [
        ogr2ogr, "-f", "GPKG", str(dst), str(src), "-dialect", "SQLite", "-sql", sql, "-nln", "test_layer"
    ]
    ok, out = _run(cmd)
    if ok:
        print("Success with 2 args (floats)")
    else:
        print(f"Failed: {out}")
        
        # Try 3 args (z)
        if dst.exists(): dst.unlink()
        sql = "SELECT ST_Translate(geom, -10.0, -10.0, 0.0) as geom, * FROM test"
        print(f"Trying: {sql}")
        cmd = [ogr2ogr, "-f", "GPKG", str(dst), str(src), "-dialect", "SQLite", "-sql", sql, "-nln", "test_layer"]
        ok, out = _run(cmd)
        if ok:
             print("Success with 3 args (z)")
        else:
             print(f"Failed: {out}")

    # Clean up
    if src.exists(): src.unlink()
    if dst.exists(): dst.unlink()

if __name__ == "__main__":
    test_shift()
