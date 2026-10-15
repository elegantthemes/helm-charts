"""Run all offline session, chart-wiring and reader admission checks."""
from pathlib import Path
import subprocess
import sys

for script in ['check.py', 'render.py', 'reader.py']:
    subprocess.run([sys.executable, str(Path(__file__).with_name(script))], check=True)
