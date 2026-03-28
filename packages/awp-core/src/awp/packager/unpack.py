"""Unpack an .awp.zip archive into a workflow directory."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


def unpack_workflow(
    archive_path: str | Path,
    output_dir: str | Path | None = None,
    verify_checksums: bool = True,
) -> Path:
    """Unpack an .awp.zip archive into a workflow directory.

    Args:
        archive_path: Path to .awp.zip file.
        output_dir: Output directory. Defaults to current dir / workflow_name.
        verify_checksums: Verify file checksums after extraction.

    Returns:
        Path to extracted workflow directory.

    Raises:
        FileNotFoundError: If archive not found.
        ValueError: If archive is invalid or checksums don't match.
    """
    archive = Path(archive_path)
    if not archive.exists():
        raise FileNotFoundError(f"Archive not found: {archive}")

    with zipfile.ZipFile(archive, "r") as zf:
        # Read package manifest
        if "manifest.json" not in zf.namelist():
            raise ValueError("Invalid AWP archive: missing manifest.json")

        manifest = json.loads(zf.read("manifest.json"))
        workflow_name = manifest.get("workflow_name", archive.stem.replace(".awp", ""))

        # Determine output directory
        if output_dir is None:
            output_dir = Path.cwd() / workflow_name
        output_dir = Path(output_dir)

        # Extract
        output_dir.mkdir(parents=True, exist_ok=True)

        for member in zf.namelist():
            # Skip meta files
            if member in ("manifest.json", "checksums.sha256"):
                continue

            target = output_dir / member
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(member))

        # Verify checksums
        if verify_checksums and "checksums.sha256" in zf.namelist():
            checksums_raw = zf.read("checksums.sha256").decode("utf-8")
            expected: dict[str, str] = {}
            for line in checksums_raw.strip().split("\n"):
                if "  " in line:
                    checksum, filename = line.split("  ", 1)
                    expected[filename] = checksum

            for filename, expected_hash in expected.items():
                file_path = output_dir / filename
                if file_path.exists():
                    actual_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
                    if actual_hash != expected_hash:
                        raise ValueError(
                            f"Checksum mismatch for {filename}: "
                            f"expected {expected_hash[:16]}..., got {actual_hash[:16]}..."
                        )

    return output_dir
