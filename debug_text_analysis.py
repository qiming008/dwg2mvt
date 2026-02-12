import sqlite3
import re
import math
import struct
from pathlib import Path

def wgs84_to_webmercator(lon, lat):
    """Convert WGS84 lon/lat to Web Mercator X/Y"""
    if abs(lon) > 180 or abs(lat) > 90:
        return 0.0, 0.0
    x = lon * 20037508.34 / 180.0
    try:
        y = math.log(math.tan((90 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
    except:
        y = 0.0
    y = y * 20037508.34 / 180.0
    return x, y

def get_xy_from_wkb(blob):
    if not blob: return 0.0, 0.0
    try:
        if blob[:2] != b'GP': return 0.0, 0.0
        flags = blob[3]
        envelope_indicator = (flags >> 1) & 0x07
        header_len = 8 
        if envelope_indicator == 1: header_len += 32
        elif envelope_indicator == 2: header_len += 48
        elif envelope_indicator == 3: header_len += 64
        elif envelope_indicator == 4: header_len += 80
        wkb_start = header_len
        if len(blob) < wkb_start + 21: return 0.0, 0.0
        byte_order = blob[wkb_start] 
        endian = '>' if byte_order == 0 else '<'
        geom_type_val = struct.unpack(endian + 'I', blob[wkb_start+1:wkb_start+5])[0]
        
        if geom_type_val == 1: # Point
            x_offset = wkb_start + 5
            x = struct.unpack(endian + 'd', blob[x_offset:x_offset+8])[0]
            y = struct.unpack(endian + 'd', blob[x_offset+8:x_offset+16])[0]
            return x, y
        elif geom_type_val == 2: # LineString
            x_offset = wkb_start + 9
            x = struct.unpack(endian + 'd', blob[x_offset:x_offset+8])[0]
            y = struct.unpack(endian + 'd', blob[x_offset+8:x_offset+16])[0]
            return x, y
        else:
            return 0.0, 0.0
    except:
        return 0.0, 0.0

def parse_dxf_text_info(dxf_path):
    info = {}
    try:
        with open(dxf_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        iterator = iter(lines)
        current_handle = None
        current_type = None
        current_section = None
        attrs = {}
        while True:
            try:
                code = next(iterator).strip()
                value = next(iterator).strip()
            except StopIteration:
                break
            if code == '0':
                if value == 'SECTION':
                    try:
                        c2 = next(iterator).strip()
                        v2 = next(iterator).strip()
                        if c2 == '2':
                            current_section = v2
                    except:
                        pass
                elif value == 'ENDSEC':
                    current_section = None

                if current_handle and current_type in ('TEXT', 'MTEXT', 'LINE'):
                    info[current_handle] = {
                        'type': current_type,
                        'section': current_section,
                        '10': attrs.get('10'),
                        '20': attrs.get('20'),
                        '11': attrs.get('11'),
                        '21': attrs.get('21'),
                        '71': attrs.get('71', 0),
                        '72': attrs.get('72', 0),
                        '73': attrs.get('73', 0),
                        '62': attrs.get('62', 256),
                        '67': attrs.get('67', 0),
                        '210': attrs.get('210', 0.0),
                        '220': attrs.get('220', 0.0),
                        '230': attrs.get('230', 1.0),
                        '1': attrs.get('1', ''),
                    }
                current_type = value
                current_handle = None
                attrs = {}
            elif code == '5':
                current_handle = value
            elif code in ('10', '20', '11', '21', '210', '220', '230'):
                attrs[code] = float(value)
            elif code in ('71', '72', '73', '62', '67'):
                attrs[code] = int(value)
            elif code == '1':
                attrs[code] = value
    except Exception as e:
        print(f"DXF parse error: {e}")
    return info

def get_gpkg_text_info(gpkg_path):
    info = {}
    conn = sqlite3.connect(gpkg_path)
    c = conn.cursor()
    c.execute("SELECT EntityHandle, geom FROM entities WHERE EntityHandle IS NOT NULL")
    rows = c.fetchall()
    for r in rows:
        info[r[0]] = {'geom': r[1]}
    conn.close()
    return info

def analyze_job(job_id):
    job_dir = Path(r"d:\project\LibreDWG\backend\data\jobs") / job_id
    dxf_path = job_dir / "anteen.dxf"
    gpkg_path = job_dir / "anteen.gpkg"
    
    if not dxf_path.exists() or not gpkg_path.exists():
        print("DXF or GPKG not found")
        return

    print(f"Analyzing job: {gpkg_path}")

    # 1. Parse DXF
    dxf_info = parse_dxf_text_info(dxf_path)
    print(f"Parsed {len(dxf_info)} text/line entities from DXF")

    # 2. Parse GPKG
    gpkg_info = get_gpkg_text_info(gpkg_path)
    print(f"Found {len(gpkg_info)} entities in GPKG")

    # 3. Calculate Shift C using LINE entities
    shift_c_x = 0
    shift_c_y = 0
    line_count = 0
    
    print("\n--- Calibration (LINE Entities) ---")
    print(f"{'Handle':<10} {'DXF_Start':<20} {'GPKG_Start_Merc':<25} {'Shift_X':<15} {'Shift_Y':<15}")
    
    for handle, d_info in dxf_info.items():
        if d_info['type'] == 'LINE' and handle in gpkg_info:
            g_blob = gpkg_info[handle]['geom']
            g_lon, g_lat = get_xy_from_wkb(g_blob)
            g_x, g_y = wgs84_to_webmercator(g_lon, g_lat)
            
            d_x = d_info['10']
            d_y = d_info['20']
            
            # Shift = DXF - GPKG
            s_x = d_x - g_x
            s_y = d_y - g_y
            
            # Only print first few
            if line_count < 5:
                print(f"{handle:<10} {f'{d_x:.2f},{d_y:.2f}':<20} {f'{g_x:.2f},{g_y:.2f}':<25} {f'{s_x:.2f}':<15} {f'{s_y:.2f}':<15}")
            
            shift_c_x += s_x
            shift_c_y += s_y
            line_count += 1
            if line_count >= 10: break
            
    if line_count == 0:
        print("No matching LINE entities found for calibration!")
        avg_shift_x = 0
        avg_shift_y = 0
    else:
        avg_shift_x = shift_c_x / line_count
        avg_shift_y = shift_c_y / line_count
        
    print(f"Average Shift (C): X={avg_shift_x:.2f}, Y={avg_shift_y:.2f}")

    # 4. Analyze Text Position
    print("\n--- Text Position Analysis ---")
    print(f"{'Handle':<10} {'Align':<8} {'DXF_10':<18} {'DXF_11':<18} {'GPKG_Raw':<18} {'Rec_GPKG':<18} {'Dist_10':<10}")
    
    # Specific handles to investigate
    targets = ['59768', '5976C', '59770', '59772', '59776', '593FA']
    
    for handle in targets:
        if handle in dxf_info and handle in gpkg_info:
            d_info = dxf_info[handle]
            g_blob = gpkg_info[handle]['geom']
            g_lon, g_lat = get_xy_from_wkb(g_blob)
            g_x, g_y = wgs84_to_webmercator(g_lon, g_lat)
            
            rec_x = g_x + avg_shift_x
            rec_y = g_y + avg_shift_y
            
            d_x10 = d_info['10']
            d_y10 = d_info['20']
            d_x11 = d_info.get('11', 0)
            d_y11 = d_info.get('21', 0)
            
            dist_10 = math.sqrt((rec_x - d_x10)**2 + (rec_y - d_y10)**2)
            
            print(f"{handle:<10} {d_info.get('type',''):<8} {f'{d_x10:.1f},{d_y10:.1f}':<18} {f'{d_x11:.1f},{d_y11:.1f}':<18} {f'{g_x:.1f},{g_y:.1f}':<18} {f'{rec_x:.1f},{rec_y:.1f}':<18} {f'{dist_10:.1f}':<10}")
            print(f"  -> BLOB: {g_blob.hex()[:60]}...")


if __name__ == "__main__":
    analyze_job("21b465d885a54832b5d300e74fda60c9")
