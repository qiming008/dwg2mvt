# -*- coding: utf-8 -*-
"""DWG -> DXF (LibreDWG) -> GeoPackage (GDAL) conversion"""
import csv
import html
import json
import subprocess
import uuid
import re
import sqlite3
import os
import shutil
import time
import struct
import unicodedata
import tempfile
from collections import Counter
from pathlib import Path
import math

from app.config import settings
from app.services.coordinate_systems import CoordinateSystemError, build_source_srs

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


def _run_stdout_to_file(
    cmd: list[str],
    output_path: Path,
    cwd: Path | None = None,
    timeout: int = 300,
) -> tuple[bool, str]:
    """Execute command and write stdout to a file."""
    try:
        with output_path.open("wb") as f:
            r = subprocess.run(
                cmd,
                cwd=cwd,
                env=ENV_GDAL,
                stdout=f,
                stderr=subprocess.PIPE,
                text=False,
                timeout=timeout,
            )
        if r.returncode != 0:
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass
            message = (r.stderr or b"").decode("utf-8", errors="replace")
            return False, message or f"exit code {r.returncode}"
        if not output_path.exists() or output_path.stat().st_size == 0:
            return False, "No preview content was generated"
        return True, ""
    except subprocess.TimeoutExpired:
        try:
            output_path.unlink(missing_ok=True)
        except Exception:
            pass
        return False, "Execution timeout"
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"
    except Exception as e:
        return False, str(e)


def _find_tool(*relative_parts: str) -> str:
    """Resolve tool path from backend/tools, with executable name fallback."""
    try:
        tool_path = BACKEND_DIR / "tools" / Path(*relative_parts)
        if tool_path.exists():
            return str(tool_path)
    except Exception:
        pass
    fallback_name = Path(relative_parts[-1]).stem
    return fallback_name if fallback_name else relative_parts[-1]


def _iter_geojson_coords(geometry: dict):
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return

    if geom_type == "Point":
        yield coords
        return

    stack = [coords]
    while stack:
        item = stack.pop()
        if not item:
            continue
        if isinstance(item[0], (int, float)) and len(item) >= 2:
            yield item
        else:
            stack.extend(reversed(item))


def _svg_point(point: list, bbox: list[float], scale: float, pad: float) -> tuple[float, float]:
    min_x, min_y, _max_x, max_y = bbox
    x = (float(point[0]) - min_x) * scale + pad
    y = (max_y - float(point[1])) * scale + pad
    return x, y


def _svg_path_from_coords(coords, geom_type: str, bbox: list[float], scale: float, pad: float) -> str:
    def ring_path(ring) -> str:
        parts = []
        for i, pt in enumerate(ring):
            x, y = _svg_point(pt, bbox, scale, pad)
            parts.append(("M" if i == 0 else "L") + f"{x:.2f},{y:.2f}")
        return " ".join(parts)

    if geom_type == "LineString":
        return ring_path(coords)
    if geom_type == "MultiLineString":
        return " ".join(ring_path(line) for line in coords)
    if geom_type == "Polygon":
        return " ".join(f"{ring_path(ring)} Z" for ring in coords)
    if geom_type == "MultiPolygon":
        return " ".join(f"{ring_path(ring)} Z" for poly in coords for ring in poly)
    return ""


def generate_gpkg_svg_preview(gpkg_path: Path, output_dir: Path) -> tuple[bool, Path | None, str]:
    """Generate a lightweight SVG preview from the converted GeoPackage."""
    if not gpkg_path.exists():
        return False, None, "GPKG preview source not found"

    ok_bbox, bbox = get_gpkg_bbox(gpkg_path)
    view_bbox = get_view_bbox(gpkg_path)
    if view_bbox:
        bbox = view_bbox
        ok_bbox = True
    if not ok_bbox or not bbox:
        return False, None, "GPKG preview bbox not found"

    min_x, min_y, max_x, max_y = bbox
    width_units = max_x - min_x
    height_units = max_y - min_y
    if width_units <= 0 or height_units <= 0:
        return False, None, "Invalid GPKG preview bbox"

    output_dir.mkdir(parents=True, exist_ok=True)
    preview_path = output_dir / "original_preview.svg"
    temp_root = Path(settings.original_preview_temp_dir)
    temp_root.mkdir(parents=True, exist_ok=True)
    visible_layers: list[str] = []
    try:
        conn = sqlite3.connect(gpkg_path)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='layer_metadata'")
        if c.fetchone():
            c.execute("SELECT layer_name FROM layer_metadata WHERE visible=1 ORDER BY layer_name")
            visible_layers = [str(row[0]) for row in c.fetchall() if row and row[0] is not None]
        conn.close()
    except Exception as e:
        print(f"GPKG SVG preview layer filter warning: {e}")

    with tempfile.TemporaryDirectory(prefix="gpkg_preview_", dir=temp_root) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        geojson_path = temp_dir / "preview.geojson"
        sql = None
        if visible_layers:
            escaped_layers = ", ".join("'" + layer.replace("'", "''") + "'" for layer in visible_layers)
            sql = f"SELECT * FROM entities WHERE Layer IN ({escaped_layers})"

        cmd = [
            settings.ogr2ogr_cmd,
            "-f",
            "GeoJSON",
            str(geojson_path),
            str(gpkg_path),
            "-spat",
            str(min_x),
            str(min_y),
            str(max_x),
            str(max_y),
            "-lco",
            "COORDINATE_PRECISION=7",
        ]
        if sql:
            cmd.extend(["-dialect", "SQLite", "-sql", sql])
        else:
            cmd.append("entities")
        ok, err = _run(cmd, cwd=temp_dir, timeout=settings.original_preview_timeout_seconds)
        if not ok or not geojson_path.exists():
            return False, None, f"GPKG to GeoJSON failed: {err}"

        data = json.loads(geojson_path.read_text(encoding="utf-8"))
        features = data.get("features") or []

    canvas_width = 1600.0
    canvas_height = max(600.0, min(1200.0, canvas_width * height_units / width_units))
    pad = 30.0
    scale = min((canvas_width - pad * 2) / width_units, (canvas_height - pad * 2) / height_units)
    stroke_width = max(0.6, min(2.0, 1200.0 / max(len(features), 1)))

    svg_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width:.0f}" height="{canvas_height:.0f}" viewBox="0 0 {canvas_width:.0f} {canvas_height:.0f}">',
        '<rect width="100%" height="100%" fill="#050505"/>',
        '<g font-family="SimHei, Microsoft YaHei, Arial, sans-serif" font-size="8">',
    ]
    for feature in features:
        geometry = feature.get("geometry") or {}
        geom_type = geometry.get("type")
        props = feature.get("properties") or {}
        subclasses = str(props.get("SubClasses") or "")
        if "AcDbDimensionLine" in subclasses:
            continue
        color = props.get("line_color") or props.get("text_color") or "#FFFFFF"
        fill = props.get("fill_color") if geom_type in {"Polygon", "MultiPolygon"} else None
        text = props.get("text_content") or props.get("Text")

        if is_visible_cad_text(text):
            first_point = next(_iter_geojson_coords(geometry), None)
            if first_point:
                x, y = _svg_point(first_point, bbox, scale, pad)
                size = props.get("text_size") or 8
                try:
                    font_size = max(2.0, min(14.0, float(size) * 0.18))
                except Exception:
                    font_size = 4.0
                angle = props.get("text_angle") or props.get("rotation") or 0
                try:
                    angle_value = float(angle)
                except Exception:
                    angle_value = 0.0
                safe_text = html.escape(str(text))
                svg_lines.append(
                    f'<text x="{x:.2f}" y="{y:.2f}" fill="{html.escape(str(color))}" font-size="{font_size:.2f}" transform="rotate({angle_value:.2f} {x:.2f} {y:.2f})">{safe_text}</text>'
                )
            continue

        if geom_type in {"LineString", "MultiLineString", "Polygon", "MultiPolygon"}:
            path = _svg_path_from_coords(geometry.get("coordinates"), geom_type, bbox, scale, pad)
            if not path:
                continue
            safe_color = html.escape(str(color))
            safe_fill = html.escape(str(fill)) if fill else "none"
            fill_opacity = "0.35" if fill else "0"
            svg_lines.append(
                f'<path d="{path}" stroke="{safe_color}" stroke-width="{stroke_width:.2f}" fill="{safe_fill}" fill-opacity="{fill_opacity}" vector-effect="non-scaling-stroke"/>'
            )
        elif geom_type == "Point":
            continue

    svg_lines.extend(["</g>", "</svg>"])
    temp_preview = output_dir / "original_preview.tmp.svg"
    temp_preview.write_text("\n".join(svg_lines), encoding="utf-8")
    if preview_path.exists():
        preview_path.unlink()
    temp_preview.rename(preview_path)
    return True, preview_path, ""


