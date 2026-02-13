# -*- coding: utf-8 -*-
"""DWG -> DXF (LibreDWG) -> GeoPackage (GDAL) conversion"""
import subprocess
import uuid
import re
import sqlite3
import os
import shutil
import time
import struct
from pathlib import Path
import math

from app.config import settings

# AutoCAD Color Index (ACI) to Hex mapping (0-255)
# Using a simplified palette for brevity, filling the rest with black
ACI_HEX = [
    "#000000", "#FF0000", "#FFFF00", "#00FF00", "#00FFFF", "#0000FF", "#FF00FF", "#FFFFFF",
    "#414141", "#808080", "#FF0000", "#FFAAAA", "#BD0000", "#BD7E7E", "#810000", "#815656",
    "#680000", "#684545", "#FF3F00", "#FFB5AA", "#BD2E00", "#BD867E", "#811F00", "#815B56",
    "#681900", "#684945", "#FF7F00", "#FFD4AA", "#BD5E00", "#BD9D7E", "#814000", "#816B56",
    "#683400", "#685645", "#FFBF00", "#FFF4AA", "#BD8D00", "#BDB57E", "#816000", "#817C56",
    "#684F00", "#686345", "#00FF00", "#AAFFAA", "#00BD00", "#7EBD7E", "#008100", "#568156",
    "#006800", "#456845", "#00FF7F", "#AAFFD4", "#00BD5E", "#7EBD9D", "#008140", "#56816B",
    "#006834", "#456856", "#00FFFF", "#AAFFFF", "#00BDBD", "#7EBDBD", "#008181", "#568181",
    "#006868", "#456868", "#007FFF", "#AAD4FF", "#005EBD", "#7E9DBD", "#004081", "#566B81",
    "#003468", "#455668", "#0000FF", "#AAAAFF", "#0000BD", "#7E7EBD", "#000081", "#565681",
    "#000068", "#454568", "#7F00FF", "#D4AAFF", "#5E00BD", "#9D7EBD", "#400081", "#6B5681",
    "#340068", "#564568", "#FF00FF", "#FFAAFF", "#BD00BD", "#BDBDBD", "#810081", "#815681",
    "#680068", "#684568", "#FF007F", "#FFAAD4", "#BD005E", "#BD7E9D", "#810040", "#81566B",
    "#680034", "#684556", "#333333", "#505050", "#696969", "#828282", "#BEBEBE", "#FFFFFF"
]
while len(ACI_HEX) < 256:
    ACI_HEX.append("#000000")

# Setup GDAL/PROJ environment variables dynamically
ENV_GDAL = os.environ.copy()
try:
    # Use absolute path based on file location to avoid relative path issues
    # conversion.py is in backend/app/services/
    BACKEND_DIR = Path(__file__).resolve().parents[2]
    GDAL_BIN_DIR = BACKEND_DIR / "tools" / "gdal" / "bin"
    
    if GDAL_BIN_DIR.exists():
        # Add gdal apps to PATH
        gdal_apps = GDAL_BIN_DIR / "gdal" / "apps"
        if gdal_apps.exists():
             ENV_GDAL["PATH"] = str(gdal_apps) + os.pathsep + str(GDAL_BIN_DIR) + os.pathsep + ENV_GDAL.get("PATH", "")
        else:
             ENV_GDAL["PATH"] = str(GDAL_BIN_DIR) + os.pathsep + ENV_GDAL.get("PATH", "")
        
        # GDAL_DATA
        gdal_data = GDAL_BIN_DIR / "gdal-data"
        if gdal_data.exists():
            ENV_GDAL["GDAL_DATA"] = str(gdal_data)
            
        # PROJ_LIB
        proj_lib = GDAL_BIN_DIR / "proj9" / "share"
        if not proj_lib.exists():
            proj_lib = GDAL_BIN_DIR / "proj" / "share"
        
        if proj_lib.exists():
            ENV_GDAL["PROJ_LIB"] = str(proj_lib)
except Exception as e:
    print(f"Error setting up environment: {e}")

