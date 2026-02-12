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
    sys.exit(1)

gpkg_files = list(target_job.glob("*.gpkg"))
gpkg_path = gpkg_files[0]

conn = sqlite3.connect(gpkg_path)
c = conn.cursor()
c.execute("PRAGMA table_info(entities)")
cols = [r[1] for r in c.fetchall()]
print("Columns:", cols)
conn.close()