def generate_original_preview(source_path: Path, output_dir: Path, gpkg_path: Path | None = None) -> tuple[bool, Path | None, str]:
    """Generate a LibreDWG SVG preview for the uploaded source file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    preview_path = output_dir / "original_preview.svg"
    source_suffix = source_path.suffix.lower()

    if source_suffix == ".dxf":
        if gpkg_path:
            return generate_gpkg_svg_preview(gpkg_path, output_dir)
        return False, None, "DXF source requires a converted GPKG for original preview"

    temp_root = Path(settings.original_preview_temp_dir)
    temp_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="preview_", dir=temp_root) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        temp_source = temp_dir / f"source{source_suffix}"
        shutil.copy2(source_path, temp_source)

        dwg_timeout = settings.original_preview_timeout_seconds
        if source_suffix == ".dwg":
            dwg_path = temp_source
        else:
            return False, None, "Only DWG/DXF files can be previewed"

        temp_preview = temp_dir / "original_preview.tmp.svg"

        ok, err = _run_stdout_to_file(
            [settings.dwg2svg_cmd, str(dwg_path)],
            temp_preview,
            cwd=temp_dir,
            timeout=dwg_timeout,
        )
        if not ok:
            if gpkg_path:
                return generate_gpkg_svg_preview(gpkg_path, output_dir)
            return False, None, f"DWG to SVG failed: {err}"

        final_temp_preview = output_dir / "original_preview.tmp.svg"
        if final_temp_preview.exists():
            final_temp_preview.unlink()
        shutil.copy2(temp_preview, final_temp_preview)
        if preview_path.exists():
            preview_path.unlink()
        final_temp_preview.rename(preview_path)
        return True, preview_path, ""


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

def parse_dxf_layer_states(dxf_path: Path) -> dict[str, dict]:
    """Parse DXF LAYER table for visibility and representative color."""
    layers: dict[str, dict] = {}
    try:
        with open(dxf_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        lines = content.splitlines()
        current_layer = None
        current_color_aci: int | None = None
        current_flags = 0
        current_true_color: str | None = None
        in_layer_table = False

        def flush_current():
            if not current_layer:
                return

            color = None
            if current_true_color:
                color = current_true_color
            elif current_color_aci is not None:
                color_idx = abs(current_color_aci)
                if 0 <= color_idx < len(ACI_HEX):
                    color = ACI_HEX[color_idx]

            is_off = current_color_aci is not None and current_color_aci < 0
            is_frozen = bool(current_flags & 1)
            visible = (not is_off) and (not is_frozen)
            layers[current_layer] = {"visible": visible, "color": color}

        for i, line in enumerate(lines):
            line = line.strip()
            if line == "TABLE" and i+2 < len(lines) and lines[i+2].strip() == "LAYER":
                in_layer_table = True
            if line == "ENDTAB":
                flush_current()
                current_layer = None
                current_color_aci = None
                current_flags = 0
                current_true_color = None
                in_layer_table = False

            if in_layer_table:
                if line == "LAYER":
                    flush_current()
                    current_layer = None
                    current_color_aci = None
                    current_flags = 0
                    current_true_color = None
                if line == "2" and i+1 < len(lines):
                    current_layer = lines[i+1].strip()
                if line == "70" and i+1 < len(lines):
                    try:
                        current_flags = int(lines[i+1].strip())
                    except Exception:
                        pass
                if line == "62" and i+1 < len(lines) and current_layer:
                    try:
                        current_color_aci = int(lines[i+1].strip())
                    except Exception:
                        pass
                if line == "420" and i+1 < len(lines) and current_layer:
                    try:
                        val = int(lines[i+1].strip())
                        r = (val >> 16) & 0xFF
                        g = (val >> 8) & 0xFF
                        b = val & 0xFF
                        current_true_color = f"#{r:02X}{g:02X}{b:02X}"
                    except Exception:
                        pass
    except Exception as e:
        print(f"Layer parsing failed: {e}")
    return layers


def parse_dxf_layers(dxf_path: Path) -> dict[str, str]:
    """Backward-compatible layer-color parser."""
    layer_states = parse_dxf_layer_states(dxf_path)
    return {
        layer_name: state["color"]
        for layer_name, state in layer_states.items()
        if state.get("color")
    }


def parse_dwg_layer_states(dwg_path: Path) -> dict[str, dict]:
    """Parse original DWG layer flags via LibreDWG dwglayers."""
    layer_states: dict[str, dict] = {}
    dwglayers_cmd = _find_tool("dwglayers.exe")
    ok, output = _run([dwglayers_cmd, "-f", str(dwg_path)], cwd=dwg_path.parent)
    if not ok:
        return layer_states

    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if "\t" in line:
            flag_text, layer_name = line.split("\t", 1)
        else:
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            flag_text, layer_name = parts

        flag_text = flag_text.strip()
        layer_name = layer_name.strip()
        if not layer_name:
            continue

        # dwglayers -f prints 3 flag slots: frozen / on-off / locked
        # We only care about the explicit on/off and frozen state here.
        visible = "+" in flag_text and "f" not in flag_text.lower()
        layer_states[layer_name] = {"visible": visible, "color": None}

    return layer_states


def write_layer_metadata(gpkg_path: Path, layer_states: dict[str, dict]) -> None:
    """Persist DXF-derived layer defaults into the final GPKG."""
    if not layer_states or not gpkg_path.exists():
        return

    conn = sqlite3.connect(gpkg_path)
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS layer_metadata (
                layer_name TEXT PRIMARY KEY,
                visible INTEGER NOT NULL DEFAULT 1,
                color TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_layer_metadata_visible ON layer_metadata(visible)")
        c.execute("DELETE FROM layer_metadata")
        c.executemany(
            "INSERT INTO layer_metadata(layer_name, visible, color) VALUES (?, ?, ?)",
            [
                (
                    layer_name,
                    1 if state.get("visible", True) else 0,
                    state.get("color"),
                )
                for layer_name, state in layer_states.items()
            ],
        )
        conn.commit()
    finally:
        conn.close()


def clean_mtext_content(value: str | None) -> str | None:
    """Strip AutoCAD MTEXT formatting controls while preserving visible text."""
    if value is None:
        return None

    text = str(value)
    if not text:
        return text

    literal_lbrace = "\u0000LBRACE\u0000"
    literal_rbrace = "\u0000RBRACE\u0000"
    text = text.replace("\\{", literal_lbrace).replace("\\}", literal_rbrace)
    text = text.replace("\\P", "\n").replace("\\p", "\n").replace("\\~", " ")
    text = text.replace("\\\\", "\\")

    # Font, color, width, height, tracking and stacked-fraction controls end at ';'.
    text = re.sub(r"\\[A-Za-z][^;{}\\]*(?:;|$)", "", text)
    # Simple toggles such as underline/overline may not have parameters.
    text = re.sub(r"\\[LlOoKk]", "", text)
    text = text.replace("{", "").replace("}", "")
    text = text.replace(literal_lbrace, "{").replace(literal_rbrace, "}")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def is_visible_cad_text(value: str | None) -> bool:
    """Filter CAD control strings that are not intended as visible labels."""
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    upper = text.upper()
    if re.fullmatch(r"ISO[-_ ]?\d+(?:\$0)?", upper):
        return False
    if upper in {"STANDARD", "BYLAYER", "BYBLOCK"}:
        return False
    return True


def clean_duplicate_and_control_text_entities(conn: sqlite3.Connection, cols: list[str]) -> None:
    """Remove only explicit CAD control text from persisted entities."""
    if 'Text' not in cols and 'text_content' not in cols:
        return

    c = conn.cursor()
    text_expr = "COALESCE(text_content, Text)" if 'text_content' in cols and 'Text' in cols else (
        "text_content" if 'text_content' in cols else "Text"
    )

    try:
        c.execute(
            f"""
            SELECT rowid, {text_expr} AS text_value
            FROM entities
            WHERE {text_expr} IS NOT NULL AND TRIM({text_expr}) <> ''
            """
        )
        clear_rowids: list[tuple[int]] = []
        for rowid, text_value in c.fetchall():
            cleaned = clean_mtext_content(text_value)
            if not is_visible_cad_text(cleaned):
                clear_rowids.append((rowid,))

        if clear_rowids:
            assignments = []
            if 'Text' in cols:
                assignments.append("Text=NULL")
            if 'text_content' in cols:
                assignments.append("text_content=NULL")
            c.executemany(
                f"UPDATE entities SET {', '.join(assignments)} WHERE rowid=?",
                clear_rowids,
            )
            print(f"Removed {len(clear_rowids)} CAD control text entities")
    except Exception as e:
        print(f"Control text cleanup warning: {e}")


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
                
                # 1. Color (Group 62 & 420)
                # If missing, it's ByLayer (256), which we skip (handled by layer logic)
                # If 0, it's ByBlock
                color_hex = None
                
                # Check True Color (420) first
                if '420' in attrs:
                    try:
                        val = int(attrs['420'])
                        r = (val >> 16) & 0xFF
                        g = (val >> 8) & 0xFF
                        b = val & 0xFF
                        color_hex = f"#{r:02X}{g:02X}{b:02X}"
                        data['c'] = color_hex
                    except: pass
                
                # Fallback to ACI (62) if no True Color
                if not color_hex and '62' in attrs:
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
                if type_ in ('TEXT', 'MTEXT', 'DIMENSION'):
                    # Rotation (Group 50)
                    rotation = 0.0
                    if '50' in attrs:
                        try: rotation = -float(attrs['50']) # Convert CCW to CW for SLD/MapLibre
                        except: pass
                    
                    # MTEXT Direction Vector (Group 11, 21) overrides/supplements rotation
                    # Usually MTEXT rotation is 0 and direction defines angle
                    if type_ in ('MTEXT', 'DIMENSION') and '11' in attrs and '21' in attrs:
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
                            if '11' in attrs and '21' in attrs:
                                data['align_x_raw'] = g11x
                                data['align_y_raw'] = g11y
                            off_x = g11x - g10x
                            off_y = g11y - g10y
                    elif type_ == 'DIMENSION':
                        ax, ay = 0.5, 0.5
                        g10x = float(attrs.get('10', 0.0))
                        g10y = float(attrs.get('20', 0.0))
                        g11x = float(attrs.get('11', g10x))
                        g11y = float(attrs.get('21', g10y))
                        off_x = g11x - g10x
                        off_y = g11y - g10y
                        data['definition'] = {
                            key: float(attrs[key])
                            for key in ('10', '20', '11', '21', '13', '23', '14', '24', '50')
                            if key in attrs
                        }
                            
                    data['ax'] = ax
                    data['ay'] = ay
                    if off_x != 0 or off_y != 0:
                        data['dx'] = off_x
                        data['dy'] = off_y
                        
                # 5. Text Content (Full Extraction)
                if type_ == 'DIMENSION' and '42' in attrs:
                    try:
                        measurement = float(attrs['42'])
                        data['t'] = f"{measurement:.2f}".replace(".", ",")
                    except Exception:
                        pass
                elif 'txt' in attrs:
                    # DXF stores MTEXT in chunks: Group 3 (multiple) followed by Group 1.
                    # We just concatenate all found strings in order of appearance.
                    # Since we read sequentially, this should be correct if DXF is well-formed.
                    full_text = "".join(attrs['txt'])
                    if full_text:
                        data['t'] = clean_mtext_content(full_text) if type_ == 'MTEXT' else full_text

                # 6. Layer Name (Group 8)
                if '8' in attrs:
                    data['layer'] = attrs['8']

                return data

            try:
                # We need to track current handle and type
                current_handle = None
                current_type = None
                attrs = {}
                
                for line in iterator:
                    code = line.strip()
                    try:
                        value = next(iterator).strip()
                    except StopIteration:
                        break
                    
                    if code == '0':
                        # End of previous entity
                        if current_handle:
                            # Use helper
                            res = process_entity(current_type, attrs)
                            if res: results[current_handle] = res

                        current_type = value
                        current_handle = None
                        attrs = {}
                        
                        if value == 'EOF':
                            break
                            
                    elif code == '5':
                        current_handle = value
                    elif code == '8':
                        # Layer Name
                        attrs['8'] = value
                    elif code in ('1', '3'):
                        # Text Content (1=Primary, 3=Additional chunks for MTEXT > 250 chars)
                        # We accumulate them in order. DXF standard: 3 comes before 1.
                        # But some implementations might vary. We'll store list.
                        if 'txt' not in attrs: attrs['txt'] = []
                        attrs['txt'].append(value)
                    elif code in ('10', '20', '11', '21', '13', '23', '14', '24', '40', '42', '50'):
                        try: attrs[code] = float(value) # Keep as float for coords/angles
                        except: pass
                    elif code in ('62', '71', '72', '73', '370', '420'):
                        try: attrs[code] = int(value) # Keep as int for enums
                        except: pass
                        
            except StopIteration:
                pass
                
    except Exception as e:
        print(f"Attribute extraction failed: {e}")
        
    return results


SUPPORTED_HATCH_PATTERNS = {"ANSI31", "ANSI36", "ANGLE", "GRAVEL", "GRAVL1", "AR-SAND", "STEEL"}


def extract_dxf_hatch_patterns(dxf_path: Path) -> dict[str, dict]:
    """Extract non-solid HATCH pattern metadata keyed by entity handle."""
    hatches: dict[str, dict] = {}
    try:
        with open(dxf_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [line.rstrip("\r\n") for line in f]

        current: list[tuple[str, str]] = []

        def flush_entity(entity: list[tuple[str, str]]) -> None:
            if not entity:
                return
            values: dict[str, list[str]] = {}
            for code, value in entity:
                values.setdefault(code, []).append(value)
            if values.get("0", [""])[0] != "HATCH":
                return

            handle = (values.get("5") or [None])[0]
            pattern = (values.get("2") or [""])[0].strip().upper()
            if not handle or not pattern or pattern == "SOLID":
                return
            if pattern not in SUPPORTED_HATCH_PATTERNS:
                return

            def first_float(code: str, fallback: float) -> float:
                try:
                    return float((values.get(code) or [fallback])[0])
                except Exception:
                    return fallback

            hatches[handle] = {
                "handle": handle,
                "layer": (values.get("8") or [""])[0],
                "pattern": pattern,
                "angle": first_float("52", 0.0),
                "scale": first_float("41", 1.0),
            }

        for i in range(0, len(lines) - 1, 2):
            code = lines[i].strip()
            value = lines[i + 1].strip()
            if code == "0":
                flush_entity(current)
                current = [("0", value)]
            elif current:
                current.append((code, value))
        flush_entity(current)
    except Exception as e:
        print(f"HATCH pattern extraction failed: {e}")
    return hatches


def _gpkg_linestring_blob(points: list[tuple[float, float]], srs_id: int = 4326) -> bytes:
    """Create a minimal GeoPackage geometry blob for a 2D LineString."""
    wkb = bytearray()
    wkb.extend(struct.pack("<BII", 1, 2, len(points)))
    for x, y in points:
        wkb.extend(struct.pack("<dd", x, y))
    return b"GP\x00\x01" + struct.pack("<I", srs_id) + bytes(wkb)


def _gpkg_point_blob(point: tuple[float, float], srs_id: int = 4326) -> bytes:
    """Create a minimal GeoPackage geometry blob for a 2D Point."""
    wkb = bytearray()
    wkb.extend(struct.pack("<BI", 1, 1))
    wkb.extend(struct.pack("<dd", point[0], point[1]))
    return b"GP\x00\x01" + struct.pack("<I", srs_id) + bytes(wkb)


def _gpkg_geometry_type(blob) -> int | None:
    """Return the WKB geometry type from a GeoPackage geometry blob."""
    if not blob or len(blob) < 13:
        return None
    try:
        if blob[:2] != b"GP":
            return None
        flags = blob[3]
        envelope_code = (flags >> 1) & 7
        offset = 8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(envelope_code, 0)
        endian = blob[offset]
        fmt = "<" if endian == 1 else ">"
        return struct.unpack(fmt + "I", blob[offset + 1:offset + 5])[0]
    except Exception:
        return None


def _clip_line_to_bbox(
    cx: float,
    cy: float,
    dx: float,
    dy: float,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
) -> list[tuple[float, float]] | None:
    """Clip an infinite parametric line to an axis-aligned bbox."""
    ts: list[float] = []
    eps = 1e-15
    if abs(dx) > eps:
        for x in (min_x, max_x):
            t = (x - cx) / dx
            y = cy + t * dy
            if min_y - eps <= y <= max_y + eps:
                ts.append(t)
    if abs(dy) > eps:
        for y in (min_y, max_y):
            t = (y - cy) / dy
            x = cx + t * dx
            if min_x - eps <= x <= max_x + eps:
                ts.append(t)
    if len(ts) < 2:
        return None
    ts = sorted(ts)
    p1 = (cx + ts[0] * dx, cy + ts[0] * dy)
    p2 = (cx + ts[-1] * dx, cy + ts[-1] * dy)
    if abs(p1[0] - p2[0]) < eps and abs(p1[1] - p2[1]) < eps:
        return None
    return [p1, p2]


def _generate_parallel_hatch_lines(
    bbox: tuple[float, float, float, float],
    angle_degrees: float,
    spacing: float,
    max_lines: int = 350,
) -> list[list[tuple[float, float]]]:
    min_x, min_y, max_x, max_y = bbox
    width = max_x - min_x
    height = max_y - min_y
    if width <= 0 or height <= 0:
        return []

    diagonal = math.hypot(width, height)
    spacing = max(spacing, diagonal / max_lines)
    angle = math.radians(angle_degrees)
    dx = math.cos(angle)
    dy = math.sin(angle)
    nx = -dy
    ny = dx
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    count = min(max_lines, int(diagonal / spacing) + 4)
    start = -count / 2
    lines: list[list[tuple[float, float]]] = []
    for i in range(count + 1):
        offset = (start + i) * spacing
        cx = center_x + nx * offset
        cy = center_y + ny * offset
        clipped = _clip_line_to_bbox(cx, cy, dx, dy, min_x, min_y, max_x, max_y)
        if clipped:
            lines.append(clipped)
    return lines


def _generate_gravel_hatch_lines(
    bbox: tuple[float, float, float, float],
    spacing: float,
    max_cells: int = 120,
) -> list[list[tuple[float, float]]]:
    min_x, min_y, max_x, max_y = bbox
    width = max_x - min_x
    height = max_y - min_y
    if width <= 0 or height <= 0:
        return []
    spacing = max(spacing, math.hypot(width, height) / max_cells)
    cols = min(max_cells, max(1, int(width / spacing)))
    rows = min(max_cells, max(1, int(height / spacing)))
    lines: list[list[tuple[float, float]]] = []
    for row in range(rows):
        for col in range(cols):
            seed = (row * 928371 + col * 364479) & 0xFFFF
            jitter_x = ((seed % 97) / 97.0 - 0.5) * spacing * 0.35
            jitter_y = (((seed // 97) % 89) / 89.0 - 0.5) * spacing * 0.35
            cx = min_x + (col + 0.5) * spacing + jitter_x
            cy = min_y + (row + 0.5) * spacing + jitter_y
            r = spacing * (0.28 + (seed % 17) / 100.0)
            sides = 5 + (seed % 3)
            poly: list[tuple[float, float]] = []
            for idx in range(sides + 1):
                a = 2 * math.pi * idx / sides + (seed % 31) * 0.03
                x = min(max(cx + math.cos(a) * r, min_x), max_x)
                y = min(max(cy + math.sin(a) * r, min_y), max_y)
                poly.append((x, y))
            lines.append(poly)
    return lines


def _build_source_srs_for_conversion(
    coordinate_system_code: str | None,
    gauss_kruger_zone: int | None,
) -> tuple[str | None, str | None]:
    if not settings.enable_gauss_kruger_transform:
        return None, None
    if coordinate_system_code:
        source_srs = build_source_srs(coordinate_system_code)
        return source_srs, f"coordinate_system={coordinate_system_code}"

    zone = gauss_kruger_zone if gauss_kruger_zone is not None else settings.gauss_kruger_zone
    if zone is None:
        zone = 39
        print(f"Auto-detected Gauss-Kruger 3-degree zone fallback: {zone}")
    central_meridian = zone * 3
    false_easting = zone * 1000000 + 500000
    source_srs = (
        f"+proj=tmerc +lat_0=0 +lon_0={central_meridian} "
        f"+k=1.0 +x_0={false_easting} +y_0=0 +ellps=krass +units=m +no_defs"
    )
    return source_srs, f"belt_code={zone}"


def _gdaltransform_cmd() -> str:
    ogr_cmd = Path(settings.ogr2ogr_cmd)
    if os.name == "nt" and ogr_cmd.name.lower().endswith(".exe"):
        candidate = ogr_cmd.with_name("gdaltransform.exe")
        if candidate.exists():
            return str(candidate)
    return "gdaltransform"


def _transform_points_with_gdal(
    points: list[tuple[float, float]],
    source_srs: str | None,
    target_srs: str = "EPSG:4326",
) -> list[tuple[float, float]]:
    if not points:
        return []
    if not source_srs:
        return points

    input_text = "".join(f"{x} {y}\n" for x, y in points)
    try:
        proc = subprocess.run(
            [_gdaltransform_cmd(), "-s_srs", source_srs, "-t_srs", target_srs],
            input=input_text,
            text=True,
            capture_output=True,
            timeout=60,
            env=ENV_GDAL,
        )
        if proc.returncode != 0:
            print(f"DIMENSION transform warning: {proc.stderr or proc.stdout}")
            return []
        transformed = []
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                transformed.append((float(parts[0]), float(parts[1])))
        return transformed if len(transformed) == len(points) else []
    except Exception as e:
        print(f"DIMENSION transform warning: {e}")
        return []


def _dimension_line_segments(definition: dict) -> list[list[tuple[float, float]]]:
    if not all(key in definition for key in ('13', '23', '14', '24', '10', '20')):
        return []

    p1 = (definition['13'], definition['23'])
    p2 = (definition['14'], definition['24'])
    dim_ref = (definition['10'], definition['20'])
    vx = p2[0] - p1[0]
    vy = p2[1] - p1[1]
    length = math.hypot(vx, vy)
    if length <= 1e-9:
        return []

    ux, uy = vx / length, vy / length
    nx, ny = -uy, ux
    offset = (dim_ref[0] - p1[0]) * nx + (dim_ref[1] - p1[1]) * ny
    d1 = (p1[0] + nx * offset, p1[1] + ny * offset)
    d2 = (p2[0] + nx * offset, p2[1] + ny * offset)

    segments = [
        [p1, d1],
        [p2, d2],
        [d1, d2],
    ]

    return segments


def expand_degraded_dimensions(
    conn: sqlite3.Connection,
    cols: list[str],
    attrs_map: dict[str, dict],
    source_srs: str | None,
) -> None:
    if not attrs_map or 'geom' not in cols or 'EntityHandle' not in cols:
        return

    c = conn.cursor()
    insert_rows = []
    text_updates = []
    point_rowids_to_delete = []
    for handle, data in attrs_map.items():
        if data.get('type') != 'DIMENSION' or not data.get('definition'):
            continue

        c.execute(
            """
            SELECT rowid, SubClasses, geom, Layer, line_color, text_color
            FROM entities
            WHERE EntityHandle=?
            """,
            (handle,),
        )
        rows = c.fetchall()
        if not rows or any("AcDbDimensionLine" in str(row[1] or "") for row in rows):
            continue

        raw_segments = _dimension_line_segments(data['definition'])
        if not raw_segments:
            continue
        raw_points = [point for segment in raw_segments for point in segment]
        points = _transform_points_with_gdal(raw_points, source_srs)
        if not points:
            continue

        sample = rows[0]
        layer = sample[3] or data.get('layer')
        color = data.get('c') or sample[4] or sample[5]
        if color == "#000000":
            color = "#FFFFFF"

        inserted_for_handle = 0
        for idx in range(0, len(points), 2):
            p1, p2 = points[idx], points[idx + 1]
            if abs(p1[0] - p2[0]) <= 1e-12 and abs(p1[1] - p2[1]) <= 1e-12:
                continue
            insert_rows.append((
                _gpkg_linestring_blob([p1, p2]),
                layer,
                "AcDbEntity:AcDbDimension:AcDbDimensionLine",
                f"{handle}_DIMLINE_{idx // 2}",
                color,
            ))
            inserted_for_handle += 1

        if inserted_for_handle:
            point_rowids_to_delete.extend(
                row[0]
                for row in rows
                if "Text" not in str(row[1] or "")
                and "MText" not in str(row[1] or "")
                and "Attribute" not in str(row[1] or "")
            )

        definition = data['definition']
        if '11' in definition and '21' in definition:
            text_point = _transform_points_with_gdal([(definition['11'], definition['21'])], source_srs)
            if text_point:
                text_updates.append((_gpkg_point_blob(text_point[0]), handle))

    if insert_rows:
        c.executemany(
            """
            INSERT INTO entities (geom, Layer, SubClasses, EntityHandle, line_color)
            VALUES (?, ?, ?, ?, ?)
            """,
            insert_rows,
        )
    if text_updates:
        c.executemany(
            """
            UPDATE entities
            SET geom=?
            WHERE EntityHandle=?
              AND (SubClasses LIKE '%Text%' OR SubClasses LIKE '%MText%' OR SubClasses LIKE '%Attribute%')
            """,
            text_updates,
        )
    if point_rowids_to_delete:
        c.executemany("DELETE FROM entities WHERE rowid=?", [(rowid,) for rowid in point_rowids_to_delete])
    if insert_rows or text_updates:
        print(
            f"Expanded {len(insert_rows)} DIMENSION line entities, "
            f"repositioned {len(text_updates)} dimension texts, "
            f"removed {len(point_rowids_to_delete)} degraded dimension fragments"
        )


def clear_dimension_trace_fills(
    conn: sqlite3.Connection,
    cols: list[str],
    attrs_map: dict[str, dict],
) -> None:
    """Keep DIMENSION arrow/marker fragments, but do not render their TRACE fills as blobs."""
    if 'fill_color' not in cols or 'EntityHandle' not in cols or 'SubClasses' not in cols:
        return

    dimension_handles = [
        handle
        for handle, data in attrs_map.items()
        if data.get('type') == 'DIMENSION'
    ]
    if not dimension_handles:
        return

    c = conn.cursor()
    c.execute("CREATE TEMPORARY TABLE IF NOT EXISTS dimension_handles (handle TEXT PRIMARY KEY)")
    c.execute("DELETE FROM dimension_handles")
    c.executemany("INSERT OR IGNORE INTO dimension_handles(handle) VALUES (?)", [(h,) for h in dimension_handles])
    c.execute(
        """
        UPDATE entities
        SET fill_color=NULL
        WHERE EntityHandle IN (SELECT handle FROM dimension_handles)
          AND SubClasses LIKE '%AcDbTrace%'
        """
    )
    cleared = c.rowcount
    c.execute("DROP TABLE dimension_handles")
    if cleared:
        print(f"Cleared fill from {cleared} DIMENSION trace fragments")


def expand_hatch_patterns_to_lines(gpkg_path: Path, dxf_path: Path) -> bool:
    """Append approximate vector hatch pattern linework for non-solid DXF hatches."""
    if not gpkg_path.exists() or not dxf_path.exists():
        return False

    hatch_patterns = extract_dxf_hatch_patterns(dxf_path)
    if not hatch_patterns:
        return False

    conn = sqlite3.connect(gpkg_path)
    inserted = 0
    try:
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
        c.execute("PRAGMA table_info(entities)")
        cols = {row[1] for row in c.fetchall()}
        required = {"fid", "geom", "Layer", "SubClasses", "EntityHandle", "line_color"}
        if not required.issubset(cols):
            return False

        matched_handles = set(hatch_patterns.keys())
        cleared_fills = 0
        if matched_handles and "fill_color" in cols:
            placeholders = ",".join(["?"] * len(matched_handles))
            c.execute(
                f"""
                UPDATE entities
                SET fill_color=NULL
                WHERE EntityHandle IN ({placeholders})
                  AND SubClasses LIKE '%AcDbHatch%'
                """,
                list(matched_handles),
            )
            cleared_fills = c.rowcount

        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rtree_entities_geom'")
        if not c.fetchone():
            conn.commit()
            print(f"HATCH pattern expansion skipped: missing spatial index, cleared {cleared_fills} hatch fills")
            return cleared_fills > 0

        c.execute(
            """
            SELECT e.EntityHandle, e.Layer, e.line_color, r.minx, r.miny, r.maxx, r.maxy
            FROM entities e
            JOIN rtree_entities_geom r ON r.id = e.fid
            WHERE e.SubClasses LIKE '%AcDbHatch%' AND e.EntityHandle IS NOT NULL
            """
        )
        rows = c.fetchall()
        insert_rows = []
        expanded_handles: set[str] = set()
        for handle, layer, line_color, min_x, min_y, max_x, max_y in rows:
            hatch = hatch_patterns.get(str(handle))
            if not hatch:
                continue
            expanded_handles.add(str(handle))
            bbox = (float(min_x), float(min_y), float(max_x), float(max_y))
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            if width <= 0 or height <= 0:
                continue

            diagonal = math.hypot(width, height)
            pattern = hatch["pattern"]
            base_spacing = max(diagonal / 60.0, min(width, height) / 12.0)
            if pattern in {"ANSI31", "ANSI36", "ANGLE", "STEEL"}:
                angles = [float(hatch.get("angle") or 0.0)]
                if pattern in {"ANGLE", "STEEL"}:
                    angles.append(angles[0] + 90.0)
                for angle in angles:
                    for points in _generate_parallel_hatch_lines(bbox, angle, base_spacing):
                        insert_rows.append(
                            (
                                _gpkg_linestring_blob(points),
                                layer,
                                False,
                                "AcDbEntity:AcDbLine:AcDbHatchPattern",
                                "CONTINUOUS",
                                f"{handle}_HATCH_{inserted}",
                                line_color or "#FFFFFF",
                                None,
                            )
                        )
                        inserted += 1
            elif pattern in {"GRAVEL", "GRAVL1", "AR-SAND"}:
                spacing = max(diagonal / 45.0, min(width, height) / 8.0)
                for points in _generate_gravel_hatch_lines(bbox, spacing):
                    insert_rows.append(
                        (
                            _gpkg_linestring_blob(points),
                            layer,
                            False,
                            "AcDbEntity:AcDbLine:AcDbHatchPattern",
                            "CONTINUOUS",
                            f"{handle}_HATCH_{inserted}",
                            line_color or "#FFFFFF",
                            None,
                        )
                    )
                    inserted += 1

            if len(insert_rows) > 10000:
                c.executemany(
                    """
                    INSERT INTO entities(geom, Layer, PaperSpace, SubClasses, Linetype, EntityHandle, line_color, fill_color)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    insert_rows,
                )
                insert_rows.clear()

        if insert_rows:
            c.executemany(
                """
                INSERT INTO entities(geom, Layer, PaperSpace, SubClasses, Linetype, EntityHandle, line_color, fill_color)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                insert_rows,
            )
        conn.commit()
    except Exception as e:
        print(f"HATCH pattern expansion warning: {e}")
        return False
    finally:
        conn.close()

    if inserted:
        print(f"Expanded {inserted} HATCH pattern line entities, cleared {cleared_fills} hatch fills")
    elif cleared_fills:
        print(f"Cleared {cleared_fills} non-solid HATCH fills; no pattern lines were generated")
    return inserted > 0 or cleared_fills > 0


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

def convert_dwg_to_gpkg(
    dwg_path: Path,
    output_dir: Path,
    progress_callback=None,
    coordinate_system_code: str | None = None,
    gauss_kruger_zone: int | None = None,
) -> tuple[bool, Path | None, str]:
    job_id = output_dir.name
    source_suffix = dwg_path.suffix.lower()
    is_dxf_source = source_suffix == ".dxf"
    temp_dwg = None if is_dxf_source else output_dir / f"temp_{job_id}.dwg"
    dxf_path = output_dir / f"{dwg_path.stem}.dxf"
    gpkg_path = output_dir / f"{dwg_path.stem}.gpkg"
    
    if progress_callback: progress_callback(10, "Initializing...")
    
    if is_dxf_source:
        if dwg_path.resolve() != dxf_path.resolve():
            try:
                shutil.copy2(dwg_path, dxf_path)
            except Exception as e:
                return False, None, f"Failed to create temp file: {e}"
        if progress_callback: progress_callback(20, "Processing DXF...")
    else:
        # 1. Copy to temp ASCII name if needed
        try:
            shutil.copy2(dwg_path, temp_dwg)
        except Exception as e:
            return False, None, f"Failed to create temp file: {e}"
            
        # 2. DWG -> DXF
        if progress_callback: progress_callback(20, "Converting DWG to DXF...")
        # Use -y to overwrite if exists
        cmd_dxf = [settings.dwg2dxf_cmd, "-y", "-o", str(dxf_path), str(temp_dwg)]
        ok, err = _run(cmd_dxf, cwd=output_dir)
        if not ok:
            if temp_dwg and temp_dwg.exists(): temp_dwg.unlink()
            return False, None, f"LibreDWG conversion failed: {err}"
            
        if temp_dwg and temp_dwg.exists(): temp_dwg.unlink()
    
    # 3. Repair Encoding (Stream processing)
    if progress_callback: progress_callback(40, "正在修复编码...")
    try:
        repair_dxf_encoding(dxf_path)
    except Exception as e:
        print(f"Encoding repair warning: {e}")
    
    # 4. Parse Layers
    if progress_callback: progress_callback(50, "正在解析图层...")
    dxf_layer_states = parse_dxf_layer_states(dxf_path)
    dwg_layer_states = {} if is_dxf_source else parse_dwg_layer_states(dwg_path)
    layer_states = dxf_layer_states
    if dwg_layer_states:
        layer_states = {
            layer_name: {
                "visible": dwg_state.get("visible", True),
                "color": dxf_layer_states.get(layer_name, {}).get("color"),
            }
            for layer_name, dwg_state in dwg_layer_states.items()
        }
        for layer_name, dxf_state in dxf_layer_states.items():
            if layer_name not in layer_states:
                layer_states[layer_name] = dxf_state

    layer_colors = {
        layer_name: state["color"]
        for layer_name, state in layer_states.items()
        if state.get("color")
    }
    
    # 5. DXF -> GPKG
    if progress_callback: progress_callback(60, "正在将 DXF 转换为 GeoPackage...")
    cmd_gpkg = [
        settings.ogr2ogr_cmd,
        "--config", "DXF_FEATURE_LIMIT_PER_BLOCK", "-1",
        "--config", "DXF_ENCODING", "UTF-8",
        "--config", "DXF_MERGE_BLOCK_GEOMETRIES", "FALSE",
        "--config", "DXF_INLINE_BLOCKS", "TRUE",
        "--config", "DXF_ATTRIBUTES", "TRUE",
        "-f", "GPKG",
        str(gpkg_path),
        str(dxf_path),
        "-skipfailures",
        "-lco", "GEOMETRY_NAME=geom"
    ]
    
    # Add Gauss-Kruger to WGS84 transform when enabled.
    source_srs = None
    source_label = None
    if settings.enable_gauss_kruger_transform:
        try:
            source_srs, source_label = _build_source_srs_for_conversion(coordinate_system_code, gauss_kruger_zone)
        except CoordinateSystemError as e:
            return False, None, str(e)

        target_srs = "EPSG:4326"
        cmd_gpkg.extend([
            "-s_srs", source_srs,
            "-t_srs", target_srs
        ])
        print(f"鍚敤楂樻柉 - 鍏嬪悤鏍兼姇褰辫浆鎹細{source_label}, source_srs={source_srs}")

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
    count = check_gpkg_count(gpkg_path)
    # Threshold increased to 500 to catch cases where only few entities (like border) are converted
    # but the main content (in blocks) is missing.
    if ok and count < 500:
         print(f"Initial conversion resulted in only {count} entities. Retrying without inline blocks...")
         
         # Backup original GPKG just in case retry is worse
         gpkg_backup = gpkg_path.with_suffix(".gpkg.bak")
         try:
             shutil.copy2(gpkg_path, gpkg_backup)
         except: pass

         # Retry with DXF_INLINE_BLOCKS=FALSE (sometimes better for messy blocks)
         cmd_retry = list(cmd_gpkg)
         # Find and replace config
         for i, arg in enumerate(cmd_retry):
             if arg == "DXF_INLINE_BLOCKS":
                 cmd_retry[i+1] = "FALSE"
         
         ok_retry, err_retry = _run(cmd_retry, cwd=output_dir, timeout=3600)
         
         # Compare results
         count_retry = check_gpkg_count(gpkg_path)
         print(f"Retry result: {count_retry} entities")
         
         if not ok_retry or count_retry <= count:
             print("Retry was worse or failed, reverting to original...")
             try:
                 if gpkg_backup.exists():
                     shutil.move(gpkg_backup, gpkg_path)
             except: pass
         else:
             # Retry was better, keep it
             # Clean backup
             if gpkg_backup.exists():
                 try: gpkg_backup.unlink()
                 except: pass
             ok = ok_retry
             err = err_retry

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
        if progress_callback: progress_callback(70, "正在解析实体属性（对齐/旋转/颜色/线宽）...")
        try:
            if not layer_colors:
                print("Warning: No layer colors found")
            
            attrs_map = extract_dxf_attributes(dxf_path)
            if attrs_map:
                # Prepare data
                anchors = []
                aligned_text_points = []
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

                    if (
                        source_srs
                        and v.get('type') == 'TEXT'
                        and 'align_x_raw' in v
                        and 'align_y_raw' in v
                    ):
                        aligned_text_points.append((k, v['align_x_raw'], v['align_y_raw']))
                    
                    # Shifts
                    if (
                        'dx' in v
                        and v.get('type') != 'DIMENSION'
                        and not (
                            source_srs
                            and v.get('type') == 'TEXT'
                            and 'align_x_raw' in v
                            and 'align_y_raw' in v
                        )
                    ):
                        shifts.append((v['dx'], v['dy'], k))
                        
                    # Sizes
                    if 'h' in v and v['h'] > 0:
                        sizes.append((v['h'], k))
                        
                    # Rotations
                    if 'r' in v:
                        rotations.append((v['r'], k))
                        
                    # Colors (Explicit > ByLayer)
                    color = None
                    if 'c' in v:
                        color = v['c']
                    elif 'layer' in v and v['layer'] in layer_colors:
                        # Use Layer Color if Entity Color is missing (ByLayer)
                        color = layer_colors[v['layer']]
                        
                    if color:
                        if color == "#000000": color = "#FFFFFF"
                        
                        if v['type'] in ('TEXT', 'MTEXT'):
                            text_colors.append((color, k))
                        else:
                            line_colors.append((color, k))
                            
                    # Fill Colors (Hatch/Solid)
                    fill = None
                    if 'fill' in v:
                        fill = v['fill']
                    elif v['type'] in ('HATCH', 'SOLID', 'TRACE') and color:
                        # Use line color (explicit or layer) as fill if explicit fill is missing
                        fill = color
                        
                    if fill:
                        # Handle colors for Black Background (Dark Mode)
                        if fill == "#000000": 
                            fill = "#FFFFFF"
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

                # GDAL emits some justified TEXT points at their insertion point, while CAD
                # viewers use the raw 11/21 alignment point. Transform that point explicitly
                # instead of adding projected-unit offsets to already reprojected geometries.
                if aligned_text_points:
                    try:
                        raw_points = [(x, y) for _, x, y in aligned_text_points]
                        transformed_points = _transform_points_with_gdal(raw_points, source_srs)
                        if len(transformed_points) == len(aligned_text_points):
                            print(f"Applying transformed text alignment to {len(aligned_text_points)} text entities...")
                            geom_updates = [
                                (_gpkg_point_blob(point), handle)
                                for (handle, _, _), point in zip(aligned_text_points, transformed_points)
                            ]
                            c.executemany(
                                "UPDATE entities SET geom=? WHERE EntityHandle=?",
                                geom_updates,
                            )
                        else:
                            print("Text alignment transform skipped: transformed point count mismatch")
                    except Exception as e:
                        print(f"Text alignment transform warning: {e}")
                
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
                        except Exception:
                            pass

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

                try:
                    clear_dimension_trace_fills(conn, cols, attrs_map)
                except Exception as e:
                    print(f"DIMENSION trace fill cleanup warning: {e}")
                
                # Update Full Text (New - Fix truncation issues)
                # We collect full text from DXF (Group 3 + Group 1) and overwrite the potentially truncated text in GPKG
                full_texts = []
                for h, d in attrs_map.items():
                    if 't' in d:
                        full_texts.append((d['t'], h))
                
                if full_texts:
                    try:
                        if 'Text' in cols:
                            c.executemany(
                                """
                                UPDATE entities
                                SET Text=?
                                WHERE EntityHandle=?
                                  AND (SubClasses LIKE '%Text%' OR SubClasses LIKE '%MText%')
                                """,
                                full_texts,
                            )
                        if 'text_content' in cols:
                            c.executemany(
                                """
                                UPDATE entities
                                SET text_content=?
                                WHERE EntityHandle=?
                                  AND (SubClasses LIKE '%Text%' OR SubClasses LIKE '%MText%')
                                """,
                                full_texts,
                            )
                    except Exception as e:
                        print(f"Full text update error: {e}")

        except Exception as e:
            print(f"Attribute parsing warning: {e}")

        try:
            text_updates = []
            if 'Text' in cols:
                c.execute("SELECT rowid, Text FROM entities WHERE Text LIKE '%\\%' OR Text LIKE '%{%'")
                for rid, value in c.fetchall():
                    cleaned = clean_mtext_content(value)
                    if cleaned != value:
                        text_updates.append((cleaned, rid))
                if text_updates:
                    c.executemany("UPDATE entities SET Text=? WHERE rowid=?", text_updates)

            if 'text_content' in cols:
                content_updates = []
                c.execute("SELECT rowid, text_content FROM entities WHERE text_content LIKE '%\\%' OR text_content LIKE '%{%'")
                for rid, value in c.fetchall():
                    cleaned = clean_mtext_content(value)
                    if cleaned != value:
                        content_updates.append((cleaned, rid))
                if content_updates:
                    c.executemany("UPDATE entities SET text_content=? WHERE rowid=?", content_updates)
        except Exception as e:
            print(f"MTEXT cleanup warning: {e}")

        if 'SubClasses' in cols:
            try:
                assignments = []
                if 'Text' in cols:
                    assignments.append("Text=NULL")
                if 'text_content' in cols:
                    assignments.append("text_content=NULL")
                if assignments:
                    c.execute(
                        f"""
                        UPDATE entities
                        SET {', '.join(assignments)}
                        WHERE SubClasses NOT LIKE '%Text%'
                          AND SubClasses NOT LIKE '%MText%'
                          AND SubClasses NOT LIKE '%Attribute%'
                        """
                    )
            except Exception as e:
                print(f"Non-text entity text cleanup warning: {e}")

        try:
            clean_duplicate_and_control_text_entities(conn, cols)
        except Exception as e:
            print(f"Control text cleanup warning: {e}")
            
        # 8. Decode Multibyte Text (MIF \M+nXXXX)
        # This handles cases where GDAL/LibreDWG didn't decode the specific codepage (e.g. GBK \M+5xxxx)
        if 'Text' in cols:
             if progress_callback: progress_callback(75, "正在解析特殊字符...")
             try:
                 c.execute("SELECT rowid, Text FROM entities WHERE Text LIKE '%\\M+%' ESCAPE '!'")
                 rows = c.fetchall()
                 if rows:
                     print(f"Found {len(rows)} entities with potential encoded text")
                     updates = []
                     import re
                     # Regex for \M+nXXXX (n=digit, XXXX=hex)
                     pattern = re.compile(r'\\M\+([0-9])([0-9A-Fa-f]{4})', re.IGNORECASE)
                     
                     codepages = {
                        '1': 'cp1252', # ANSI
                        '2': 'cp932',  # Shift-JIS
                        '3': 'cp949',  # Hangul
                        '5': 'gbk',    # GBK (CP936)
                        '7': 'big5'    # Big5
                     }

                     def replace_match_wrapper(match):
                        cp_digit = match.group(1)
                        hex_str = match.group(2)
                        # Default to GBK (5) if unknown
                        enc_name = codepages.get(cp_digit, 'gbk')
                        try:
                            # Convert hex string (4 chars) to bytes (2 bytes)
                            byte_data = bytes.fromhex(hex_str)
                            return byte_data.decode(enc_name)
                        except Exception:
                            return match.group(0)

                     for rid, txt in rows:
                         if not txt: continue
                         try:
                             new_txt = pattern.sub(replace_match_wrapper, txt)
                             if new_txt != txt:
                                 updates.append((new_txt, rid))
                         except Exception: pass
                     
                     if updates:
                         print(f"Decoded {len(updates)} text entities")
                         c.executemany("UPDATE entities SET Text=? WHERE rowid=?", updates)
                         # Also update text_content if it exists
                         if 'text_content' in cols:
                             c.executemany("UPDATE entities SET text_content=? WHERE rowid=?", updates)
                             
             except Exception as e:
                 print(f"Text decoding error: {e}")

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

        try:
            clean_duplicate_and_control_text_entities(conn, cols)
        except Exception as e:
            print(f"Final control text cleanup warning: {e}")

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
    if progress_callback: progress_callback(85, "正在清理坐标...")
    try:
        sanitize_coordinates(gpkg_path)
    except Exception as e:
        print(f"Sanitization warning: {e}")

    # Keep GDAL's original CAD interpretation for high-risk geometry such as
    # hatches and DIMENSION arrow fragments. Expanding them here caused visual
    # regressions on valid annotation symbols.

    # Normalize coordinates (optional - disabled to preserve original DWG coordinates)
    # if progress_callback: progress_callback(90, "正在归一化坐标...")
    # try:
    #     normalize_coordinates(gpkg_path)
    # except Exception as e:
    #     print(f"Normalization warning: {e}")
        
    # Force Repack GPKG to fix Spatial Index (RTree) after direct SQLite modifications
    # This ensures GeoServer can properly query the data
    try:
        if progress_callback: progress_callback(95, "正在重新打包 GeoPackage...")
        repack_gpkg(gpkg_path)
    except Exception as e:
        print(f"Repack warning: {e}")

    if progress_callback: progress_callback(100, "转换完成")
    try:
        write_layer_metadata(gpkg_path, layer_states)
    except Exception as e:
        print(f"Layer metadata persistence warning: {e}")

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


def clean_gpkg_for_vector_preview(gpkg_path: Path) -> bool:
    """Legacy hook kept for compatibility; high-fidelity mode preserves layers."""
    return False


def apply_layer_visibility_override(gpkg_path: Path, visible_layers: list[str] | None) -> bool:
    """Persist the user's selected visible layers into layer_metadata."""
    if not gpkg_path.exists() or visible_layers is None:
        return False

    try:
        def normalize_layer_name(value: str) -> str:
            # Preserve exact-match behavior, but tolerate legacy whitespace and
            # full-width/compatibility variants that often appear in CAD exports.
            normalized = unicodedata.normalize("NFKC", value)
            normalized = re.sub(r"\s+", "", normalized)
            return normalized.casefold().strip()

        visible_set = {layer.strip() for layer in visible_layers if layer and layer.strip()}
        normalized_visible_set = {normalize_layer_name(layer) for layer in visible_set}
        conn = sqlite3.connect(gpkg_path)
        try:
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='layer_metadata'")
            if not c.fetchone():
                return False

            c.execute("SELECT layer_name FROM layer_metadata")
            existing_layers = [row[0] for row in c.fetchall()]
            if not existing_layers:
                return False

            if not visible_set:
                c.execute("UPDATE layer_metadata SET visible = 0")
            else:
                matched_layers = [layer for layer in existing_layers if layer in visible_set]
                if not matched_layers:
                    matched_layers = [
                        layer
                        for layer in existing_layers
                        if normalize_layer_name(layer) in normalized_visible_set
                    ]
                if not matched_layers:
                    return False
                c.execute("UPDATE layer_metadata SET visible = 0")
                placeholders = ",".join(["?"] * len(matched_layers))
                c.execute(
                    f"UPDATE layer_metadata SET visible = 1 WHERE layer_name IN ({placeholders})",
                    matched_layers,
                )

            conn.commit()
            return True
        finally:
            conn.close()
    except Exception as e:
        print(f"Layer visibility override warning: {e}")
        return False

def get_gpkg_bbox(gpkg_path: Path) -> tuple[bool, list[float] | None]:
    try:
        conn = sqlite3.connect(gpkg_path)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='layer_metadata'")
        has_layer_meta = c.fetchone() is not None
        if has_layer_meta:
            c.execute("PRAGMA table_info(entities)")
            entity_cols = [r[1] for r in c.fetchall()]
            if "Layer" in entity_cols:
                c.execute("SELECT layer_name FROM layer_metadata WHERE visible=1 ORDER BY layer_name")
                visible_layers = [row[0] for row in c.fetchall()]
                if visible_layers:
                    pk_col = None
                    c.execute("PRAGMA table_info(entities)")
                    for row in c.fetchall():
                        if row[5] == 1:
                            pk_col = row[1]
                            break
                    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rtree_entities_geom'")
                    has_rtree = c.fetchone() is not None
                    if pk_col and has_rtree and all(ch.isalnum() or ch == "_" for ch in pk_col):
                        placeholders = ",".join(["?"] * len(visible_layers))
                        sql = f"""
                            SELECT MIN(r.minx), MIN(r.miny), MAX(r.maxx), MAX(r.maxy)
                            FROM rtree_entities_geom r
                            WHERE r.id IN (
                                SELECT {pk_col}
                                FROM entities
                                WHERE Layer IN ({placeholders}) AND geom IS NOT NULL
                            )
                        """
                        c.execute(sql, visible_layers)
                        row = c.fetchone()
                        if row and all(x is not None for x in row):
                            conn.close()
                            return True, list(row)
        c.execute("SELECT min_x, min_y, max_x, max_y FROM gpkg_contents WHERE table_name='entities'")
        row = c.fetchone()
        conn.close()
        if row and all(x is not None for x in row):
            return True, list(row)

        exact_bbox = _get_exact_gpkg_bbox(gpkg_path)
        if exact_bbox:
            _write_gpkg_bbox(gpkg_path, exact_bbox)
            return True, exact_bbox
        return False, None
    except Exception:
        return False, None


def _get_exact_gpkg_bbox(gpkg_path: Path) -> list[float] | None:
    """Compute the exact bbox from entity geometries."""
    try:
        csv_path = gpkg_path.with_suffix(".bbox_exact.csv")
        if csv_path.exists():
            try:
                csv_path.unlink()
            except Exception:
                pass

        cmd = [
            settings.ogr2ogr_cmd,
            "-f",
            "CSV",
            str(csv_path),
            str(gpkg_path),
            "-dialect",
            "SQLite",
            "-sql",
            "SELECT MIN(ST_MinX(geom)) AS min_x, MIN(ST_MinY(geom)) AS min_y, MAX(ST_MaxX(geom)) AS max_x, MAX(ST_MaxY(geom)) AS max_y FROM entities WHERE geom IS NOT NULL",
        ]

        ok, _ = _run(cmd)
        if not ok or not csv_path.exists():
            return None

        try:
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
        finally:
            try:
                csv_path.unlink()
            except Exception:
                pass

        if len(rows) < 2:
            return None

        values = rows[1]
        if len(values) < 4:
            return None

        bbox: list[float] = []
        for value in values[:4]:
            value = value.strip()
            if not value or value.upper() == "NULL":
                return None
            bbox.append(float(value))

        return bbox
    except Exception:
        return None


def _write_gpkg_bbox(gpkg_path: Path, bbox: list[float]) -> bool:
    """Persist bbox into gpkg_contents so later reads stay consistent."""
    if not bbox or len(bbox) != 4:
        return False

    try:
        conn = sqlite3.connect(gpkg_path)
        try:
            c = conn.cursor()
            c.execute(
                """
                UPDATE gpkg_contents
                SET min_x = ?, min_y = ?, max_x = ?, max_y = ?
                WHERE table_name = 'entities'
                """,
                (bbox[0], bbox[1], bbox[2], bbox[3]),
            )
            conn.commit()
            return c.rowcount > 0
        finally:
            conn.close()
    except Exception:
        return False

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


def get_view_bbox(gpkg_path: Path) -> list[float] | None:
    """Find a CAD-like default view bbox, preferring drawing frames over outliers."""
    frame_bbox = _detect_frame_bbox(gpkg_path)
    if frame_bbox:
        return frame_bbox

    robust = get_robust_bbox(gpkg_path)
    if robust:
        min_x, max_x, min_y, max_y, *_ = robust
        if _is_valid_bbox([min_x, min_y, max_x, max_y]):
            return [min_x, min_y, max_x, max_y]

    ok, bbox = get_gpkg_bbox(gpkg_path)
    return bbox if ok else None


def _is_valid_bbox(bbox: list[float] | tuple[float, float, float, float] | None) -> bool:
    if not bbox or len(bbox) != 4:
        return False
    min_x, min_y, max_x, max_y = bbox
    if not all(math.isfinite(v) for v in (min_x, min_y, max_x, max_y)):
        return False
    return max_x > min_x and max_y > min_y


def _detect_frame_bbox(gpkg_path: Path) -> list[float] | None:
    """Heuristically detect a drawing frame from large rectangular CAD entities."""
    try:
        conn = sqlite3.connect(gpkg_path)
        try:
            c = conn.cursor()
            c.execute("PRAGMA table_info(entities)")
            cols = {row[1] for row in c.fetchall()}
            if "geom" not in cols:
                return None

            pk_col = None
            c.execute("PRAGMA table_info(entities)")
            for row in c.fetchall():
                if row[5] == 1:
                    pk_col = row[1]
                    break

            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rtree_entities_geom'")
            has_rtree = c.fetchone() is not None
            if not pk_col or not has_rtree or not all(ch.isalnum() or ch == "_" for ch in pk_col):
                return None

            layer_expr = "e.Layer" if "Layer" in cols else "''"
            subclass_expr = "e.SubClasses" if "SubClasses" in cols else "''"
            text_expr = "e.Text" if "Text" in cols else "NULL"
            sql = f"""
                SELECT
                    e.{pk_col},
                    {layer_expr} AS layer_name,
                    {subclass_expr} AS subclasses,
                    {text_expr} AS text_value,
                    r.minx,
                    r.miny,
                    r.maxx,
                    r.maxy
                FROM entities e
                JOIN rtree_entities_geom r ON r.id = e.{pk_col}
                WHERE e.geom IS NOT NULL
            """
            c.execute(sql)
            rows = c.fetchall()
        finally:
            conn.close()

        items = []
        for _, layer_name, subclasses, text_value, min_x, min_y, max_x, max_y in rows:
            try:
                bbox = [float(min_x), float(min_y), float(max_x), float(max_y)]
            except Exception:
                continue
            if not _is_valid_bbox(bbox):
                continue
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            area = width * height
            items.append(
                {
                    "bbox": bbox,
                    "layer": str(layer_name or ""),
                    "subclasses": str(subclasses or ""),
                    "text": str(text_value or ""),
                    "width": width,
                    "height": height,
                    "area": area,
                    "cx": (bbox[0] + bbox[2]) / 2,
                    "cy": (bbox[1] + bbox[3]) / 2,
                }
            )

        if len(items) < 8:
            return None

        all_bbox = _merge_bboxes([item["bbox"] for item in items])
        if not _is_valid_bbox(all_bbox):
            return None
        all_area = (all_bbox[2] - all_bbox[0]) * (all_bbox[3] - all_bbox[1])
        if all_area <= 0:
            return None

        max_item_area = max(item["area"] for item in items) or 1
        meaningful = [
            item
            for item in items
            if item["area"] > 0 and item["area"] >= max_item_area * 0.000002
        ]
        if not meaningful:
            meaningful = items

        candidates: list[tuple[float, list[float], str]] = []
        candidates.extend(_frame_candidates_from_entities(meaningful, all_area))
        candidates.extend(_frame_candidates_from_line_pairs(meaningful, all_area))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0], reverse=True)
        best_score, best_bbox, reason = candidates[0]
        if best_score < 4.0:
            return None

        print(f"Detected view bbox ({reason}, score={best_score:.2f}): {best_bbox}")
        return _pad_bbox(best_bbox, 0.015)
    except Exception as e:
        print(f"Frame bbox detection warning: {e}")
        return None