def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 300) -> tuple[bool, str]:
    """Execute command, return (success, stderr/stdout)"""
    # DEBUG: Log environment and command
    if cwd:
        try:
            debug_log = cwd / "ogr_debug.log"
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"\n--- Command Execution ---\n")
                f.write(f"Command: {cmd}\n")
                f.write(f"CWD: {cwd}\n")
                f.write(f"GDAL_DATA: {ENV_GDAL.get('GDAL_DATA')}\n")
                f.write(f"PROJ_LIB: {ENV_GDAL.get('PROJ_LIB')}\n")
        except: pass

    try:
        r = subprocess.run(
            cmd,
            cwd=cwd,
            env=ENV_GDAL,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode != 0:
            return False, (r.stderr or r.stdout or f"exit code {r.returncode}")
        return True, r.stdout
    except subprocess.TimeoutExpired:
        return False, "Execution timeout"
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"
    except Exception as e:
        return False, str(e)

def detect_encoding(file_path: Path) -> str:
    """Detect file encoding (utf-8 vs cp936/gb18030/big5/shift_jis)"""
    try:
        # Read a larger chunk (2MB) to ensure we catch non-ASCII characters
        with open(file_path, "rb") as f:
            raw = f.read(2 * 1024 * 1024)
        
        # Try UTF-8 first
        try:
            raw.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            pass
            
        # Try GB18030 (superset of GBK/CP936) - Common in Mainland China
        try:
            raw.decode("gb18030")
            return "gb18030"
        except UnicodeDecodeError:
            pass

        # Try Big5 - Common in Taiwan/Hong Kong
        try:
            raw.decode("big5")
            return "big5"
        except UnicodeDecodeError:
            pass

        # Try Shift-JIS - Common in Japan
        try:
            raw.decode("shift_jis")
            return "shift_jis"
        except UnicodeDecodeError:
            pass

        # Fallback to cp936 (often works for GBK if gb18030 fails slightly differently, or just default)
        return "cp936"
    except Exception:
        return "utf-8"

def repair_dxf_encoding(dxf_path: Path):
    """Convert DXF to UTF-8 and fix header for GDAL (Streaming version for large files)"""
    enc = detect_encoding(dxf_path)
    print(f"Detected encoding for {dxf_path.name}: {enc}")
    
    temp_path = dxf_path.with_name(f"{dxf_path.stem}_temp.dxf")
    
    try:
        # Streaming read/write to handle large files
        with open(dxf_path, "r", encoding=enc, errors="ignore") as f_in, \
             open(temp_path, "w", encoding="utf-8") as f_out:
            
            iterator = iter(f_in)
            try:
                while True:
                    line = next(iterator)
                    # Check for $DWGCODEPAGE
                    # Standard DXF: 
                    # 9
                    # $DWGCODEPAGE
                    # 3
                    # ANSI_xxx
                    
                    if line.strip() == '$DWGCODEPAGE':
                        # Write the variable name lines (assuming previous was 9, but we just write this line)
                        # Actually we need to be careful. The loop just reads lines.
                        # If we found $DWGCODEPAGE, we know the NEXT two lines should be '3' and 'Value'
                        f_out.write(line)
                        
                        try:
                            # Read code 3
                            code_line = next(iterator)
                            f_out.write(code_line)
                            
                            if code_line.strip() == '3':
                                # Read value line
                                val_line = next(iterator)
                                # Replace value with ANSI_1252
                                f_out.write("ANSI_1252\n")
                            else:
                                # Unexpected structure, just write what we read
                                f_out.write(code_line)
                        except StopIteration:
                            break
                    else:
                        f_out.write(line)
            except StopIteration:
                pass
                
        # Replace original with temp
        dxf_path.unlink()
        temp_path.rename(dxf_path)
        
    except Exception as e:
        print(f"Encoding repair failed: {e}")
        if temp_path.exists():
            temp_path.unlink()

def parse_dxf_layers(dxf_path: Path) -> dict[str, str]:
    """Parse LAYER table for colors"""
    layers = {}
    try:
        with open(dxf_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        
        lines = content.splitlines()
        current_layer = None
        in_layer_table = False
        
        for i, line in enumerate(lines):
            line = line.strip()
            if line == "TABLE" and i+2 < len(lines) and lines[i+2].strip() == "LAYER":
                in_layer_table = True
            if line == "ENDTAB":
                in_layer_table = False
            
            if in_layer_table:
                if line == "LAYER":
                    current_layer = None
                if line == "2" and i+1 < len(lines):
                    current_layer = lines[i+1].strip()
                if line == "62" and i+1 < len(lines) and current_layer:
                    try:
                        color_idx = int(lines[i+1].strip())
                        if color_idx < 0: color_idx = -color_idx
                        if 0 <= color_idx < len(ACI_HEX):
                            layers[current_layer] = ACI_HEX[color_idx]
                    except:
                        pass
    except Exception as e:
        print(f"Layer parsing failed: {e}")
    return layers

def extract_dxf_attributes(dxf_path: Path) -> dict[str, dict]:
    """
    Parse DXF to extract attributes for entities.
    Returns dict: Handle -> {
        'type': str,
        'ax': float, 'ay': float,       # Alignment (Text only)
        'dx': float, 'dy': float,       # Geometry Shift (Text only)
        'h': float,                     # Height (Text only)
        'r': float,                     # Rotation (Group 50 or calculated from 11/21)
        'c': str,                       # Color Hex (Group 62)
        'lw': int,                      # Line Weight (Group 370)
        'fill': str                     # Fill Color Hex (Group 62 for HATCH/SOLID)
    }
    """
    results = {}
    try:
        with open(dxf_path, "r", encoding="utf-8", errors="ignore") as f:
            iterator = iter(f)
            
            current_handle = None
            current_type = None
            attrs = {}
            
            def process_entity(type_, attrs):
                data = {'type': type_}
                
                # 1. Color (Group 62)
                # If missing, it's ByLayer (256), which we skip (handled by layer logic)
                # If 0, it's ByBlock
                color_hex = None
                if '62' in attrs:
                    try:
                        c_idx = int(attrs['62'])
                        if c_idx < 0: c_idx = -c_idx # Layer off but color persists
                        if 0 <= c_idx < len(ACI_HEX):
                            color_hex = ACI_HEX[c_idx]
                            data['c'] = color_hex
                    except: pass

                # 2. Line Weight (Group 370)
                # Values: -3 (Standard), -2 (ByBlock), -1 (ByLayer), 0-211 (1/100 mm)
                if '370' in attrs:
                    try:
                        lw = int(attrs['370'])
                        if lw >= 0:
                            data['lw'] = lw
                    except: pass

                # 3. Fill Color for HATCH, SOLID, TRACE
                if type_ in ('HATCH', 'SOLID', 'TRACE'):
                    if color_hex:
                        data['fill'] = color_hex
                        # Ensure line color matches fill for solids to avoid borders
                        if 'c' not in data: data['c'] = color_hex

                # 4. Text Specifics
                if type_ in ('TEXT', 'MTEXT'):
                    # Rotation (Group 50)
                    rotation = 0.0
                    if '50' in attrs:
                        try: rotation = -float(attrs['50']) # Convert CCW to CW for SLD/MapLibre
                        except: pass
                    
                    # MTEXT Direction Vector (Group 11, 21) overrides/supplements rotation
                    # Usually MTEXT rotation is 0 and direction defines angle
                    if type_ == 'MTEXT' and '11' in attrs and '21' in attrs:
                        try:
                            dx = float(attrs['11'])
                            dy = float(attrs['21'])
                            if dx != 0 or dy != 0:
                                # Calculate angle from vector
                                dir_angle = math.degrees(math.atan2(dy, dx))
                                # DXF 50 is relative to X-axis, but if direction vector is present,
                                # it defines the X-axis. 
                                # Usually if 11/21 are present, they define the rotation.
                                # Let's use the direction vector angle.
                                # Convert CCW to CW for SLD/MapLibre
                                rotation = -dir_angle
                        except: pass
                        
                    data['r'] = rotation
                        
                    # Height (Group 40)
                    if '40' in attrs:
                        try: data['h'] = float(attrs['40'])
                        except: pass
                        
                    # Alignment
                    ax, ay = 0.0, 0.0
                    off_x, off_y = 0.0, 0.0
                    
                    if type_ == 'MTEXT':
                        # Group 71: Attachment point
                        ap = int(attrs.get('71', 1))
                        if ap in (1, 2, 3): ay = 1.0 # Top
                        elif ap in (4, 5, 6): ay = 0.5 # Middle
                        else: ay = 0.0 # Bottom
                        
                        if ap in (1, 4, 7): ax = 0.0 # Left
                        elif ap in (2, 5, 8): ax = 0.5 # Center
                        else: ax = 1.0 # Right
                        
                    elif type_ == 'TEXT':
                        h = int(attrs.get('72', 0))
                        v = int(attrs.get('73', 0))
                        
                        if h == 0: ax = 0.0
                        elif h == 1: ax = 0.5
                        elif h == 2: ax = 1.0
                        elif h == 4: ax = 0.5
                        else: ax = 0.5
                        
                        if v == 3: ay = 1.0
                        elif v == 2: ay = 0.5
                        elif v == 1: ay = 0.0
                        else: ay = 0.0
                        
                        if h == 4: ax, ay = 0.5, 0.5
                        
                        # Geometry Shift
                        if h != 0 or v != 0:
                            g10x = float(attrs.get('10', 0.0))
                            g10y = float(attrs.get('20', 0.0))
                            g11x = float(attrs.get('11', 0.0))
                            g11y = float(attrs.get('21', 0.0))
                            off_x = g11x - g10x
                            off_y = g11y - g10y
                            
                    data['ax'] = ax
                    data['ay'] = ay
                    if off_x != 0 or off_y != 0:
                        data['dx'] = off_x
                        data['dy'] = off_y
                        
                return data

            try:
                while True:
                    code = next(iterator).strip()
                    value = next(iterator).strip()
                    
                    if code == '0':
                        if current_handle:
                            res = process_entity(current_type, attrs)
                            if res: results[current_handle] = res
                        
                        current_type = value
                        current_handle = None
                        attrs = {}
                        
                        if value == 'EOF':
                            break
                            
                    elif code == '5':
                        current_handle = value
                    elif code in ('10', '20', '11', '21', '40', '50'):
                        try: attrs[code] = float(value) # Keep as float for coords/angles
                        except: pass
                    elif code in ('62', '71', '72', '73', '370'):
                        try: attrs[code] = int(value) # Keep as int for enums
                        except: pass
                        
            except StopIteration:
                pass
                
    except Exception as e:
        print(f"Attribute extraction failed: {e}")
        
    return results

def apply_geometry_shift(blob, dx, dy):
    """Shift GeoPackage geometry blob by dx, dy"""
    if not blob: return blob
    try:
        # GeoPackage Header
        if blob[:2] != b'GP': return blob
        
        flags = blob[3]
        envelope_indicator = (flags >> 1) & 0x07
        
        header_len = 8 
        if envelope_indicator == 1: header_len += 32
        elif envelope_indicator == 2: header_len += 48
        elif envelope_indicator == 3: header_len += 64
        elif envelope_indicator == 4: header_len += 80
        
        # WKB Start
        wkb_start = header_len
        if len(blob) < wkb_start + 21: return blob
        
        byte_order = blob[wkb_start] # 0=Big, 1=Little
        endian = '>' if byte_order == 0 else '<'
        
        # Geometry Type (4 bytes) - check if it looks like a point
        # We assume X and Y are always at offset 5 for Points
        
        # X starts at wkb_start + 5
        x_offset = wkb_start + 5
        x = struct.unpack(endian + 'd', blob[x_offset:x_offset+8])[0]
        y = struct.unpack(endian + 'd', blob[x_offset+8:x_offset+16])[0]
        
        new_x = x + dx
        new_y = y + dy
        
        new_x_bytes = struct.pack(endian + 'd', new_x)
        new_y_bytes = struct.pack(endian + 'd', new_y)
        
        # Reconstruct
        new_blob = blob[:x_offset] + new_x_bytes + new_y_bytes + blob[x_offset+16:]
        return new_blob
    except:
        return blob

def convert_dwg_to_gpkg(dwg_path: Path, output_dir: Path, progress_callback=None) -> tuple[bool, Path | None, str]:
    job_id = output_dir.name
    temp_dwg = output_dir / f"temp_{job_id}.dwg"
    dxf_path = output_dir / f"{dwg_path.stem}.dxf"
    gpkg_path = output_dir / f"{dwg_path.stem}.gpkg"
    
    if progress_callback: progress_callback(10, "正在初始化...")
    
    # 1. Copy to temp ASCII name if needed
    try:
        shutil.copy2(dwg_path, temp_dwg)
    except Exception as e:
        return False, None, f"创建临时文件失败: {e}"
        
    # 2. DWG -> DXF
    if progress_callback: progress_callback(20, "正在将 DWG 转换为 DXF...")
    # Use -y to overwrite if exists
    cmd_dxf = [settings.dwg2dxf_cmd, "-y", "-o", str(dxf_path), str(temp_dwg)]
    ok, err = _run(cmd_dxf, cwd=output_dir)
    if not ok:
        if temp_dwg.exists(): temp_dwg.unlink()
        return False, None, f"LibreDWG 转换失败: {err}"
        
    if temp_dwg.exists(): temp_dwg.unlink()
    
    # 3. Repair Encoding (Stream processing)
    if progress_callback: progress_callback(40, "正在修复编码...")
    try:
        repair_dxf_encoding(dxf_path)
    except Exception as e:
        print(f"Encoding repair warning: {e}")
    
    # 4. Parse Layers
    if progress_callback: progress_callback(50, "正在解析图层...")
    layer_colors = parse_dxf_layers(dxf_path)
    
    # 5. DXF -> GPKG
    if progress_callback: progress_callback(60, "正在将 DXF 转换为 GeoPackage...")
    
    # Define ogr2ogr command
    try:
        BACKEND_DIR = Path(__file__).resolve().parents[2]
        ogr2ogr_cmd = BACKEND_DIR / "tools" / "gdal" / "bin" / "gdal" / "apps" / "ogr2ogr.exe"
        if not ogr2ogr_cmd.exists():
             # Fallback
             ogr2ogr_cmd = BACKEND_DIR / "tools" / "gdal" / "bin" / "ogr2ogr.exe"
    except:
        ogr2ogr_cmd = "ogr2ogr"

    cmd_gpkg = [
        str(ogr2ogr_cmd),
        "--config", "DXF_ENCODING", "UTF-8",
        "--config", "DXF_MERGE_BLOCK_GEOMETRIES", "FALSE",
        "--config", "DXF_INLINE_BLOCKS", "TRUE",
        "--config", "DXF_ATTRIBUTES", "TRUE",
        "-f", "GPKG",
        # Do not force SRS here to allow large coordinates (e.g. millimeters) to be imported
        # We will normalize/project later
        str(gpkg_path),
        str(dxf_path),
        "-skipfailures",
        "-lco", "GEOMETRY_NAME=geom"
    ]

    # DEBUG: Log environment and command
    try:
        debug_log = output_dir / "ogr_debug.log"
        with open(debug_log, "w", encoding="utf-8") as f:
            f.write(f"SRS: {settings.target_srs}\n")
            f.write(f"GDAL_DATA: {ENV_GDAL.get('GDAL_DATA')}\n")
            f.write(f"PROJ_LIB: {ENV_GDAL.get('PROJ_LIB')}\n")
            f.write(f"PATH: {ENV_GDAL.get('PATH')}\n")
            f.write(f"Command: {cmd_gpkg}\n")
    except: pass
    
    # Ensure fresh start for GPKG
    if gpkg_path.exists():
        try:
            gpkg_path.unlink()
        except Exception as e:
            return False, None, f"Failed to remove existing GPKG: {e}"

    # Run conversion with logging
    # Increase timeout to 1 hour for large/complex drawings
    ok, err = _run(cmd_gpkg, cwd=output_dir, timeout=3600)
    
    # Check if we got entities
    if ok and check_gpkg_count(gpkg_path) == 0:
         print("Initial conversion resulted in 0 entities. Retrying without inline blocks...")
         # Retry with DXF_INLINE_BLOCKS=FALSE (sometimes better for messy blocks)
         cmd_retry = list(cmd_gpkg)
         # Find and replace config
         for i, arg in enumerate(cmd_retry):
             if arg == "DXF_INLINE_BLOCKS":
                 cmd_retry[i+1] = "FALSE"
         
         ok, err = _run(cmd_retry, cwd=output_dir, timeout=3600)

    # DEBUG: Log result
    try:
        with open(output_dir / "ogr_debug.log", "a", encoding="utf-8") as f:
            f.write(f"\nResult: {ok}\nError/Output: {err}\n")
    except: pass
    
    if not ok:
        return False, None, f"GDAL conversion failed: {err}"
        
    # 6. Post-processing
    if progress_callback: progress_callback(80, "正在处理数据...")
    try:
        conn = sqlite3.connect(gpkg_path)
        conn.text_factory = lambda b: b.decode(errors="ignore")
        
        # Mock SpatiaLite functions
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
        
        # Create indexes for performance
        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_entities_handle ON entities(EntityHandle)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_entities_layer ON entities(Layer)")
        except: pass
        
        c.execute("PRAGMA table_info(entities)")
        cols = [r[1] for r in c.fetchall()]
        
        # Add basic style columns
        if 'line_color' not in cols:
            c.execute("ALTER TABLE entities ADD COLUMN line_color TEXT")
        if 'fill_color' not in cols:
            c.execute("ALTER TABLE entities ADD COLUMN fill_color TEXT")
        if 'rotation' not in cols:
            c.execute("ALTER TABLE entities ADD COLUMN rotation REAL")
        if 'line_width' not in cols:
            c.execute("ALTER TABLE entities ADD COLUMN line_width REAL")
            
        # Add text specific style columns
        text_cols = {
            'text_font': 'TEXT',
            'text_size': 'REAL',
            'text_color': 'TEXT',
            'text_angle': 'REAL',
            'text_content': 'TEXT',
            'anchor_x': 'REAL',
            'anchor_y': 'REAL'
        }
        for col_name, col_type in text_cols.items():
            if col_name not in cols:
                c.execute(f"ALTER TABLE entities ADD COLUMN {col_name} {col_type}")
        
        # 7. Parse DXF Attributes (Alignments, Rotation, Color, Width)
        if progress_callback: progress_callback(70, "正在解析实体属性(对齐/旋转/颜色/线宽)...")
        try:
            attrs_map = extract_dxf_attributes(dxf_path)
            if attrs_map:
                # Prepare data
                anchors = []
                shifts = []
                sizes = []
                rotations = []
                text_colors = []
                line_colors = []
                fill_colors = []
                line_widths = []
                
                for k, v in attrs_map.items():
                    # Anchors
                    if 'ax' in v:
                        anchors.append((v['ax'], v['ay'], k))
                    
                    # Shifts
                    if 'dx' in v:
                        shifts.append((v['dx'], v['dy'], k))
                        
                    # Sizes
                    if 'h' in v and v['h'] > 0:
                        sizes.append((v['h'], k))
                        
                    # Rotations
                    if 'r' in v:
                        rotations.append((v['r'], k))
                        
                    # Colors
                    if 'c' in v:
                        color = v['c']
                        if color == "#000000": color = "#FFFFFF"
                        
                        if v['type'] in ('TEXT', 'MTEXT'):
                            text_colors.append((color, k))
                        else:
                            line_colors.append((color, k))
                            
                    # Fill Colors (Hatch/Solid)
                    if 'fill' in v:
                        fill = v['fill']
                        # Handle colors for Black Background (Dark Mode)
                        # If fill is black (#000000), convert to white (#FFFFFF) to be visible
                        if fill == "#000000": 
                            fill = "#FFFFFF"
                        # If fill is white (#FFFFFF), keep it white
                        elif fill == "#FFFFFF":
                            pass
                             
                        fill_colors.append((fill, k))
                        
                    # Line Weights
                    if 'lw' in v:
                        line_widths.append((v['lw'], k))

                # Update Anchors
                if anchors:
                    c.executemany(
                        "UPDATE entities SET anchor_x=?, anchor_y=? WHERE EntityHandle=?", 
                        anchors
                    )
                
                # Apply geometry shifts
                if shifts:
                    print(f"Applying geometry shift to {len(shifts)} text entities...")
                    try:
                        c.execute("CREATE TEMPORARY TABLE IF NOT EXISTS text_shifts (handle TEXT PRIMARY KEY, dx REAL, dy REAL)")
                        c.execute("DELETE FROM text_shifts")
                        c.executemany("INSERT INTO text_shifts (dx, dy, handle) VALUES (?, ?, ?)", shifts)
                        
                        c.execute("""
                            SELECT e.EntityHandle, e.geom, s.dx, s.dy
                            FROM entities e
                            JOIN text_shifts s ON e.EntityHandle = s.handle
                            WHERE e.geom IS NOT NULL
                        """)
                        
                        geom_updates = []
                        rows = c.fetchall()
                        for handle, blob, dx, dy in rows:
                            new_blob = apply_geometry_shift(blob, dx, dy)
                            if new_blob != blob:
                                geom_updates.append((new_blob, handle))
                                
                        if geom_updates:
                            c.executemany("UPDATE entities SET geom=? WHERE EntityHandle=?", geom_updates)
                            
                        c.execute("DROP TABLE text_shifts")
                        
                    except Exception as e:
                        print(f"Batch geometry shift error: {e}")
                        for dx, dy, handle in shifts:
                            try:
                                c.execute("SELECT geom FROM entities WHERE EntityHandle=?", (handle,))
                                row = c.fetchone()
                                if row and row[0]:
                                    new_blob = apply_geometry_shift(row[0], dx, dy)
                                    if new_blob != row[0]:
                                        c.execute("UPDATE entities SET geom=? WHERE EntityHandle=?", (new_blob, handle))
                            except: pass

                # Update Text Size
                if sizes:
                    try:
                        c.execute("CREATE TEMPORARY TABLE IF NOT EXISTS text_sizes (handle TEXT PRIMARY KEY, size REAL)")
                        c.execute("DELETE FROM text_sizes")
                        c.executemany("INSERT INTO text_sizes (size, handle) VALUES (?, ?)", sizes)
                        
                        try:
                            c.execute("""
                                UPDATE entities 
                                SET text_size = text_sizes.size 
                                FROM text_sizes 
                                WHERE entities.EntityHandle = text_sizes.handle
                            """)
                        except:
                            c.execute("""
                                UPDATE entities 
                                SET text_size = (SELECT size FROM text_sizes WHERE handle = entities.EntityHandle)
                                WHERE EXISTS (SELECT 1 FROM text_sizes WHERE handle = entities.EntityHandle)
                            """)
                            
                        c.execute("DROP TABLE text_sizes")
                    except Exception as e:
                        print(f"Text size batch update error: {e}")
                        try:
                             c.executemany("UPDATE entities SET text_size=? WHERE EntityHandle=?", sizes)
                        except: pass

                # Update Rotations (New)
                if rotations:
                     try:
                         c.executemany("UPDATE entities SET text_angle=? WHERE EntityHandle=?", rotations)
                         c.executemany("UPDATE entities SET rotation=COALESCE(rotation, ?) WHERE EntityHandle=?", rotations)
                     except Exception as e:
                         print(f"Rotation update error: {e}")
                     
                # Update Colors (New)
                if text_colors:
                    try:
                        c.executemany("UPDATE entities SET text_color=? WHERE EntityHandle=?", text_colors)
                    except Exception as e:
                        print(f"Text color update error: {e}")
                    
                if line_colors:
                    try:
                        c.executemany("UPDATE entities SET line_color=? WHERE EntityHandle=?", line_colors)
                    except Exception as e:
                        print(f"Line color update error: {e}")
                        
                # Update Fill Colors (New)
                if fill_colors:
                    try:
                        c.executemany("UPDATE entities SET fill_color=? WHERE EntityHandle=?", fill_colors)
                    except Exception as e:
                         print(f"Fill color update error: {e}")
                         
                # Update Line Widths (New)
                if line_widths:
                    try:
                        c.executemany("UPDATE entities SET line_width=? WHERE EntityHandle=?", line_widths)
                    except Exception as e:
                        print(f"Line width update error: {e}")

        except Exception as e:
            print(f"Attribute parsing warning: {e}")
            
        # Remove text from Hatch entities (often pattern names like SOLID, HONEY)
        # We do this early to ensure it runs even if later steps fail
        if 'Text' in cols:
             try:
                 # Aggressively remove known pattern names (case insensitive check via UPPER)
                 c.execute("UPDATE entities SET Text = NULL WHERE UPPER(Text) IN ('SOLID', 'HONEY')")
                 if 'SubClasses' in cols:
                     c.execute("UPDATE entities SET Text = NULL WHERE SubClasses LIKE '%AcDbHatch%'")
             except Exception as e:
                 print(f"Hatch text cleanup error: {e}")
                 
        # Additional cleanup for attribute fields that might contain hatch pattern names
        # Check for any column that might hold the pattern name if 'Text' was empty but now populated
        # (Though usually it's 'Text')

        # Update colors and rotation from styles
        updates = []
        if 'style' in cols:
            try:
                # Include existing text_size in selection to preserve it if style doesn't override
                c.execute("SELECT rowid, style, text_size FROM entities WHERE style IS NOT NULL")
                rows = c.fetchall()
                for rid, style, existing_size in rows:
                    l_c = None
                    f_c = None
                    rot = None
                    
                    t_font = None
                    t_size = existing_size
                    t_color = None
                    t_angle = None
                    t_text = None
                    
                    if "PEN(" in style:
                        try:
                            p = style.split("PEN(")[1].split(")")[0]
                            for kv in p.split(","):
                                if kv.startswith("c:"): 
                                    l_c = kv[2:]
                                    # Strip alpha if present (8 chars hex)
                                    if l_c.startswith('#') and len(l_c) > 7:
                                        l_c = l_c[:7]
                                    # Remap Black to White for black background
                                    if l_c.lower() == "#000000":
                                        l_c = "#FFFFFF"
                        except: pass
                    if "BRUSH(" in style:
                        try:
                            p = style.split("BRUSH(")[1].split(")")[0]
                            for kv in p.split(","):
                                if kv.startswith("fc:"): 
                                    f_c = kv[3:]
                                    # Strip alpha if present (8 chars hex)
                                    if f_c.startswith('#') and len(f_c) > 7:
                                        f_c = f_c[:7]
                                    # Remap Black to White for black background (though fill usually isn't black)
                                    if f_c.lower() == "#000000":
                                        f_c = "#FFFFFF"
                        except: pass
                    if "LABEL(" in style:
                        try:
                            # Parse LABEL style using regex to handle quotes safely
                            # Example: LABEL(f:"Arial",t:"+0,000",s:250g,w:90,p:7,c:#00000000)
                            p_start = style.find("LABEL(") + 6
                            p_end = style.rfind(")")
                            if p_start > 5 and p_end > p_start:
                                content = style[p_start:p_end]
                                matches = re.findall(r'([a-zA-Z]+):(".*?"|[^,]+)', content)
                                for k, v in matches:
                                    if v.startswith('"') and v.endswith('"'):
                                        v = v[1:-1]
                                    
                                    if k == 'f': t_font = v
                                    elif k == 's': 
                                        try:
                                            # remove unit suffix if any (g=ground, p=points, m=mm, etc)
                                            val_str = v.rstrip("gpm")
                                            t_size = float(val_str)
                                        except: pass
                                    elif k == 'c': 
                                        t_color = v
                                        if t_color.startswith('#') and len(t_color) > 7:
                                            t_color = t_color[:7]
                                        if t_color.lower() == "#000000":
                                            t_color = "#FFFFFF"
                                    elif k == 'a': 
                                        try: t_angle = float(v)
                                        except: pass
                                    elif k == 't': t_text = v
                                    elif k == 'p': pass # priority/position
                                    
                                # If we found label attributes, set generic ones too if missing
                                if t_color and not l_c: l_c = t_color
                                if t_angle is not None: rot = t_angle
                        except Exception as e:
                            # print(f"Label parse error: {e}")
                            pass

                    if any(x is not None for x in [l_c, f_c, rot, t_font, t_size, t_color, t_angle, t_text]):
                        updates.append((l_c, f_c, rot, t_font, t_size, t_color, t_angle, t_text, rid))
            except Exception as e:
                print(f"Style processing error: {e}")
                
        if updates:
            try:
                c.executemany("""
                    UPDATE entities SET 
                        line_color=COALESCE(?, line_color), 
                        fill_color=COALESCE(?, fill_color), 
                        rotation=COALESCE(?, rotation),
                        text_font=COALESCE(?, text_font),
                        text_size=COALESCE(?, text_size),
                        text_color=COALESCE(?, text_color),
                        text_angle=COALESCE(?, text_angle),
                        text_content=COALESCE(?, text_content)
                    WHERE rowid=?
                """, updates)
            except Exception as e:
                print(f"Style update error: {e}")
        
        # Update layer colors
        if 'Layer' in cols:
            for layer, color in layer_colors.items():
                # Remap Black to White for layer colors too
                if color and color.lower() == "#000000":
                    color = "#FFFFFF"
                    
                # Update if line_color is NULL, OR if it's White/Black (likely default) and layer has a specific color
                # This helps recover "ByLayer" colors where OGR_STYLE defaulted to black
                c.execute("""
                    UPDATE entities 
                    SET line_color = ? 
                    WHERE Layer = ? 
                    AND (line_color IS NULL OR line_color IN ('#FFFFFF', '#000000'))
                """, (color, layer))
                
        # Force Black to White cleanup globally (run AFTER layer updates to catch ByLayer blacks)
        try:
            c.execute("UPDATE entities SET line_color='#FFFFFF' WHERE line_color='#000000'")
            c.execute("UPDATE entities SET text_color='#FFFFFF' WHERE text_color='#000000'")
            c.execute("UPDATE entities SET line_color=text_color WHERE line_color IS NULL AND text_color IS NOT NULL")
        except Exception as e:
            print(f"Color cleanup error: {e}")

        conn.commit()
    
        # Check count
        try:
            c.execute("SELECT COUNT(*) FROM entities")
            count = c.fetchone()[0]
            print(f"Total entities in GPKG: {count}")
            if count == 0:
                print("Warning: No entities found in converted GPKG!")
        except: pass

        conn.close()
    except Exception as e:
        print(f"Post-processing error: {e}")
    
    # Sanitize coordinates (remove garbage)
    if progress_callback: progress_callback(85, "Sanitizing coordinates...")
    try:
        sanitize_coordinates(gpkg_path)
    except Exception as e:
        print(f"Sanitization warning: {e}")

    # Normalize coordinates
    if progress_callback: progress_callback(90, "Normalizing coordinates...")
    try:
        normalize_coordinates(gpkg_path)
    except Exception as e:
        print(f"Normalization warning: {e}")
        
    # Force Repack GPKG to fix Spatial Index (RTree) after direct SQLite modifications
    # This ensures GeoServer can properly query the data
    try:
        if progress_callback: progress_callback(95, "Repacking GeoPackage...")
        repack_gpkg(gpkg_path)
    except Exception as e:
        print(f"Repack warning: {e}")

    if progress_callback: progress_callback(100, "Done")
    return True, gpkg_path, ""

def check_gpkg_count(gpkg_path: Path) -> int:
    try:
        conn = sqlite3.connect(gpkg_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM entities")
        count = c.fetchone()[0]
        conn.close()
        return count
    except:
        return 0

def repack_gpkg(gpkg_path: Path):
    """Repack GeoPackage to fix RTree and optimize"""
    temp_repacked = gpkg_path.parent / (gpkg_path.stem + "_repacked.gpkg")
    if temp_repacked.exists():
        try: temp_repacked.unlink()
        except: pass

    cmd_repack = [
        settings.ogr2ogr_cmd,
        "-f", "GPKG",
        str(temp_repacked),
        str(gpkg_path),
        "-nln", "entities",
        "-lco", "GEOMETRY_NAME=geom",
        "-nlt", "GEOMETRY",
        "-dim", "XY"
    ]
    
    ok, out = _run(cmd_repack)
    
    # Verify count before overwriting
    if ok and temp_repacked.exists():
        count = check_gpkg_count(temp_repacked)
        if count == 0:
            print("Repack resulted in empty GPKG, keeping original.")
            return False

        for i in range(5):
            try:
                shutil.move(temp_repacked, gpkg_path)
                return True
            except Exception as e:
                time.sleep(1)
        print("Could not overwrite original GPKG after repack")
    else:
        print(f"Repack failed: {out}")
    return False

def sanitize_coordinates(gpkg_path: Path) -> bool:
    """Filter out entities with extreme coordinates (likely garbage)"""
    # 1e20 is large enough to cover the observable universe in meters, so anything larger is definitely garbage
    limit = 1e20 
    temp_sane = gpkg_path.parent / (gpkg_path.stem + "_sane.gpkg")
    if temp_sane.exists():
        try: temp_sane.unlink()
        except: pass

    # Use SQLite dialect to filter by bounding box
    # We rely on ST_MinX etc. being available in the GDAL SQLite dialect
    sql = f"SELECT * FROM entities WHERE ST_MinX(geom) > {-limit} AND ST_MaxX(geom) < {limit} AND ST_MinY(geom) > {-limit} AND ST_MaxY(geom) < {limit}"
    
    cmd_sanitize = [
        settings.ogr2ogr_cmd,
        "-f", "GPKG",
        str(temp_sane),
        str(gpkg_path),
        "-dialect", "SQLite",
        "-sql", sql,
        "-nln", "entities",
        "-lco", "GEOMETRY_NAME=geom",
        "-nlt", "GEOMETRY",
        "-dim", "XY"
    ]
    
    ok, out = _run(cmd_sanitize)
    
    if ok and temp_sane.exists():
        # Replace original
        count = check_gpkg_count(temp_sane)
        if count == 0:
            print("Sanitization resulted in empty GPKG, keeping original.")
            return False

        for i in range(5):
            try:
                shutil.move(temp_sane, gpkg_path)
                return True
            except Exception as e:
                time.sleep(1)
        else:
             print("Could not overwrite original GPKG after sanitization")
             return False
    else:
        # If SQLite dialect fails, try fallback or just ignore
        print(f"Sanitization failed (possibly no SpatiaLite): {out}")
        return False

def get_gpkg_bbox(gpkg_path: Path) -> tuple[bool, list[float] | None]:
    try:
        conn = sqlite3.connect(gpkg_path)
        c = conn.cursor()
        c.execute("SELECT min_x, min_y, max_x, max_y FROM gpkg_contents WHERE table_name='entities'")
        row = c.fetchone()
        conn.close()
        if row and all(x is not None for x in row):
            return True, list(row)
        return False, None
    except Exception:
        return False, None

def get_robust_bbox(gpkg_path: Path) -> tuple[float, float, float, float, float, float]:
    """
    Get robust bounding box using percentiles to ignore outliers.
    Returns (min_x, max_x, min_y, max_y, robust_width, robust_height)
    """
    try:
        csv_path = gpkg_path.with_suffix(".bbox.csv")
        if csv_path.exists(): csv_path.unlink()
        
        cmd = [
            settings.ogr2ogr_cmd,
            "-f", "CSV",
            str(csv_path),
            str(gpkg_path),
            "-dialect", "SQLite",
            "-sql", "SELECT ST_MinX(geom) as x1, ST_MaxX(geom) as x2, ST_MinY(geom) as y1, ST_MaxY(geom) as y2 FROM entities"
        ]
        
        ok, out = _run(cmd)
        if not ok or not csv_path.exists():
            return None
            
        x_vals = []
        y_vals = []
        
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                next(f, None)
                for line in f:
                    parts = line.strip().split(',')
                    if len(parts) >= 4:
                        try:
                            x1 = float(parts[0].strip('"'))
                            x2 = float(parts[1].strip('"'))
                            y1 = float(parts[2].strip('"'))
                            y2 = float(parts[3].strip('"'))
                            x_vals.extend([x1, x2])
                            y_vals.extend([y1, y2])
                        except: pass
        except: pass
            
        if csv_path.exists(): 
            try: csv_path.unlink()
            except: pass
        
        if not x_vals or not y_vals:
            return None
            
        x_vals.sort()
        y_vals.sort()
        n = len(x_vals)
        if n == 0: return None
        
        p10 = int(n * 0.1)
        p90 = int(n * 0.9)
        rx1, rx2 = x_vals[p10], x_vals[p90]
        ry1, ry2 = y_vals[p10], y_vals[p90]
        robust_w = rx2 - rx1
        robust_h = ry2 - ry1
        
        p01 = int(n * 0.01)
        p99 = int(n * 0.99)
        sx1, sx2 = x_vals[p01], x_vals[p99]
        sy1, sy2 = y_vals[p01], y_vals[p99]
        
        if robust_w > 0 and (sx2 - sx1) > robust_w * 20:
            mid_x = (rx1 + rx2) / 2
            sx1 = max(sx1, mid_x - robust_w * 10)
            sx2 = min(sx2, mid_x + robust_w * 10)
            
        if robust_h > 0 and (sy2 - sy1) > robust_h * 20:
            mid_y = (ry1 + ry2) / 2
            sy1 = max(sy1, mid_y - robust_h * 10)
            sy2 = min(sy2, mid_y + robust_h * 10)

        return (sx1, sx2, sy1, sy2, robust_w, robust_h)

    except Exception:
        return None

def normalize_coordinates(gpkg_path: Path) -> bool:
    """Check if coordinates are out of WGS84 bounds and shift to (0,0) if needed."""
    
    # 1. Get Robust Stats
    stats = get_robust_bbox(gpkg_path)
    
    # Fallback if robust failed
    if not stats:
        ok, bbox = get_gpkg_bbox(gpkg_path)
        if not ok or not bbox: return False
        min_x, min_y, max_x, max_y = bbox
        sx1, sx2, sy1, sy2 = min_x, max_x, min_y, max_y
        robust_w, robust_h = max_x - min_x, max_y - min_y
        cx, cy = (min_x + max_x) / 2, (min_y + max_y) / 2
    else:
        sx1, sx2, sy1, sy2, robust_w, robust_h = stats
        # Use center of Safe Bounds (clamped) as the center
        cx = (sx1 + sx2) / 2
        cy = (sy1 + sy2) / 2
        print(f"Robust Stats: W={robust_w:.2f}, H={robust_h:.2f}, Center=({cx:.2f}, {cy:.2f})")

    # If already normalized
    if -200 <= sx1 and sx2 <= 200 and -100 <= sy1 and sy2 <= 100:
        return True
        
    print(f"Normalizing... Center:({cx:.2f},{cy:.2f})")
    
    scale_factor = 1.0
    # Determine scale factor based on ROBUST dimensions
    if robust_w > 20000000 or robust_h > 20000000:
        scale_factor = 0.001
        print(f"Detected huge dimensions (Robust W:{robust_w:.0f}), scaling by 0.001...")
    
    # Check for Text Unit Mismatch (e.g. Geometry in Meters, Text in Millimeters)
    text_scale_factor = scale_factor
    try:
        conn = sqlite3.connect(gpkg_path)
        c = conn.cursor()
        c.execute("PRAGMA table_info(entities)")
        cols_info = {r[1] for r in c.fetchall()}
        
        if 'text_size' in cols_info:
            # Check Max Text Size
            c.execute("SELECT MAX(text_size) FROM entities WHERE text_size IS NOT NULL")
            row = c.fetchone()
            max_text = float(row[0]) if row and row[0] is not None else 0.0

            # Check Median Text Size (Approximation via middle row)
            c.execute("SELECT COUNT(*) FROM entities WHERE text_size IS NOT NULL")
            count_row = c.fetchone()
            count = count_row[0] if count_row else 0
            
            median_text = 0.0
            if count > 0:
                offset = count // 2
                c.execute(f"SELECT text_size FROM entities WHERE text_size IS NOT NULL ORDER BY text_size LIMIT 1 OFFSET {offset}")
                med_row = c.fetchone()
                if med_row and med_row[0] is not None:
                    median_text = float(med_row[0])

            # Heuristic Logic
            # 1. Median Text > 50: Strong indicator of unit mismatch (mm vs m).
            # 2. Max Text > 50% of Width: Strong indicator of huge labels.
            
            should_scale = False
            reason = ""

            if robust_w > 0:
                ratio_max = (max_text * scale_factor) / (robust_w * scale_factor)
                ratio_med = (median_text * scale_factor) / (robust_w * scale_factor)
                
                # Smart Heuristic Logic
                # We want to distinguish between:
                # 1. Unit Mismatch (e.g. 3000mm text -> 3m). Scaling is GOOD.
                # 2. Big Text on Large Map (e.g. 300m text on 30km map). Scaling -> 0.3m (Invisible). Scaling is BAD.
                # 3. Huge Text on Small Map (e.g. 300m text on 500m map). Scaling -> 0.3m (Tiny but better than covering map). Scaling is NECESSARY.
                
                median_val = median_text * scale_factor
                scaled_median = median_val * 0.001
                max_val = max_text * scale_factor
                
                if robust_w > 0:
                    ratio_median = median_val / robust_w
                    ratio_max = max_val / robust_w
                else:
                    ratio_median = 0
                    ratio_max = 0
                
                # Only consider scaling if Median Text > 50 (Strong indicator of non-meter units like mm)
                if median_val > 50:
                    # Case A: Scaling results in a "Normal" size (>= 0.5m)
                    # e.g. 5000 -> 5m. 600 -> 0.6m.
                    # This confirms it was likely mm.
                    if scaled_median >= 0.5:
                        should_scale = True
                        reason = f"Median ({median_val:.2f}) > 50 and Scaled ({scaled_median:.2f}m) is visible (>=0.5m)"
                    
                    # Case B: Scaling results in "Tiny" size (< 0.5m), BUT Original is "Huge" (> 10% of map)
                    # e.g. 300 on 100m map. Ratio 3.0. Scaled 0.3m.
                    # 0.3m is small, but 300m covers the map. We prefer small.
                    elif ratio_median > 0.1:
                        should_scale = True
                        reason = f"Median ({median_val:.2f}) is Huge relative to map ({ratio_median:.1%}), despite becoming small ({scaled_median:.2f}m)"
                        
                    # Case C: Scaling results in "Tiny" size, AND Original is "Acceptable" (< 10% of map)
                    # e.g. 300 on 30,000m map. Ratio 1%. Scaled 0.3m.
                    # 300m text is big but readable. 0.3m is invisible.
                    # We KEEP the original.
                    else:
                        should_scale = False
                        print(f"Text scaling skipped: Median ({median_val:.2f}) would become invisible ({scaled_median:.2f}m) and fits map ({ratio_median:.1%}).")
                
                else:
                    # Median <= 50. Likely Meters.
                    # However, if Max Text is ABSURDLY huge (e.g. > 80% of map), it's likely an outlier or unit mismatch affecting titles.
                    # e.g. Map width 100m. Title "System Diagram" is 300 units (300mm -> 0.3m).
                    # Interpreted as 300m. Covers map 3x.
                    if ratio_max > 0.8:
                         should_scale = True
                         reason = f"Max Text ({max_val:.2f}) covers map ({ratio_max:.1%}) -> Forced Scale"
                    else:
                         should_scale = False

                if should_scale:
                    proposed_scale = scale_factor * 0.001
                    
                    # Safeguard: Don't scale if result becomes invisible (< 0.05m = 5cm)
                    # Unless original was truly huge (> 50m/units) which implies it MUST be scaled
                    # If text is 80 (mm) -> 0.08m (8cm). OK.
                    # If text is 20 (m) -> 0.02m (2cm). Too small? 
                    # But 20m text is huge. If we scale 20 -> 0.02, it disappears.
                    # If we don't scale 20 -> 20m. It covers map.
                    # So if text > 50, we assume mm.
                    # If text < 50, we rely on safeguard.
                    
                    # Check if SCALED median text would be at least 1cm (0.01m)
                    # 10mm text -> 0.01m.
                    
                    scaled_max = max_text * proposed_scale
                    
                    if scaled_max < 0.01: # < 1cm
                         print(f"Text scaling skipped: Resulting text too small (Max {scaled_max:.4f}m). Reason: {reason}")
                    else:
                         print(f"Detected text unit mismatch. {reason}. Scaling text by 0.001...")
                         text_scale_factor = proposed_scale

        conn.close()
    except Exception as e:
        print(f"Error checking text size: {e}")

    # Get columns to avoid "geom, *" ambiguity and handle text scaling
    cols_str = "*"
    try:
        conn = sqlite3.connect(gpkg_path)
        c = conn.cursor()
        c.execute("PRAGMA table_info(entities)")
        cols = [r[1] for r in c.fetchall()]
        conn.close()
        
        other_cols_sql = []
        for col in cols:
            if col.lower() in ('geom', 'geometry'): continue
            if col == 'text_size':
                if text_scale_factor != 1.0:
                    other_cols_sql.append(f"text_size * {text_scale_factor} as text_size")
                else:
                    other_cols_sql.append(f'"{col}"')
            elif col == 'line_width' and scale_factor != 1.0:
                 # line_width is usually in 1/100mm (integer). 
                 # If we scale geometry, line_width should ideally remain as "print size".
                 # But if line_width was somehow in ground units, it should scale.
                 # DXF 370 is strictly 1/100mm. It should NOT be scaled if it represents print width.
                 # So we keep it as is.
                 other_cols_sql.append(f'"{col}"')
            else:
                other_cols_sql.append(f'"{col}"')
                
        if other_cols_sql:
            cols_str = ", ".join(other_cols_sql)
            
    except Exception as e:
        print(f"Failed to get columns: {e}")
    
    temp_shifted = gpkg_path.parent / (gpkg_path.stem + "_shifted.gpkg")
    temp_final = gpkg_path.parent / (gpkg_path.stem + "_final.gpkg")
    
    for p in [temp_shifted, temp_final]:
        if p.exists():
            try: p.unlink()
            except: pass

    # Step 1: Shift to center (0,0) + Handle Scaling
    # Instead of ST_Scale (which might be missing), we use SRS transformation trick
    # We define Source SRS with units=mm if needed, and Target SRS with units=m
    
    # First, shift to center (0,0)
    print(f"Shifting geometry by X:{-cx:.2f}, Y:{-cy:.2f} to center at (0,0)")
    sql = f"SELECT ST_Translate(geom, {-cx}, {-cy}, 0) as geom, {cols_str} FROM entities"
    
    # If scaling is needed, we define a custom SRS for the shifted GPKG
    # We use a Mercator projection centered at 0,0
    # If scale_factor is 0.001 (mm), we set units=mm
    # If scale_factor is 1.0 (m), we set units=m
    
    src_proj = "+proj=merc +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84 +datum=WGS84 +units=m +no_defs"
    if scale_factor == 0.001:
        # Use +to_meter=0.001 to explicitly define units as millimeters
        # +units=mm might be ignored or not supported in all PROJ versions for Mercator
        src_proj = "+proj=merc +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84 +datum=WGS84 +to_meter=0.001 +no_defs"
    
    cmd_shift = [settings.ogr2ogr_cmd, "-f", "GPKG"]
    
    # Add spatial filter if we have robust bounds to clip outliers
    # MUST be placed before source/dest in some versions, or at least before -sql depending on driver
    if stats:
        # Use formatted strings to ensure valid float representation
        cmd_shift.extend(["-spat", f"{sx1:.4f}", f"{sy1:.4f}", f"{sx2:.4f}", f"{sy2:.4f}"])

    cmd_shift.extend([
        "-dialect", "SQLite",
        "-sql", sql,
        "-nln", "entities",
        "-a_srs", src_proj, # Assign the custom SRS to the shifted data
        "-lco", "GEOMETRY_NAME=geom",
        "-nlt", "GEOMETRY",
        "-dim", "XY",
        str(temp_shifted),
        str(gpkg_path)
    ])
    
    print(f"Running normalization command: {' '.join(cmd_shift)}")
    
    ok_shift, out_shift = _run(cmd_shift)
    
    # Check if shift produced a valid file
    shift_success = False
    if ok_shift and temp_shifted.exists():
        if check_gpkg_count(temp_shifted) > 0:
            shift_success = True
        else:
            print("Normalization (Shift+Filter) resulted in empty GPKG. Retrying without spatial filter...")
    
    # Retry without spatial filter if first attempt failed (likely aggressive filtering)
    if not shift_success and stats:
        print("Retrying normalization WITHOUT spatial filter...")
        cmd_shift_retry = [settings.ogr2ogr_cmd, "-f", "GPKG"]
        cmd_shift_retry.extend([
            "-dialect", "SQLite",
            "-sql", sql,
            "-nln", "entities",
            "-a_srs", src_proj,
            "-lco", "GEOMETRY_NAME=geom",
            "-nlt", "GEOMETRY",
            "-dim", "XY",
            str(temp_shifted),
            str(gpkg_path)
        ])
        ok_shift, out_shift = _run(cmd_shift_retry)
        if ok_shift and temp_shifted.exists() and check_gpkg_count(temp_shifted) > 0:
            shift_success = True
        else:
            print(f"Retry failed: {out_shift}")

    result_gpkg = None
    
    if shift_success:
        # Step 2: Reproject to EPSG:4326 (WGS84)
        # This will automatically handle the unit conversion (mm -> m/degrees)
        # because temp_shifted has units=mm defined in its SRS
        cmd_proj = [
            settings.ogr2ogr_cmd,
            "-f", "GPKG",
            str(temp_final),
            str(temp_shifted),
            "-t_srs", "EPSG:4326"
        ]
        ok_proj, out_proj = _run(cmd_proj)
        if ok_proj:
            result_gpkg = temp_final
        else:
            print(f"Normalization (Project) failed: {out_proj}")
    else:
        print(f"Normalization (Shift) failed: {out_shift}")
        # Fallback: Direct project without shift (assume coordinates are valid 3857)
        print("Attempting fallback: Project 3857->4326 without shift...")
        cmd_fallback = [
            settings.ogr2ogr_cmd,
            "-f", "GPKG",
            str(temp_final),
            str(gpkg_path),
            "-s_srs", "EPSG:3857",
            "-t_srs", "EPSG:4326"
        ]
        ok_fb, out_fb = _run(cmd_fallback)
        if ok_fb:
            result_gpkg = temp_final
        else:
            print(f"Fallback failed: {out_fb}")

    if result_gpkg and result_gpkg.exists():
        count = check_gpkg_count(result_gpkg)
        if count == 0:
            print("Normalization resulted in empty GPKG, keeping original.")
            return False

        # Replace original
        for i in range(5):
            try:
                shutil.move(result_gpkg, gpkg_path)
                break
            except Exception as e:
                print(f"Overwrite retry {i}: {e}")
                time.sleep(1)
        else:
             print("Could not overwrite original GPKG")
             return False
        
        # Cleanup
        if temp_shifted.exists():
            try: temp_shifted.unlink()
            except: pass
        return True
    
    return False

def get_gpkg_layers(gpkg_path: Path) -> list[dict]:
    """Extract distinct layer names and their representative colors from the GPKG entities table."""
    try:
        conn = sqlite3.connect(gpkg_path)
        c = conn.cursor()
        
        # Check if Layer column exists
        c.execute("PRAGMA table_info(entities)")
        cols = [r[1] for r in c.fetchall()]
        
        if 'Layer' not in cols:
            conn.close()
            return []
            
            
        # 1. Get all layers
        c.execute("SELECT DISTINCT Layer FROM entities WHERE Layer IS NOT NULL ORDER BY Layer")
        all_layers = [row[0] for row in c.fetchall()]
        
        # 2. Get representative color for each layer (most frequent line_color)
        layer_colors = {}
        if 'line_color' in cols:
            try:
                c.execute("""
                    SELECT Layer, line_color, COUNT(*) as cnt 
                    FROM entities 
                    WHERE Layer IS NOT NULL AND line_color IS NOT NULL 
                    GROUP BY Layer, line_color
                """)
                # Process to find max count per layer
                temp_counts = {}
                for row in c.fetchall():
                    layer, color, count = row
                    if layer not in temp_counts:
                        temp_counts[layer] = []
                    temp_counts[layer].append((color, count))
                
                for layer, counts in temp_counts.items():
                    # Sort by count desc
                    counts.sort(key=lambda x: x[1], reverse=True)
                    layer_colors[layer] = counts[0][0]
            except Exception as e:
                print(f"Error extracting colors: {e}")

        result = []
        for layer in all_layers:
            # Default to a generic color if not found
            color = layer_colors.get(layer, "#9ca3af") 
            result.append({"name": layer, "color": color})
            
        conn.close()
        return result
    except Exception as e:
        print(f"Error getting layers: {e}")
        return []
