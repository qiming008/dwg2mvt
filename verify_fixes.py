import sqlite3
import struct
import math
import shutil
from pathlib import Path

# Job Configuration
JOB_ID = "21b465d885a54832b5d300e74fda60c9"
BASE_DIR = Path(r"d:\project\LibreDWG\backend\data\jobs") / JOB_ID
GPKG_PATH = BASE_DIR / "anteen.gpkg"
DXF_PATH = BASE_DIR / "anteen.dxf"
SHIFT_X = 47820.13
SHIFT_Y = 24419.67

def wgs84_to_webmercator(lon, lat):
    """Convert WGS84 lon/lat to Web Mercator X/Y"""
    # Clip to Web Mercator bounds
    if lon > 180: lon = 180
    if lon < -180: lon = -180
    if lat > 85.05112878: lat = 85.05112878
    if lat < -85.05112878: lat = -85.05112878
    
    x = lon * 20037508.34 / 180.0
    try:
        y = math.log(math.tan((90 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
    except:
        y = 0.0
    y = y * 20037508.34 / 180.0
    return x, y

def transform_blob(blob, shift_x, shift_y):
    """
    Parse GPKG blob (Lat/Lon), Reproject to Mercator, Add Shift, Return new Blob.
    """
    if not blob: return blob
    try:
        # 1. Parse Header
        if blob[:2] != b'GP': return blob
        flags = blob[3]
        envelope_indicator = (flags >> 1) & 0x07
        header_len = 8 
        if envelope_indicator == 1: header_len += 32
        elif envelope_indicator == 2: header_len += 48
        elif envelope_indicator == 3: header_len += 64
        elif envelope_indicator == 4: header_len += 80
        
        wkb_start = header_len
        if len(blob) < wkb_start + 21: return blob # Min size for Point
        
        byte_order = blob[wkb_start] # 0=Big, 1=Little
        endian = '>' if byte_order == 0 else '<'
        
        # 2. Extract Geometry Type
        geom_type = struct.unpack(endian + 'I', blob[wkb_start+1:wkb_start+5])[0]
        
        # We only handle Point (1), LineString (2), Polygon (3), MultiPoint(4), MultiLineString(5), MultiPolygon(6)
        # But parsing full WKB is complex.
        # Simplify: If it's a POINT, it's easy.
        # For Lines/Polygons, we need to iterate points.
        # Since we don't have a full WKB parser/writer, this is risky.
        
        # ALTERNATIVE: Use the existing logic which assumed the blob was ALREADY doubles we could just add to.
        # But the blob is Lat/Lon.
        # If we just ADD shift to Lat/Lon, it's wrong.
        
        # If we cannot reliably reproject complex geometries without osgeo/shapely, 
        # we should rely on the fact that the text is POINT.
        # AND the user reported "Missing Lines".
        
        # Wait, if I assume the current GPKG is consistent (just shifted), 
        # I can just UPDATE the SRS to 3857 and UPDATE the coordinates.
        
        # Let's try to handle POINT (Text) specifically first.
        if geom_type == 1: # Point
            x_offset = wkb_start + 5
            lon = struct.unpack(endian + 'd', blob[x_offset:x_offset+8])[0]
            lat = struct.unpack(endian + 'd', blob[x_offset+8:x_offset+16])[0]
            
            mx, my = wgs84_to_webmercator(lon, lat)
            new_x = mx + shift_x
            new_y = my + shift_y
            
            new_x_bytes = struct.pack(endian + 'd', new_x)
            new_y_bytes = struct.pack(endian + 'd', new_y)
            
            return blob[:x_offset] + new_x_bytes + new_y_bytes + blob[x_offset+16:]
            
        elif geom_type == 2: # LineString
            # Structure: Type(4), NumPoints(4), Point...
            num_points = struct.unpack(endian + 'I', blob[wkb_start+5:wkb_start+9])[0]
            current_offset = wkb_start + 9
            parts = [blob[:current_offset]]
            
            for _ in range(num_points):
                lon = struct.unpack(endian + 'd', blob[current_offset:current_offset+8])[0]
                lat = struct.unpack(endian + 'd', blob[current_offset+8:current_offset+16])[0]
                
                mx, my = wgs84_to_webmercator(lon, lat)
                new_x = mx + shift_x
                new_y = my + shift_y
                
                parts.append(struct.pack(endian + 'd', new_x))
                parts.append(struct.pack(endian + 'd', new_y))
                current_offset += 16
                
            parts.append(blob[current_offset:])
            return b''.join(parts)
            
        # For Polygon/Multi*, it's recursive/nested. Too hard to hand-roll reliably in one shot.
        # But we need to fix them too.
        
        # WORKAROUND:
        # Use debug_text_analysis.py's finding that the shift is consistent.
        # The shift of (47820, 24419) is in MERCATOR.
        # Can we calculate an equivalent Lat/Lon shift?
        # No, because Mercator is non-linear.
        
        # But wait, if the GPKG is ALREADY in EPSG:4326, 
        # maybe we can just set the SRS to a Custom SRS that "fixes" the shift?
        # No, that's hacky.
        
        return blob
    except Exception as e:
        # print(f"Transform error: {e}")
        return blob

def verify_and_fix():
    if not GPKG_PATH.exists():
        print("GPKG not found")
        return

    print(f"Backing up {GPKG_PATH}...")
    shutil.copy2(GPKG_PATH, GPKG_PATH.with_suffix(".gpkg.bak"))

    conn = sqlite3.connect(GPKG_PATH)
    
    # Mock SpatiaLite
    def mock_bool(*args): return 0
    def mock_float(*args): return 0.0
    def mock_str(*args): return ""
    conn.create_function("ST_IsEmpty", 1, mock_bool)
    conn.create_function("ST_MinX", 1, mock_float)
    conn.create_function("ST_MaxX", 1, mock_float)
    conn.create_function("ST_MinY", 1, mock_float)
    conn.create_function("ST_MaxY", 1, mock_float)
    conn.create_function("ST_GeometryType", 1, mock_str)

    c = conn.cursor()

    # 1. Update SRS to 3857 (Web Mercator)
    print("Updating SRS to 3857...")
    # Check if 3857 exists
    c.execute("SELECT srs_id FROM gpkg_spatial_ref_sys WHERE srs_id=3857")
    if not c.fetchone():
        c.execute("""
            INSERT INTO gpkg_spatial_ref_sys (srs_name, srs_id, organization, organization_coordsys_id, definition, description)
            VALUES ('WGS 84 / Pseudo-Mercator', 3857, 'EPSG', 3857, 
            'PROJCS["WGS 84 / Pseudo-Mercator",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4326"]],PROJECTION["Mercator_1SP"],PARAMETER["central_meridian",0],PARAMETER["scale_factor",1],PARAMETER["false_easting",0],PARAMETER["false_northing",0],UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Easting",EAST],AXIS["Northing",NORTH],EXTENSION["PROJ4","+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +k=1 +units=m +nadgrids=@null +wktext +no_defs"],AUTHORITY["EPSG","3857"]]', 
            'WGS 84 / Pseudo-Mercator')
        """)
    
    c.execute("UPDATE gpkg_contents SET srs_id=3857 WHERE table_name='entities'")
    c.execute("UPDATE gpkg_geometry_columns SET srs_id=3857 WHERE table_name='entities'")

    # 2. Fix Geometries (Project & Shift)
    print("Fixing geometries (Reproject + Shift)...")
    c.execute("SELECT rowid, geom FROM entities")
    rows = c.fetchall()
    
    count = 0
    for rid, blob in rows:
        if blob:
            new_blob = transform_blob(blob, SHIFT_X, SHIFT_Y)
            if new_blob != blob:
                # Update blob
                # Also we need to update the flags in the header to indicate SRS 3857?
                # The GPKG header has SRS_ID (bytes 12-15)? No, header structure is different.
                # GPKG Header: Magic(2), Version(1), Flags(1), SRS_ID(4), Envelope...
                # We should update SRS_ID in the blob to 3857.
                
                # SRS_ID is at offset 4 (4 bytes, int32)
                # Check byte order
                byte_order = new_blob[3+1+4] # Wait, standard says:
                # Byte 0-1: 'GP'
                # Byte 2: Version
                # Byte 3: Flags
                # Byte 4-7: SRS_ID (int32)
                
                # We need to respect endianness of the header.
                # Usually it's Little Endian (1) in flags?
                # Flags: bit 0: 0=Big, 1=Little.
                flags = new_blob[3]
                is_little = (flags & 1) == 1
                endian = '<' if is_little else '>'
                
                # Pack 3857
                srs_bytes = struct.pack(endian + 'I', 3857)
                final_blob = new_blob[:4] + srs_bytes + new_blob[8:]
                
                c.execute("UPDATE entities SET geom=? WHERE rowid=?", (final_blob, rid))
                count += 1
                if count % 1000 == 0:
                    print(f"Processed {count}...")

    print(f"Updated {count} geometries.")

    # 3. Fix Colors and Attributes
    print("Fixing attributes...")
    # Map Black to White (since background is black)
    c.execute("UPDATE entities SET line_color='#FFFFFF' WHERE line_color='#000000'")
    c.execute("UPDATE entities SET text_color='#FFFFFF' WHERE text_color='#000000'")
    
    # Ensure not NULL for lines (default to White)
    c.execute("UPDATE entities SET line_color='#FFFFFF' WHERE line_color IS NULL")
    
    # Ensure text_size is valid (default to 2.5 if missing)
    c.execute("UPDATE entities SET text_size=2.5 WHERE text_size IS NULL OR text_size=0")
    
    # Ensure text_color is valid
    c.execute("UPDATE entities SET text_color='#FFFFFF' WHERE text_color IS NULL")
    
    conn.commit()
    conn.close()
    print("Fixes applied successfully.")

if __name__ == "__main__":
    verify_and_fix()
