import sys
from pathlib import Path
from app.services.conversion import _run, settings

def check_st_translate():
    print("Checking ST_Translate capability...")
    
    # We need a dummy file or just check if we can run a query
    # ogrinfo usually requires a datasource.
    # Let's create a tiny gpkg
    dummy_gpkg = Path("test_cap.gpkg")
    if dummy_gpkg.exists():
        dummy_gpkg.unlink()
        
    # Create empty gpkg using ogr2ogr (since we know it works)
    # actually just touch it? No, needs valid structure.
    # Use python to create minimal valid gpkg?
    # Or just try to run ogrinfo on a non-existent file with -sql "SELECT 1" sometimes works? No.
    
    # Let's use ogr2ogr to create one from nothing?
    # ogr2ogr -f GPKG test_cap.gpkg -dialect SQLite -sql "SELECT MakePoint(0,0) as geom"
    # This might fail if no input source.
    
    # Let's try creating a simple sqlite file
    import sqlite3
    conn = sqlite3.connect(dummy_gpkg)
    conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, geom BLOB)")
    conn.execute("INSERT INTO test (id, geom) VALUES (1, NULL)")
    conn.close()
    
    ogrinfo_cmd = Path(settings.ogr2ogr_cmd).parent / "ogrinfo.exe"
    
    cmd = [
        str(ogrinfo_cmd),
        str(dummy_gpkg),
        "-dialect", "SQLite",
        "-sql", "SELECT ST_AsText(ST_Translate(MakePoint(0,0), 10, 20))"
    ]
    
    success, output = _run(cmd)
    
    print(f"Success: {success}")
    print(f"Output: {output}")
    
    if "POINT (10 20)" in output:
        print("ST_Translate is AVAILABLE")
    else:
        print("ST_Translate is NOT available")

    if dummy_gpkg.exists():
        try:
            dummy_gpkg.unlink()
        except:
            pass

if __name__ == "__main__":
    check_st_translate()
