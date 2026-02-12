import sqlite3
from pathlib import Path

# Path to the specific job GPKG
job_id = "eb9baa721885d3f0fe07dbc7c7d12fe4"
gpkg_path = Path("temp_check.gpkg")

def check_extent():
    if not gpkg_path.exists():
        print("GPKG not found")
        return

    print(f"Checking extent for {gpkg_path}...")
    conn = sqlite3.connect(gpkg_path)
    c = conn.cursor()
    try:
        # Check if gpkg_contents exists
        c.execute("SELECT min_x, min_y, max_x, max_y, srs_id FROM gpkg_contents WHERE table_name='entities'")
        row = c.fetchone()
        if row:
            print(f"Declared Extent: MinX={row[0]}, MinY={row[1]}, MaxX={row[2]}, MaxY={row[3]}, SRS={row[4]}")
        
        # Check raw data extent (approximate via MBR)
        # We can't use ST_MinX without loading spatialite, but we can inspect the geometry blob header?
        # No, that's too hard.
        # But wait, we previously saw rtree triggers.
        # We can query the rtree table!
        c.execute("SELECT min(minx), min(miny), max(maxx), max(maxy) FROM rtree_entities__ogr_geometry_")
        row = c.fetchone()
        if row:
             print(f"Actual Data Extent (from RTree): MinX={row[0]}, MinY={row[1]}, MaxX={row[2]}, MaxY={row[3]}")
             
             if row[0] is not None:
                 min_x = row[0]
                 if min_x > 20037508 or min_x < -20037508:
                     print("WARNING: X coordinate is outside Web Mercator bounds (+/- 20,037,508)")
                 else:
                     print("X coordinate seems within Web Mercator bounds.")
        else:
            print("Could not query rtree.")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    check_extent()
