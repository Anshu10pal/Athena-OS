"""Content-sniffing for topic resource uploads (Phase 5).

Never trust the client-declared extension: sniff the real type from bytes.
md and txt are content-identical (plain text) so there's no way to tell them
apart by sniffing alone -- the claimed filename extension only gets to break
that specific tie, after the content is already confirmed to be plain text.
It never decides pdf/docx/pptx/xlsx; those are always sniffed from bytes.
"""
import zipfile
from io import BytesIO
from typing import Optional

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

MIME_BY_EXT = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "md": "text/markdown",
    "txt": "text/plain",
}


def _sniff_office_kind(data: bytes) -> Optional[str]:
    if not data.startswith(b"PK\x03\x04"):
        return None
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        return None
    if "word/document.xml" in names:
        return "docx"
    if "ppt/presentation.xml" in names:
        return "pptx"
    if "xl/workbook.xml" in names:
        return "xlsx"
    return None


def _looks_like_text(data: bytes) -> bool:
    if not data or b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def resolve_upload_extension(filename: str, data: bytes) -> str:
    """One of pdf/docx/pptx/xlsx/md/txt from sniffed content.

    Raises ValueError if the content doesn't match any supported type.
    """
    if data[:5] == b"%PDF-":
        return "pdf"
    office = _sniff_office_kind(data)
    if office:
        return office
    if _looks_like_text(data):
        claimed = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return "md" if claimed == "md" else "txt"
    raise ValueError("File content doesn't match any supported type (pdf, docx, pptx, xlsx, md, txt)")
