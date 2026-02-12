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

def parse_dxf_alignments(dxf_path: Path) -> dict[str, tuple[float, float, float, float, float]]:
    """
    Parse DXF to extract text alignment points for Text/MText.
    Returns dict: Handle -> (anchor_x, anchor_y, offset_x, offset_y, height)
    offset_x/y is the shift needed if GDAL used InsertionPoint (Group 10) but Text uses AlignmentPoint (Group 11).
    height is the text height (Group 40)
    """
    alignments = {}
    try:
        with open(dxf_path, "r", encoding="utf-8", errors="ignore") as f:
            # Use iterator directly to avoid loading whole file into memory
            iterator = iter(f)
            
            current_handle = None
            current_type = None
            attrs = {}
            
            def calc_props(type_, attrs):
                # Default to Bottom Left (0, 0), No Offset (0, 0)
                ax, ay = 0.0, 0.0
                off_x, off_y = 0.0, 0.0
                height = 0.0
                
                # Group 40: Text Height
                try: height = attrs.get('40', 0.0)
                except: pass
                
                if type_ == 'MTEXT':
                    # Group 71: Attachment point
                    # 1=TL, 2=TC, 3=TR
                    # 4=ML, 5=MC, 6=MR
                    # 7=BL, 8=BC, 9=BR
                    ap = attrs.get('71', 1)
                    if ap in (1, 2, 3): ay = 1.0 # Top
                    elif ap in (4, 5, 6): ay = 0.5 # Middle
                    else: ay = 0.0 # Bottom
                    
                    if ap in (1, 4, 7): ax = 0.0 # Left
                    elif ap in (2, 5, 8): ax = 0.5 # Center
                    else: ax = 1.0 # Right
                    
                elif type_ == 'TEXT':
                    # Group 72: Horiz Alignment
                    # 0=Left, 1=Center, 2=Right, 3=Aligned, 4=Middle, 5=Fit
                    h = attrs.get('72', 0)
                    # Group 73: Vert Alignment
                    # 0=Baseline, 1=Bottom, 2=Middle, 3=Top
                    v = attrs.get('73', 0)
                    
                    # Horizontal
                    if h == 0: ax = 0.0 # Left
                    elif h == 1: ax = 0.5 # Center
                    elif h == 2: ax = 1.0 # Right
                    elif h == 4: ax = 0.5 # Middle (Special)
                    else: ax = 0.5 # Aligned/Fit (treat as center)
                    
                    # Vertical
                    if v == 3: ay = 1.0 # Top
                    elif v == 2: ay = 0.5 # Middle
                    elif v == 1: ay = 0.0 # Bottom
                    else: ay = 0.0 # Baseline
                    
                    # Special case: Middle (72=4) implies center vertical too
                    if h == 4:
                        ax, ay = 0.5, 0.5
                    
                    # Check for Geometry Offset (Text Aligned usually implies using Group 11)
                    # If alignment is used (h!=0 or v!=0), GDAL might still put geom at Group 10.
                    # We want to move it to Group 11.
                    if h != 0 or v != 0:
                        g10x = attrs.get('10', 0.0)
                        g10y = attrs.get('20', 0.0)
                        g11x = attrs.get('11', 0.0)
                        g11y = attrs.get('21', 0.0)
                        
                        # Offset = Target(11) - Current(10)
                        off_x = g11x - g10x
                        off_y = g11y - g10y
                        
                return ax, ay, off_x, off_y, height

            try:
                while True:
                    code = next(iterator).strip()
                    value = next(iterator).strip()
                    
                    if code == '0':
                        # Save previous entity if valid
                        if current_handle and current_type in ('TEXT', 'MTEXT'):
                            alignments[current_handle] = calc_props(current_type, attrs)
                        
                        current_type = value
                        current_handle = None
                        attrs = {}
                        
                        if value == 'EOF':
                            break
                            
                    elif code == '5':
                        current_handle = value
                    elif code in ('71', '72', '73'):
                        try:
                            attrs[code] = int(value)
                        except: pass
                    elif code in ('10', '20', '11', '21', '40'):
                        try:
                            attrs[code] = float(value)
                        except: pass
                        
            except StopIteration:
                pass
                
    except Exception as e:
        print(f"Alignment parsing failed: {e}")
        
    return alignments

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
        "-s_srs", "EPSG:3857",
        "-t_srs", "EPSG:3857",
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
        
        # 7. Parse DXF Text Alignments
        if progress_callback: progress_callback(70, "正在解析文本对齐方式...")
        try:
            alignments = parse_dxf_alignments(dxf_path)
            if alignments:
                # Update anchors
                c.executemany(
                    "UPDATE entities SET anchor_x=?, anchor_y=? WHERE EntityHandle=?", 
                    [(v[0], v[1], k) for k, v in alignments.items()]
                )
                
                # Apply geometry shifts for aligned text
                shifts = [(v[2], v[3], k) for k, v in alignments.items() if v[2] != 0 or v[3] != 0]
                if shifts:
                    print(f"Applying geometry shift to {len(shifts)} text entities...")
                    try:
                        # Optimized batch update using temporary table
                        c.execute("CREATE TEMPORARY TABLE IF NOT EXISTS text_shifts (handle TEXT PRIMARY KEY, dx REAL, dy REAL)")
                        c.execute("DELETE FROM text_shifts")
                        
                        # Bulk insert shifts
                        c.executemany("INSERT INTO text_shifts (dx, dy, handle) VALUES (?, ?, ?)", shifts)
                        
                        # Select all affected geometries in one go
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
                                
                        # Bulk update
                        if geom_updates:
                            c.executemany("UPDATE entities SET geom=? WHERE EntityHandle=?", geom_updates)
                            
                        # Cleanup
                        c.execute("DROP TABLE text_shifts")
                        
                    except Exception as e:
                        print(f"Batch geometry shift error: {e}")
                        # Fallback to slow loop if batch fails
                        for dx, dy, handle in shifts:
                            try:
                                c.execute("SELECT geom FROM entities WHERE EntityHandle=?", (handle,))
                                row = c.fetchone()
                                if row and row[0]:
                                    new_blob = apply_geometry_shift(row[0], dx, dy)
                                    if new_blob != row[0]:
                                        c.execute("UPDATE entities SET geom=? WHERE EntityHandle=?", (new_blob, handle))
                            except: pass

                # Update text size from Group 40 (Height)
                sizes = [(v[4], k) for k, v in alignments.items() if v[4] > 0]
                if sizes:
                    try:
                        # Optimized batch update for text sizes using temp table
                        c.execute("CREATE TEMPORARY TABLE IF NOT EXISTS text_sizes (handle TEXT PRIMARY KEY, size REAL)")
                        c.execute("DELETE FROM text_sizes")
                        c.executemany("INSERT INTO text_sizes (size, handle) VALUES (?, ?)", sizes)
                        
                        # Use UPDATE FROM syntax (SQLite >= 3.33) or standard correlated subquery
                        try:
                            # Try UPDATE FROM first
                            c.execute("""
                                UPDATE entities 
                                SET text_size = text_sizes.size 
                                FROM text_sizes 
                                WHERE entities.EntityHandle = text_sizes.handle
                            """)
                        except:
                            # Fallback to subquery (slower but safe)
                            c.execute("""
                                UPDATE entities 
                                SET text_size = (SELECT size FROM text_sizes WHERE handle = entities.EntityHandle)
                                WHERE EXISTS (SELECT 1 FROM text_sizes WHERE handle = entities.EntityHandle)
                            """)
                            
                        c.execute("DROP TABLE text_sizes")
                    except Exception as e:
                        print(f"Text size batch update error: {e}")
                        # Fallback to loop
                        try:
                             c.executemany("UPDATE entities SET text_size=? WHERE EntityHandle=?", sizes)
                        except: pass

        except Exception as e:
            print(f"Alignment parsing warning: {e}")
            
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

