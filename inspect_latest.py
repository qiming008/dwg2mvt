import sqlite3
import os
import glob

# Try to find the latest modified GPKG
jobs_dir = r"d:\project\LibreDWG\backend\data\jobs"
gpkg_files = glob.glob(os.path.join(jobs_dir, "*", "*.gpkg"))
if not gpkg_files:
    print("No GPKG files found")
    exit()

latest_gpkg = r"d:\project\LibreDWG\backend\data\jobs\c83b131f99ed46bfa8bcd018025c4593\anteen.gpkg"
print(f"Inspecting target GPKG: {latest_gpkg}")

conn = sqlite3.connect(latest_gpkg)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# 1. Check Columns
c.execute("PRAGMA table_info(entities)")
columns = [r['name'] for r in c.fetchall()]
print(f"Columns: {columns}")

# 2. Check Colors
if 'line_color' in columns:
    print("\n--- Line Color Stats ---")
    c.execute("SELECT line_color, Count(*) FROM entities GROUP BY line_color")
    for r in c.fetchall():
        print(f"'{r[0]}': {r[1]}")
else:
    print("line_color column missing!")

# 3. Check Geometry Types (using WKB parsing)
print("\n--- Geometry Types (WKB) ---")
try:
    c.execute("SELECT geom FROM entities")
    geom_types = {}
    for row in c:
        blob = row[0]
        if not blob:
            t = "None"
        else:
            # GPKG Geometry Header:
            # Byte 0-1: 'GP' (0x47 0x50)
            # Byte 2: Version (0)
            # Byte 3: Flags
            # Byte 4-??: SRS ID
            # Then WKB...
            # But ogr2ogr might write standard WKB or GPKG blob? 
            # GPKG spec says it MUST be GPKG blob.
            # Header is at least 8 bytes (flags) + srs_id (4 bytes) = 8 bytes?
            # header length depends on flags.
            # Usually we can skip header.
            # But wait, python sqlite returns bytes.
            # Let's just look at the WKB type if we can find it.
            # Simpler: just use hex string of start to guess.
            pass
            
            # Parsing GPKG header
            # byte 0-1: magic 0x47 0x50
            # byte 2: version
            # byte 3: flags. 
            # bit 0: empty geometry flag.
            # bit 1-3: envelope type.
            # bit 4: endianness (0=big, 1=little)
            # bit 5: srs_id present (always 1 in v1.0?) No.
            
            # Let's rely on standard WKB type codes which are usually at offset if we skip header.
            # But easier: Count by 'geometry_type_name' from gpkg_geometry_columns was 'GEOMETRY'.
            # That means mixed types are allowed.
            pass
            
    # Actually, better to query:
    c.execute("SELECT ST_GeometryType(geom), Count(*) FROM entities GROUP BY ST_GeometryType(geom)")
    # Wait, ST_GeometryType is not available in standard python sqlite3.
    
    # Fallback: Count by just parsing the integer type from WKB?
    # Too complex for quick script.
    print("Skipping WKB parse (too complex without SpatiaLite).")
except Exception as e:
    print(f"Geometry check error: {e}")

# 3b. Check Text Colors
print("\n--- Text Color Stats ---")
c.execute("SELECT text_color, Count(*) FROM entities WHERE Text IS NOT NULL GROUP BY text_color")
for r in c.fetchall():
    print(f"'{r[0]}': {r[1]}")

# 4. Check 'txt' layer specific
print("\n--- 'txt' Layer Stats ---")
try:
    c.execute("SELECT Layer, text_size, text_color, line_color, anchor_x, anchor_y FROM entities WHERE Layer LIKE '%txt%' LIMIT 20")
    rows = c.fetchall()
    if rows:
        print(f"Found {len(rows)} rows in txt layer:")
        for r in rows:
            print(dict(r))
    else:
        print("No 'txt' layer found. Listing all layers:")
        c.execute("SELECT DISTINCT Layer FROM entities LIMIT 20")
        for r in c.fetchall():
            print(r[0])
            
    # Check text_size stats
    print("\n--- Text Size Stats (All Layers) ---")
    c.execute("SELECT MIN(text_size), MAX(text_size), AVG(text_size) FROM entities WHERE text_size IS NOT NULL")
    r = c.fetchone()
    print(f"Min: {r[0]}, Max: {r[1]}, Avg: {r[2]}")
    
    # Check Geometry Bounds for txt layer
    print("\n--- Geometry Bounds (txt layer) ---")
    c.execute("SELECT ST_MinX(geom), ST_MaxX(geom), ST_MinY(geom), ST_MaxY(geom) FROM entities WHERE Layer LIKE '%txt%'")
    r = c.fetchone()
    print(f"Txt Bounds: X[{r[0]}, {r[1]}], Y[{r[2]}, {r[3]}]")

    # Check Global Bounds
    print("\n--- Global Bounds ---")
    c.execute("SELECT ST_MinX(geom), ST_MaxX(geom), ST_MinY(geom), ST_MaxY(geom) FROM entities")
    r = c.fetchone()
    print(f"Global Bounds: X[{r[0]}, {r[1]}], Y[{r[2]}, {r[3]}]")

except Exception as e:
    print(f"Query failed: {e}")

conn.close()
