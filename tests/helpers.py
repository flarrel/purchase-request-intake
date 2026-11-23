import tempfile
from pathlib import Path


def temporary_database_dir():
    runtime = Path(__file__).resolve().parents[2] / "runtime"
    runtime.mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(dir=runtime)
