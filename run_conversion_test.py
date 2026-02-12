import sys
import os
from pathlib import Path

# Add backend to path
sys.path.append(r"d:\project\LibreDWG\backend")

from app.services.conversion import convert_dwg_to_gpkg

def test_conversion():
    base = Path(r"d:\project\LibreDWG\backend\data\jobs")
    jobs = sorted([d for d in base.iterdir() if d.is_dir()], key=lambda x: x.stat().st_mtime, reverse=True)
    
    if not jobs:
        print("No jobs found")
        return

    job = jobs[0]
    dxf = job / "anteen.dxf"
    # We will write to a test output to avoid breaking the job if possible, 
    # but convert_dwg_to_gpkg writes to output_dir/stem.gpkg
    # So we can use a temp dir
    
    output_dir = job / "test_output"
    output_dir.mkdir(exist_ok=True)
    
    print(f"Converting {dxf} to {output_dir}")
    
    try:
        ok, gpkg, msg = convert_dwg_to_gpkg(dxf, output_dir, lambda p, m: print(f"[{p}%] {m}"))
        print(f"Result: {ok}, {gpkg}, {msg}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_conversion()
