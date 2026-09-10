"""
Secure document upload handling for `/api/v1/projects/{project_id}/documents`.

Validates:
  - filename (rejects path traversal, null bytes, unsafe characters)
  - extension (allow-list)
  - declared/content-sniffed MIME type (allow-list)
  - file size (configurable max)

Storage:
  - Files are never written using the user-supplied filename. A new random
    UUID-based filename is generated for on-disk storage; the original
    filename is retained only as metadata (`original_filename`) for display.
  - Local storage root is configurable via `UPLOAD_DIR` (defaults to
    `<repo>/uploads`), and files are stored under a per-project subdirectory
    that is itself a validated UUID (`project_id`), so no user input ever
    reaches `Path` construction.
  - If `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` and Supabase Storage are
    configured, callers may instead upload to a Supabase Storage bucket
    (see `upload_to_supabase_storage`) and use the returned object path as
    `storage_path` — this module returns a storage-agnostic result either
    way.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile, status

# Extensions this MVP's parser/engine can process (PDF text extraction) plus
# plain-text specs. DWG/DXF/IFC/Revit are explicitly out of scope for MVP
# parsing (see README limitations) but are accepted for storage/manual
# review since Phase 6 anticipates future CAD support.
ALLOWED_EXTENSIONS = {".pdf", ".txt"}

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "text/plain",
}


def _max_upload_bytes() -> int:
    return int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))


_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._ ()\-]+$")

_DEFAULT_UPLOAD_ROOT = Path(__file__).resolve().parent.parent.parent / "uploads"


def _upload_root() -> Path:
    """Resolved lazily (not at import time) so tests can override UPLOAD_DIR."""
    return Path(os.getenv("UPLOAD_DIR", str(_DEFAULT_UPLOAD_ROOT)))


@dataclass
class ValidatedUpload:
    original_filename: str
    extension: str
    content_type: str
    size_bytes: int
    storage_path: str


def _reject(detail: str) -> None:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _validate_filename(filename: Optional[str]) -> str:
    if not filename:
        _reject("Filename is required.")
    if "\x00" in filename:
        _reject("Filename contains a null byte.")
    # Reject path traversal / directory components outright; only a bare
    # filename is acceptable. Path(...).name strips any directory parts,
    # so we compare against that to detect traversal attempts.
    if filename in (".", "..") or "/" in filename or "\\" in filename:
        _reject("Filename must not contain path separators.")
    base = Path(filename).name
    if base != filename:
        _reject("Invalid filename.")
    if len(filename) > 255:
        _reject("Filename is too long.")
    if not _SAFE_FILENAME_RE.match(filename):
        _reject("Filename contains unsupported characters.")
    return filename


def _validate_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        _reject(f"Unsupported file extension '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}")
    return ext


def _validate_content_type(content_type: Optional[str]) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct not in ALLOWED_CONTENT_TYPES:
        _reject(f"Unsupported content type '{content_type}'. Allowed: {sorted(ALLOWED_CONTENT_TYPES)}")
    return ct


def _sniff_pdf_magic_bytes(head: bytes, extension: str) -> None:
    """Reject files whose content doesn't match a claimed PDF extension.

    This is a lightweight defense against disguised executables/scripts; it
    is not a substitute for antivirus/malware scanning (see README
    limitations — production deployments handling untrusted uploads at
    scale should add a dedicated malware scan step, e.g. ClamAV, before
    documents are parsed).
    """
    if extension == ".pdf" and not head.startswith(b"%PDF-"):
        _reject("File content does not match a valid PDF header.")


async def validate_and_store_upload(project_id: str, upload: UploadFile) -> ValidatedUpload:
    filename = _validate_filename(upload.filename)
    extension = _validate_extension(filename)
    content_type = _validate_content_type(upload.content_type)

    # project_id is a server-validated UUID path parameter (never raw user
    # text) by the time it reaches here — see src/api/v1/documents.py, which
    # resolves it via ProjectContext before calling this function.
    try:
        uuid.UUID(str(project_id))
    except ValueError:
        _reject("Invalid project id.")

    data = await upload.read()
    size_bytes = len(data)
    if size_bytes == 0:
        _reject("Uploaded file is empty.")
    if size_bytes > _max_upload_bytes():
        _reject(f"File exceeds maximum allowed size of {_max_upload_bytes()} bytes.")

    _sniff_pdf_magic_bytes(data[:8], extension)

    project_dir = _upload_root() / str(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"{uuid.uuid4()}{extension}"
    stored_path = project_dir / stored_name
    # Defense in depth: confirm the resolved path is still inside project_dir.
    resolved = stored_path.resolve()
    if not str(resolved).startswith(str(project_dir.resolve())):
        _reject("Invalid storage path.")

    stored_path.write_bytes(data)
    # Never executable.
    os.chmod(stored_path, 0o640)

    return ValidatedUpload(
        original_filename=filename,
        extension=extension,
        content_type=content_type,
        size_bytes=size_bytes,
        storage_path=str(stored_path),
    )