def _merge_bboxes(bboxes: list[list[float]]) -> list[float] | None:
    valid = [bbox for bbox in bboxes if _is_valid_bbox(bbox)]
    if not valid:
        return None
    return [
        min(bbox[0] for bbox in valid),
        min(bbox[1] for bbox in valid),
        max(bbox[2] for bbox in valid),
        max(bbox[3] for bbox in valid),
    ]


def _pad_bbox(bbox: list[float], ratio: float) -> list[float]:
    min_x, min_y, max_x, max_y = bbox
    width = max_x - min_x
    height = max_y - min_y
    pad_x = width * ratio
    pad_y = height * ratio
    return [min_x - pad_x, min_y - pad_y, max_x + pad_x, max_y + pad_y]


def _frame_word_score(text: str) -> float:
    value = text.lower()
    score = 0.0
    for token in ("图框", "内框", "外框", "图签", "标题栏", "图廓", "border", "frame", "title"):
        if token in value:
            score += 2.0
    return score


def _bbox_contains_ratio(outer: list[float], inner: list[float]) -> float:
    if not _is_valid_bbox(outer) or not _is_valid_bbox(inner):
        return 0.0
    ix1 = max(outer[0], inner[0])
    iy1 = max(outer[1], inner[1])
    ix2 = min(outer[2], inner[2])
    iy2 = min(outer[3], inner[3])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inner_area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    if inner_area <= 0:
        return 0.0
    return ((ix2 - ix1) * (iy2 - iy1)) / inner_area