def normalize_coordinates(gpkg_path: Path) -> bool:
    """Check if coordinates are out of WGS84 bounds and shift to (0,0) if needed."""
    ok, bbox = get_gpkg_bbox(gpkg_path)
    if not ok or not bbox:
        return False

    min_x, min_y, max_x, max_y = bbox
    if -190 <= min_x and max_x <= 190 and -95 <= min_y and max_y <= 95:
        return True
        
    print(f"Coordinates out of bounds ({bbox}), normalizing...")
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2
    
    # Get columns to avoid "geom, *" ambiguity
    cols_str = "*"
    try:
        conn = sqlite3.connect(gpkg_path)
        c = conn.cursor()
        c.execute("PRAGMA table_info(entities)")
        cols = [r[1] for r in c.fetchall()]
        conn.close()
        other_cols = [f'"{col}"' for col in cols if col.lower() not in ('geom', 'geometry')]
        if other_cols:
            cols_str = ", ".join(other_cols)
    except Exception as e:
        print(f"Failed to get columns: {e}")
    
    temp_shifted = gpkg_path.parent / (gpkg_path.stem + "_shifted.gpkg")
    temp_final = gpkg_path.parent / (gpkg_path.stem + "_final.gpkg")
    
    for p in [temp_shifted, temp_final]:
        if p.exists():
            try: p.unlink()
            except: pass

    # Step 1: Try Shift + Assign EPSG:3857
    # Use ST_Translate with Z=0 to support 3D geometries (DXF is often 3D)
    # We use -dim XY to flatten 3D geometries to 2D for better compatibility
    sql = f"SELECT ST_Translate(geom, {-cx}, {-cy}, 0) as geom, {cols_str} FROM entities"
    
    cmd_shift = [
        settings.ogr2ogr_cmd,
        "-f", "GPKG",
        str(temp_shifted),
        str(gpkg_path),
        "-dialect", "SQLite",
        "-sql", sql,
        "-nln", "entities",
        "-a_srs", "EPSG:3857",
        "-lco", "GEOMETRY_NAME=geom",
        "-nlt", "GEOMETRY",
        "-dim", "XY"
    ]
    
    ok_shift, out_shift = _run(cmd_shift)
    
    result_gpkg = None
    
    if ok_shift:
        # Step 2: Reproject to EPSG:4326
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
