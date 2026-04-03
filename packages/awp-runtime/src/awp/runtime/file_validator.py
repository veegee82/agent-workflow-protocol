"""Output file validation for AWP workers.

Heuristic checks that detect placeholder / empty / corrupt output files
so workers get immediate feedback and can self-correct.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Raster images: a real chart/plot is typically >1 KB.
# A 1×1 transparent PNG pixel is ~68 B, a minimal GIF is ~43 B.
_RASTER_MIN_BYTES = 500
_PNG_MIN_WIDTH = 10
_PNG_MIN_HEIGHT = 10

# CSV / TSV: must have at least 1 data row beyond the header
_CSV_MIN_DATA_ROWS = 1

# Text-like: must have meaningful content
_TEXT_MIN_BYTES = 10

# JSON / YAML / XML: must be parseable and non-empty
_STRUCTURED_MIN_BYTES = 3

# Binary data files: must have a meaningful payload
_BINARY_DATA_MIN_BYTES = 100

# PDF: minimal valid PDF is ~67 bytes but a real document is larger
_PDF_MIN_BYTES = 200


# ---------------------------------------------------------------------------
# Magic-byte signatures for binary format detection
# ---------------------------------------------------------------------------

_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "PNG",
    b"\xff\xd8\xff": "JPEG",
    b"GIF87a": "GIF",
    b"GIF89a": "GIF",
    b"RIFF": "RIFF",  # WEBP starts with RIFF....WEBP
    b"BM": "BMP",
    b"II\x2a\x00": "TIFF-LE",
    b"MM\x00\x2a": "TIFF-BE",
    b"%PDF": "PDF",
    b"PK\x03\x04": "ZIP",  # xlsx, parquet (sometimes), zip archives
    b"PAR1": "PARQUET",
    b"\x93NUMPY": "NPY",
    b"\x80\x04\x95": "PICKLE4",  # pickle protocol 4
    b"\x80\x05\x95": "PICKLE5",  # pickle protocol 5
    b"\x89HDF": "HDF5",
}


def _detect_magic(path: Path, max_read: int = 16) -> str | None:
    """Read first bytes and return detected format name or None."""
    try:
        with open(path, "rb") as f:
            head = f.read(max_read)
    except OSError:
        return None
    for sig, name in _MAGIC.items():
        if head[: len(sig)] == sig:
            if name == "RIFF" and len(head) >= 12 and head[8:12] == b"WEBP":
                return "WEBP"
            return name
    return None


# ---------------------------------------------------------------------------
# Individual validators
# ---------------------------------------------------------------------------

def _validate_png(path: Path) -> str | None:
    """Return a warning string if the PNG is a placeholder, else None."""
    size = path.stat().st_size
    if size == 0:
        return (
            f"{path.name}: PNG file is empty (0 bytes). "
            "The file was created but no image data was written. "
            "Ensure plt.savefig() is called AFTER plotting actual data, "
            "and that the code did not error before reaching savefig()."
        )
    if size < _RASTER_MIN_BYTES:
        return (
            f"{path.name}: PNG is only {size} bytes — likely a 1×1 placeholder pixel. "
            f"Do NOT write base64-encoded placeholder PNGs as a fallback. "
            f"Instead, fix the plotting code so it generates a real chart. "
            f"Common causes: (1) matplotlib not installed — use pip.install first, "
            f"(2) empty DataFrame/Series passed to plot(), "
            f"(3) plt.savefig() called on a blank figure with no data plotted. "
            f"Minimum expected: {_RASTER_MIN_BYTES} bytes for a real plot."
        )
    # Read IHDR chunk to check dimensions
    try:
        with open(path, "rb") as f:
            header = f.read(24)
        if len(header) >= 24 and header[:8] == b"\x89PNG\r\n\x1a\n":
            width = struct.unpack(">I", header[16:20])[0]
            height = struct.unpack(">I", header[20:24])[0]
            if width < _PNG_MIN_WIDTH or height < _PNG_MIN_HEIGHT:
                return (
                    f"{path.name}: PNG dimensions are {width}\u00d7{height} pixels — "
                    f"too small to be a real chart (likely a placeholder). "
                    f"Do NOT generate 1×1 pixel fallback images. "
                    f"Fix the actual plotting code instead. "
                    f"Minimum: {_PNG_MIN_WIDTH}\u00d7{_PNG_MIN_HEIGHT}."
                )
    except Exception:
        pass
    return None


def _validate_jpeg(path: Path) -> str | None:
    """Return a warning if the JPEG is a placeholder or corrupt."""
    size = path.stat().st_size
    if size < _RASTER_MIN_BYTES:
        return (
            f"{path.name}: JPEG is only {size} bytes — likely a placeholder. "
            f"Minimum expected: {_RASTER_MIN_BYTES} bytes."
        )
    # Verify magic bytes
    try:
        with open(path, "rb") as f:
            if f.read(3) != b"\xff\xd8\xff":
                return f"{path.name}: File has .jpg extension but invalid JPEG header."
    except Exception:
        pass
    return None


def _validate_gif(path: Path) -> str | None:
    """Return a warning if the GIF is too small or has invalid header."""
    size = path.stat().st_size
    if size < _RASTER_MIN_BYTES:
        return (
            f"{path.name}: GIF is only {size} bytes — likely a placeholder. "
            f"Minimum expected: {_RASTER_MIN_BYTES} bytes."
        )
    try:
        with open(path, "rb") as f:
            sig = f.read(6)
        if sig not in (b"GIF87a", b"GIF89a"):
            return f"{path.name}: File has .gif extension but invalid GIF header."
    except Exception:
        pass
    return None


def _validate_webp(path: Path) -> str | None:
    """Return a warning if the WEBP is too small or corrupt."""
    size = path.stat().st_size
    if size < _RASTER_MIN_BYTES:
        return (
            f"{path.name}: WEBP is only {size} bytes — likely a placeholder. "
            f"Minimum expected: {_RASTER_MIN_BYTES} bytes."
        )
    try:
        with open(path, "rb") as f:
            head = f.read(12)
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WEBP":
            return f"{path.name}: File has .webp extension but invalid WEBP header."
    except Exception:
        pass
    return None


def _validate_bmp(path: Path) -> str | None:
    """Return a warning if the BMP is too small or corrupt."""
    size = path.stat().st_size
    if size < _RASTER_MIN_BYTES:
        return (
            f"{path.name}: BMP is only {size} bytes — likely a placeholder. "
            f"Minimum expected: {_RASTER_MIN_BYTES} bytes."
        )
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"BM":
                return f"{path.name}: File has .bmp extension but invalid BMP header."
    except Exception:
        pass
    return None


def _validate_tiff(path: Path) -> str | None:
    """Return a warning if the TIFF is too small or corrupt."""
    size = path.stat().st_size
    if size < _RASTER_MIN_BYTES:
        return (
            f"{path.name}: TIFF is only {size} bytes — likely a placeholder. "
            f"Minimum expected: {_RASTER_MIN_BYTES} bytes."
        )
    try:
        with open(path, "rb") as f:
            sig = f.read(4)
        if sig not in (b"II\x2a\x00", b"MM\x00\x2a"):
            return f"{path.name}: File has .tiff extension but invalid TIFF header."
    except Exception:
        pass
    return None


def _validate_svg(path: Path) -> str | None:
    """Return a warning if the SVG is empty or has no <svg> root."""
    size = path.stat().st_size
    if size == 0:
        return f"{path.name}: SVG file is empty (0 bytes)."
    if size < _TEXT_MIN_BYTES:
        return f"{path.name}: SVG is only {size} bytes — too small to be a real graphic."
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if "<svg" not in text.lower():
            return (
                f"{path.name}: SVG file does not contain an <svg> element — "
                f"likely not a valid SVG."
            )
    except Exception as exc:
        return f"{path.name}: SVG could not be read — {exc}"
    return None


def _validate_csv(path: Path) -> str | None:
    """Return a warning if the CSV has no data rows."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        non_empty = [r for r in rows if any(cell.strip() for cell in r)]
        if len(non_empty) == 0:
            return f"{path.name}: CSV file is completely empty — no header, no data."
        if len(non_empty) <= _CSV_MIN_DATA_ROWS:
            header = ",".join(non_empty[0]) if non_empty else "(empty)"
            return (
                f"{path.name}: CSV has only a header row ({header}) but no data rows. "
                f"Generate actual data before saving."
            )
    except Exception as exc:
        return f"{path.name}: CSV could not be parsed — {exc}"
    return None


