import sqlite3
import sys
from pathlib import Path

# Correct path found previously
jobs_dir = Path(r"d:\project\LibreDWG\backend\data\jobs")
target_job = None
for job_dir in jobs_dir.iterdir():
    if job_dir.name.startswith("bf0ce2e3"):
        target_job = job_dir
        break

if not target_job:
    print("Could not find job directory")
    sys.exit(1)

gpkg_files = list(target_job.glob("*.gpkg"))
if not gpkg_files:
    print("No GPKG file found")
    sys.exit(1)

gpkg_path = gpkg_files[0]
print(f"Checking GPKG: {gpkg_path}")

try:
    conn = sqlite3.connect(gpkg_path)
    c = conn.cursor()
    # Check if 'style' column exists
    c.execute("PRAGMA table_info(entities)")
    cols = [r[1] for r in c.fetchall()]
    if 'style' not in cols:
        print("No 'style' column found")
        sys.exit(0)

    # Get some sample LABEL styles
    c.execute("SELECT style FROM entities WHERE style LIKE '%LABEL(%' LIMIT 10")
    rows = c.fetchall()
    print("\nSample LABEL styles:")
    for r in rows:
        print(r[0])
        
    conn.close()

except Exception as e:
    print(f"Error: {e}")