def _candidate_score(candidate_bbox: list[float], items: list[dict], all_area: float, reason: str) -> float:
    if not _is_valid_bbox(candidate_bbox):
        return -1.0

    width = candidate_bbox[2] - candidate_bbox[0]
    height = candidate_bbox[3] - candidate_bbox[1]
    area = width * height
    if area <= 0 or all_area <= 0:
        return -1.0

    ratio = max(width, height) / max(min(width, height), 1e-12)
    area_ratio = area / all_area
    contained_count = 0
    contained_area = 0.0
    frame_words = _frame_word_score(reason)

    for item in items:
        contains = _bbox_contains_ratio(candidate_bbox, item["bbox"])
        if contains >= 0.60:
            contained_count += 1
            contained_area += item["area"]
            frame_words += _frame_word_score(item["layer"])

    count_ratio = contained_count / max(len(items), 1)
    contained_area_ratio = contained_area / max(sum(item["area"] for item in items), 1)

    score = 0.0
    score += min(count_ratio * 10.0, 6.0)
    score += min(contained_area_ratio * 4.0, 3.0)
    score += frame_words

    if 1.05 <= ratio <= 3.2:
        score += 2.0
    elif ratio <= 6.0:
        score += 0.8
    else:
        score -= 1.8

    if 0.03 <= area_ratio <= 0.96:
        score += 1.0
    if area_ratio < 0.01:
        score -= 3.0
    if area_ratio > 0.985:
        score -= 2.0

    return score