def _validate_tsv(path: Path) -> str | None:
    """Return a warning if the TSV has no data rows."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text), delimiter="\t")
        rows = list(reader)
        non_empty = [r for r in rows if any(cell.strip() for cell in r)]
        if len(non_empty) == 0:
            return f"{path.name}: TSV file is completely empty."
        if len(non_empty) <= _CSV_MIN_DATA_ROWS:
            return (
                f"{path.name}: TSV has only a header row but no data rows. "
                f"Generate actual data before saving."
            )
    except Exception as exc:
        return f"{path.name}: TSV could not be parsed — {exc}"
    return None


def _validate_json_file(path: Path) -> str | None:
    """Return a warning if the JSON is invalid or empty."""
    size = path.stat().st_size
    if size < _STRUCTURED_MIN_BYTES:
        return f"{path.name}: JSON file is empty or too small ({size} bytes)."
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(text)
        if isinstance(data, (dict, list)) and len(data) == 0:
            return (
                f"{path.name}: JSON file parses to an empty "
                f"{type(data).__name__}."
            )
    except json.JSONDecodeError as exc:
        return f"{path.name}: JSON is malformed — {exc}"
    return None


def _validate_yaml(path: Path) -> str | None:
    """Return a warning if the YAML is empty or unparseable."""
    size = path.stat().st_size
    if size == 0:
        return f"{path.name}: YAML file is empty (0 bytes)."
    if size < _STRUCTURED_MIN_BYTES:
        return f"{path.name}: YAML file is too small ({size} bytes)."
    try:
        import yaml  # noqa: F811
        text = path.read_text(encoding="utf-8", errors="replace")
        data = yaml.safe_load(text)
        if data is None:
            return f"{path.name}: YAML file parses to null/empty."
    except ImportError:
        # yaml not available — fall back to basic text check
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            return f"{path.name}: YAML file contains only whitespace."
    except Exception as exc:
        return f"{path.name}: YAML is malformed — {exc}"
    return None


def _validate_xml(path: Path) -> str | None:
    """Return a warning if the XML is empty or unparseable."""
    size = path.stat().st_size
    if size == 0:
        return f"{path.name}: XML file is empty (0 bytes)."
    if size < _STRUCTURED_MIN_BYTES:
        return f"{path.name}: XML file is too small ({size} bytes)."
    try:
        ET.parse(path)
    except ET.ParseError as exc:
        return f"{path.name}: XML is malformed — {exc}"
    return None


def _validate_html(path: Path) -> str | None:
    """Return a warning if the HTML is empty or has no structure."""
    size = path.stat().st_size
    if size == 0:
        return f"{path.name}: HTML file is empty (0 bytes)."
    if size < _TEXT_MIN_BYTES:
        return f"{path.name}: HTML is only {size} bytes — too small."
    try:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        if "<html" not in text and "<body" not in text and "<div" not in text:
            return (
                f"{path.name}: HTML file has no recognizable HTML structure "
                f"(<html>, <body>, or <div> tag missing)."
            )
    except Exception as exc:
        return f"{path.name}: HTML could not be read — {exc}"
    return None


def _validate_text(path: Path) -> str | None:
    """Return a warning if text/markdown file is empty or trivial."""
    size = path.stat().st_size
    if size == 0:
        return f"{path.name}: Text file is empty (0 bytes)."
    if size < _TEXT_MIN_BYTES:
        content = path.read_text(encoding="utf-8", errors="replace").strip()
        if not content:
            return f"{path.name}: Text file contains only whitespace."
    return None


def _validate_pdf(path: Path) -> str | None:
    """Return a warning if the PDF is too small or has invalid header."""
    size = path.stat().st_size
    if size == 0:
        return f"{path.name}: PDF file is empty (0 bytes)."
    if size < _PDF_MIN_BYTES:
        return (
            f"{path.name}: PDF is only {size} bytes — too small for a real document. "
            f"Minimum expected: {_PDF_MIN_BYTES} bytes."
        )
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"%PDF":
                return f"{path.name}: File has .pdf extension but invalid PDF header."
    except Exception:
        pass
    return None


def _validate_xlsx(path: Path) -> str | None:
    """Return a warning if the XLSX is too small or not a valid ZIP archive."""
    size = path.stat().st_size
    if size < _BINARY_DATA_MIN_BYTES:
        return (
            f"{path.name}: XLSX is only {size} bytes — too small for a real spreadsheet."
        )
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"PK\x03\x04":
                return (
                    f"{path.name}: File has .xlsx extension but is not a valid "
                    f"ZIP archive (XLSX files are ZIP-based)."
                )
    except Exception:
        pass
    return None


def _validate_parquet(path: Path) -> str | None:
    """Return a warning if the Parquet file is too small or has bad magic."""
    size = path.stat().st_size
    if size < _BINARY_DATA_MIN_BYTES:
        return (
            f"{path.name}: Parquet file is only {size} bytes — "
            f"too small for real data."
        )
    try:
        with open(path, "rb") as f:
            header = f.read(4)
            f.seek(-4, 2)  # Parquet also has magic at end
            footer = f.read(4)
        if header != b"PAR1":
            return (
                f"{path.name}: File has .parquet extension but missing "
                f"PAR1 magic header."
            )
        if footer != b"PAR1":
            return (
                f"{path.name}: Parquet file has valid header but missing "
                f"footer magic — file may be truncated."
            )
    except Exception:
        pass
    return None


def _validate_npy(path: Path) -> str | None:
    """Return a warning if the .npy file is too small or has bad magic."""
    size = path.stat().st_size
    if size < _BINARY_DATA_MIN_BYTES:
        return (
            f"{path.name}: NumPy .npy file is only {size} bytes — "
            f"too small for real data."
        )
    try:
        with open(path, "rb") as f:
            magic = f.read(6)
        if magic != b"\x93NUMPY":
            return (
                f"{path.name}: File has .npy extension but missing "
                f"NumPy magic header."
            )
    except Exception:
        pass
    return None


def _validate_hdf5(path: Path) -> str | None:
    """Return a warning if the HDF5 file is too small or has bad magic."""
    size = path.stat().st_size
    if size < _BINARY_DATA_MIN_BYTES:
        return (
            f"{path.name}: HDF5 file is only {size} bytes — "
            f"too small for real data."
        )
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
        if magic != b"\x89HDF":
            return (
                f"{path.name}: File has .h5/.hdf5 extension but missing "
                f"HDF5 magic header."
            )
    except Exception:
        pass
    return None


def _validate_pickle(path: Path) -> str | None:
    """Return a warning if the pickle file is too small."""
    size = path.stat().st_size
    if size < _BINARY_DATA_MIN_BYTES:
        return (
            f"{path.name}: Pickle file is only {size} bytes — "
            f"too small for real data."
        )
    return None


def _validate_binary_generic(path: Path) -> str | None:
    """Fallback validator for unknown binary files: check non-empty."""
    size = path.stat().st_size
    if size == 0:
        return f"{path.name}: File is empty (0 bytes)."
    return None


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_VALIDATORS: dict[str, callable] = {
    # Raster images
    ".png": _validate_png,
    ".jpg": _validate_jpeg,
    ".jpeg": _validate_jpeg,
    ".gif": _validate_gif,
    ".webp": _validate_webp,
    ".bmp": _validate_bmp,
    ".tiff": _validate_tiff,
    ".tif": _validate_tiff,
    # Vector graphics
    ".svg": _validate_svg,
    # Tabular data
    ".csv": _validate_csv,
    ".tsv": _validate_tsv,
    ".xlsx": _validate_xlsx,
    ".xls": _validate_xlsx,  # same ZIP check applies
    ".parquet": _validate_parquet,
    # Structured text
    ".json": _validate_json_file,
    ".yaml": _validate_yaml,
    ".yml": _validate_yaml,
    ".xml": _validate_xml,
    ".html": _validate_html,
    ".htm": _validate_html,
    # Plain text
    ".txt": _validate_text,
    ".md": _validate_text,
    ".log": _validate_text,
    # Binary data
    ".pdf": _validate_pdf,
    ".npy": _validate_npy,
    ".npz": _validate_npy,  # same magic
    ".h5": _validate_hdf5,
    ".hdf5": _validate_hdf5,
    ".pkl": _validate_pickle,
    ".pickle": _validate_pickle,
}


def validate_file(path: Path) -> str | None:
    """Validate a single file.  Returns a warning string or None if OK."""
    if not path.exists() or not path.is_file():
        return f"{path.name}: File does not exist."
    suffix = path.suffix.lower()
    validator = _VALIDATORS.get(suffix)
    if validator is None:
        # Fallback: at least check non-empty for any file
        return _validate_binary_generic(path)
    try:
        return validator(path)
    except Exception as exc:
        logger.debug("File validation error for %s: %s", path, exc)
        return f"{path.name}: Validation error — {exc}"


def validate_directory(directory: Path) -> list[str]:
    """Validate all files in a directory tree.  Returns list of warnings."""
    warnings: list[str] = []
    if not directory.exists():
        return warnings
    for p in sorted(directory.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            w = validate_file(p)
            if w:
                warnings.append(w)
    return warnings


def snapshot_file_state(directory: Path) -> dict[str, tuple[float, int]]:
    """Capture mtime+size for all files in directory.

    Used for before/after diff to detect new or changed files.
    """
    state: dict[str, tuple[float, int]] = {}
    if not directory.exists():
        return state
    for p in directory.rglob("*"):
        if p.is_file() and not p.name.startswith("."):
            try:
                st = p.stat()
                state[str(p)] = (st.st_mtime, st.st_size)
            except OSError:
                pass
    return state


def find_changed_files(
    before: dict[str, tuple[float, int]],
    after: dict[str, tuple[float, int]],
) -> list[Path]:
    """Return paths of files that are new or modified between snapshots."""
    changed: list[Path] = []
    for path_str, (mtime, size) in after.items():
        old = before.get(path_str)
        if old is None or old != (mtime, size):
            changed.append(Path(path_str))
    return sorted(changed)


def validate_changed_files(
    before: dict[str, tuple[float, int]],
    after: dict[str, tuple[float, int]],
) -> list[str]:
    """Validate only files that changed between two snapshots."""
    changed = find_changed_files(before, after)
    warnings: list[str] = []
    for p in changed:
        w = validate_file(p)
        if w:
            warnings.append(w)
    return warnings


# ---------------------------------------------------------------------------
# Severity classification for file warnings
# ---------------------------------------------------------------------------

_CRITICAL_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".svg", ".webp"}
_DATA_EXTENSIONS = {".csv", ".tsv", ".json", ".yaml", ".yml", ".xml", ".parquet", ".xlsx"}


def classify_warning_severity(path: Path, warning: str) -> str:
    """Classify a file warning as 'critical', 'error', or 'warning'.

    - critical: The file is completely useless (0 bytes, placeholder image).
      These MUST be regenerated — the output is broken.
    - error: The file exists but is likely invalid (bad structure, too small).
      Should be regenerated if possible.
    - warning: The file may be suboptimal but is not empty/corrupt.
    """
    size = path.stat().st_size if path.exists() else 0
    suffix = path.suffix.lower()

    # 0-byte files are always critical
    if size == 0:
        return "critical"

    # Placeholder images (1x1 pixel PNGs, tiny rasters) are critical
    if suffix in _CRITICAL_EXTENSIONS and size < _RASTER_MIN_BYTES:
        return "critical"

    # Empty data files are errors
    if suffix in _DATA_EXTENSIONS and ("empty" in warning.lower() or "no data" in warning.lower()):
        return "error"

    return "warning"


def build_repair_instructions(warnings: list[tuple[Path, str]]) -> str:
    """Build actionable repair instructions from a list of (path, warning) tuples.

    Returns a formatted string that can be injected into the LLM context
    to guide automatic repair of broken output files.
    """
    if not warnings:
        return ""

    critical = []
    errors = []
    for path, warning in warnings:
        severity = classify_warning_severity(path, warning)
        if severity == "critical":
            critical.append((path, warning))
        elif severity == "error":
            errors.append((path, warning))

    parts = []

    if critical:
        parts.append(
            "🚨 CRITICAL: The following output files are BROKEN and MUST be regenerated:\n"
        )
        for path, warning in critical:
            suffix = path.suffix.lower()
            parts.append(f"  - {path.name}: {warning}")
            if suffix in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
                parts.append(
                    f"    FIX: Re-run the plotting code that should create {path.name}. "
                    "Ensure: (1) matplotlib is installed (pip.install if needed), "
                    "(2) actual data is plotted before savefig(), "
                    "(3) do NOT write placeholder/fallback images."
                )
            elif suffix == ".pdf":
                parts.append(
                    f"    FIX: Re-generate {path.name} with actual content. "
                    "Ensure the PDF library wrote real pages."
                )
            else:
                parts.append(
                    f"    FIX: Re-generate {path.name} with actual content."
                )

    if errors:
        parts.append(
            "\n⚠ ERROR: The following output files have structural issues:\n"
        )
        for path, warning in errors:
            parts.append(f"  - {path.name}: {warning}")
            parts.append(f"    FIX: Re-generate with valid, complete data.")

    if critical:
        parts.append(
            "\nIMPORTANT: Do NOT proceed to the next step until all CRITICAL files "
            "are fixed. Do NOT use base64 placeholder images as a workaround. "
            "If a library is missing, install it with pip.install first."
        )

    return "\n".join(parts)
