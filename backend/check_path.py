from pathlib import Path
from app.config import settings
import os

print(f"Configured dwg2dxf_cmd: {settings.dwg2dxf_cmd}")
print(f"Exists: {os.path.exists(settings.dwg2dxf_cmd)}")
