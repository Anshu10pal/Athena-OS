"""Uploaded resource files: file_path is stored relative to settings.RESOURCES_DIR
(app/api/topics.py's write side) and joined back against the same setting on
read (app/api/resources.py). Both were previously relative-to-BACKEND_DIR;
moving RESOURCES_DIR outside BACKEND_DIR (see app/core/config.py) would have
silently broken downloads if the two sides ever drifted -- this pins them
to the same base without needing a full HTTP+auth harness for something this
mechanical.
"""
from pathlib import Path


def test_write_and_read_path_use_the_same_base(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "RESOURCES_DIR", str(tmp_path))

    # mirrors topics.py's upload_resource write side
    dest_dir = Path(settings.RESOURCES_DIR) / "some-module"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored_name = "abc123.pdf"
    (dest_dir / stored_name).write_bytes(b"%PDF-1.4 fake")
    file_path = str((dest_dir / stored_name).relative_to(Path(settings.RESOURCES_DIR)))

    # mirrors resources.py's download_resource read side
    full_path = Path(settings.RESOURCES_DIR) / file_path

    assert full_path.is_file()
    assert full_path.read_bytes() == b"%PDF-1.4 fake"
