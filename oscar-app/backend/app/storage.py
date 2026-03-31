"""Local filesystem storage for PDFs and extracted text."""
import os
from pathlib import Path
from app.config import settings


def _ensure_dir(path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def upload_bytes(object_name: str, data: bytes):
    path = os.path.join(settings.storage_dir, object_name)
    _ensure_dir(path)
    with open(path, "wb") as f:
        f.write(data)


def download_bytes(object_name: str) -> bytes:
    path = os.path.join(settings.storage_dir, object_name)
    with open(path, "rb") as f:
        return f.read()


def file_exists(object_name: str) -> bool:
    return os.path.exists(os.path.join(settings.storage_dir, object_name))


def get_file_path(object_name: str) -> str:
    return os.path.join(settings.storage_dir, object_name)


def setup_storage():
    """Create storage directories."""
    for subdir in ["pdfs", "text"]:
        Path(os.path.join(settings.storage_dir, subdir)).mkdir(parents=True, exist_ok=True)
    print(f"Storage directory ready: {settings.storage_dir}")