def _frame_candidates_from_entities(items: list[dict], all_area: float) -> list[tuple[float, list[float], str]]:
    candidates: list[tuple[float, list[float], str]] = []
    max_area = max(item["area"] for item in items) or 1

    for item in items:
        bbox = item["bbox"]
        width = item["width"]
        height = item["height"]
        if width <= 0 or height <= 0:
            continue

        ratio = max(width, height) / max(min(width, height), 1e-12)
        word_score = _frame_word_score(item["layer"])
        large_enough = item["area"] >= max_area * 0.02
        frame_like = "polygon" in item["subclasses"].lower() or "polyline" in item["subclasses"].lower()

        if not large_enough and word_score <= 0:
            continue
        if ratio > 8.0:
            continue

        reason = f"entity:{item['layer'] or 'unknown'}"
        score = _candidate_score(bbox, items, all_area, reason)
        if frame_like:
            score += 0.8
        if word_score:
            score += word_score
        candidates.append((score, bbox, reason))

    return candidates


def _frame_candidates_from_line_pairs(items: list[dict], all_area: float) -> list[tuple[float, list[float], str]]:
    """Build frame candidates from long horizontal/vertical line pairs."""
    widths = [item["width"] for item in items if item["width"] > 0]
    heights = [item["height"] for item in items if item["height"] > 0]
    if not widths or not heights:
        return []

    max_width = max(widths)
    max_height = max(heights)
    horizontals = [
        item
        for item in items
        if item["width"] >= max_width * 0.35 and item["height"] <= max(item["width"] * 0.015, max_height * 0.01)
    ]
    verticals = [
        item
        for item in items
        if item["height"] >= max_height * 0.35 and item["width"] <= max(item["height"] * 0.015, max_width * 0.01)
    ]

    candidates: list[tuple[float, list[float], str]] = []
    for top_index, line_a in enumerate(horizontals):
        for line_b in horizontals[top_index + 1:]:
            min_y = min(line_a["cy"], line_b["cy"])
            max_y = max(line_a["cy"], line_b["cy"])
            height = max_y - min_y
            if height <= 0:
                continue

            x1 = max(line_a["bbox"][0], line_b["bbox"][0])
            x2 = min(line_a["bbox"][2], line_b["bbox"][2])
            if x2 <= x1:
                x1 = min(line_a["bbox"][0], line_b["bbox"][0])
                x2 = max(line_a["bbox"][2], line_b["bbox"][2])
            width = x2 - x1
            if width <= 0:
                continue

            ratio = max(width, height) / max(min(width, height), 1e-12)
            if ratio > 6.0:
                continue

            bbox = [x1, min_y, x2, max_y]
            score = _candidate_score(bbox, items, all_area, "horizontal-pair")
            candidates.append((score, bbox, "horizontal-pair"))

    for left_index, line_a in enumerate(verticals):
        for line_b in verticals[left_index + 1:]:
            min_x = min(line_a["cx"], line_b["cx"])
            max_x = max(line_a["cx"], line_b["cx"])
            width = max_x - min_x
            if width <= 0:
                continue

            y1 = max(line_a["bbox"][1], line_b["bbox"][1])
            y2 = min(line_a["bbox"][3], line_b["bbox"][3])
            if y2 <= y1:
                y1 = min(line_a["bbox"][1], line_b["bbox"][1])
                y2 = max(line_a["bbox"][3], line_b["bbox"][3])
            height = y2 - y1
            if height <= 0:
                continue

            ratio = max(width, height) / max(min(width, height), 1e-12)
            if ratio > 6.0:
                continue

            bbox = [min_x, y1, max_x, y2]
            score = _candidate_score(bbox, items, all_area, "vertical-pair")
            candidates.append((score, bbox, "vertical-pair"))

    return candidates


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
    
    # Get original count for comparison
    original_count = check_gpkg_count(gpkg_path)

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
        filtered_count = check_gpkg_count(temp_shifted)
        
        # Check if we lost too many entities due to spatial filtering
        # If we kept < 20% of entities AND kept < 2000 entities, assume filtering was too aggressive
        ratio = filtered_count / original_count if original_count > 0 else 0
        
        if filtered_count > 0 and (ratio > 0.2 or filtered_count > 2000):
            shift_success = True
        else:
            print(f"Normalization (Shift+Filter) kept only {filtered_count}/{original_count} entities ({ratio:.1%}). Retrying without spatial filter...")
    
    # Retry without spatial filter if first attempt failed or was too aggressive
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
    """Extract layer names, representative colors and default visibility."""
    try:
        conn = sqlite3.connect(gpkg_path)
        c = conn.cursor()
        
        # Check if Layer column exists
        c.execute("PRAGMA table_info(entities)")
        cols = [r[1] for r in c.fetchall()]
        
        if 'Layer' not in cols:
            conn.close()
            return []

        layer_visibility = {}
        layer_colors_from_meta = {}
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='layer_metadata'")
        if c.fetchone():
            try:
                c.execute("SELECT layer_name, visible, color FROM layer_metadata")
                for layer_name, visible, color in c.fetchall():
                    layer_visibility[layer_name] = bool(visible)
                    if color:
                        layer_colors_from_meta[layer_name] = color
            except Exception as e:
                print(f"Error reading layer metadata: {e}")

        monitor_manifest = {
            entry.get("name"): entry
            for entry in get_gpkg_monitor_manifest(gpkg_path)
            if entry.get("name")
        }

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
            manifest_entry = monitor_manifest.get(layer, {})
            color = layer_colors_from_meta.get(layer) or layer_colors.get(layer, "#9ca3af")
            visible = layer_visibility.get(layer, True)
            kind = manifest_entry.get("kind")
            result.append({"name": layer, "color": color, "visible": visible, "kind": kind})

        conn.close()
        return result
    except Exception as e:
        print(f"Error getting layers: {e}")
        return []


def get_gpkg_monitor_manifest(gpkg_path: Path) -> list[dict]:
    """Extract monitor display manifest from a GeoPackage."""
    try:
        conn = sqlite3.connect(gpkg_path)
        c = conn.cursor()

        c.execute("PRAGMA table_info(entities)")
        cols = [r[1] for r in c.fetchall()]
        if "Layer" not in cols:
            conn.close()
            return []

        layer_visibility: dict[str, bool] = {}
        layer_colors_from_meta: dict[str, str] = {}
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='layer_metadata'")
        if c.fetchone():
            try:
                c.execute("SELECT layer_name, visible, color FROM layer_metadata")
                for layer_name, visible, color in c.fetchall():
                    layer_visibility[layer_name] = bool(visible)
                    if color:
                        layer_colors_from_meta[layer_name] = color
            except Exception as e:
                print(f"Error reading layer metadata for manifest: {e}")

        c.execute(
            """
            SELECT Layer, SubClasses, line_color, text_color
            FROM entities
            WHERE Layer IS NOT NULL
            """
        )

        line_markers = (
            "AcDbEntity:AcDbLine",
            "AcDbEntity:AcDbPolyline",
            "AcDbEntity:AcDbCircle",
            "AcDbEntity:AcDbCircle:AcDbArc",
            "AcDbEntity:AcDbHatch",
            "AcDbEntity:AcDbSpline",
            "AcDbEntity:AcDbLeader",
        )
        text_markers = (
            "AcDbEntity:AcDbText:AcDbText",
            "AcDbEntity:AcDbMText",
            "AcDbEntity:AcDbText:AcDbAttribute",
        )

        stats: dict[str, dict] = {}
        for layer_name, subclasses, line_color, text_color in c.fetchall():
            entry = stats.setdefault(
                layer_name,
                {
                    "subclasses": set(),
                    "line_colors": [],
                    "text_colors": [],
                },
            )
            if subclasses:
                entry["subclasses"].add(str(subclasses))
            if line_color:
                entry["line_colors"].append(str(line_color))
            if text_color:
                entry["text_colors"].append(str(text_color))

        def most_common(values: list[str], fallback: str | None = None) -> str | None:
            cleaned = [v for v in values if v]
            if not cleaned:
                return fallback
            return Counter(cleaned).most_common(1)[0][0]

        def infer_kind(subclasses: set[str]) -> str:
            has_line = any(any(marker in sc for marker in line_markers) for sc in subclasses)
            has_text = any(any(marker in sc for marker in text_markers) for sc in subclasses)
            if has_line and has_text:
                return "both"
            if has_text:
                return "text"
            return "line"

        manifest = []
        for layer_name in sorted(stats.keys()):
            entry = stats[layer_name]
            visible = layer_visibility.get(layer_name, True)
            kind = infer_kind(entry["subclasses"])
            fallback_color = layer_colors_from_meta.get(layer_name) or "#FFFFFF"
            line_color = most_common(entry["line_colors"], fallback_color) or fallback_color
            text_color = most_common(entry["text_colors"], line_color) or line_color
            manifest.append(
                {
                    "name": layer_name,
                    "visible": visible,
                    "kind": kind,
                    "lineColor": line_color,
                    "textColor": text_color,
                }
            )

        conn.close()
        return manifest
    except Exception as e:
        print(f"Error getting monitor manifest: {e}")
        return []
