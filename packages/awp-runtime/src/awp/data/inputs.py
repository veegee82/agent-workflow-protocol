"""Input classification, serialization, and manifest building for AgentWorkflow."""

from __future__ import annotations

import json
import logging
import shutil
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_IMAGE_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".tiff",
        ".tif",
        ".webp",
        ".svg",
        ".ico",
        ".heic",
        ".heif",
    }
)


class InputType(str, Enum):
    DATAFRAME = "dataframe"
    NDARRAY = "ndarray"
    IMAGE = "image"
    FILE_PATH = "file_path"
    DICT = "dict"
    LIST = "list"
    STRING = "string"
    BYTES = "bytes"
    NUMERIC = "numeric"
    BOOLEAN = "boolean"
    NONE = "none"


def classify_input(key: str, value: Any) -> InputType:
    """Classify a single input value by its Python type."""
    # Check DataFrame first (optional pandas import)
    try:
        import pandas as pd

        if isinstance(value, pd.DataFrame):
            return InputType.DATAFRAME
    except ImportError:
        pass

    # Check numpy ndarray (optional numpy import)
    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            return InputType.NDARRAY
    except ImportError:
        pass

    if value is None:
        return InputType.NONE
    if isinstance(value, bool):
        return InputType.BOOLEAN
    if isinstance(value, (int, float)):
        return InputType.NUMERIC
    if isinstance(value, bytes):
        return InputType.BYTES
    if isinstance(value, dict):
        return InputType.DICT
    if isinstance(value, list):
        return InputType.LIST
    if isinstance(value, str):
        # Check if it's an image file path
        if _is_image_path(value):
            return InputType.IMAGE
        # Check if it's a file path that exists
        if _is_file_path(value):
            return InputType.FILE_PATH
        return InputType.STRING

    return InputType.STRING


def _is_file_path(value: str) -> bool:
    """Heuristic: treat as file path if it exists on disk."""
    try:
        p = Path(value)
        return p.exists() and (p.is_file() or p.is_dir())
    except (OSError, ValueError):
        return False


def _is_image_path(value: str) -> bool:
    """Return True if *value* is an existing file with an image extension."""
    try:
        p = Path(value)
        return p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS
    except (OSError, ValueError):
        return False


def _dataframe_schema(df: Any) -> dict[str, Any]:
    """Extract schema summary from a pandas DataFrame."""
    return {
        "shape": list(df.shape),
        "columns": list(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "head": df.head(5).to_dict(orient="records"),
        "describe": df.describe(include="all").to_dict(),
    }


def _ndarray_schema(arr: Any) -> dict[str, Any]:
    """Extract schema summary from a numpy ndarray."""
    import numpy as np

    schema: dict[str, Any] = {
        "shape": list(arr.shape),
        "dtype": str(arr.dtype),
        "ndim": arr.ndim,
        "size": arr.size,
    }
    # Add basic statistics for numeric arrays
    if np.issubdtype(arr.dtype, np.number) and arr.size > 0:
        schema["min"] = float(np.nanmin(arr))
        schema["max"] = float(np.nanmax(arr))
        schema["mean"] = float(np.nanmean(arr))
        schema["std"] = float(np.nanstd(arr))
    return schema


def _image_metadata(path: Path) -> dict[str, Any]:
    """Extract image metadata (dimensions, format) if PIL is available."""
    meta: dict[str, Any] = {
        "file_size": path.stat().st_size,
        "extension": path.suffix.lower(),
    }
    try:
        from PIL import Image

        with Image.open(path) as img:
            meta["width"] = img.width
            meta["height"] = img.height
            meta["mode"] = img.mode
            meta["format"] = img.format
    except Exception:
        pass
    return meta


def prepare_workspace(inputs: dict[str, Any], workspace_dir: Path) -> dict[str, Any]:
    """Write all inputs into the workspace and return an input manifest.

    The manifest maps each input key to metadata about the input
    (type, workspace path, preview, etc.) for injection into the manager prompt.

    ``workspace_path`` values are stored **relative to the workspace directory**
    (e.g. ``inputs/data.csv``) so the manager prompt can pass them directly to
    workers as ``file.read`` / ``code.execute`` paths.
    """
    data_dir = workspace_dir / "inputs"
    data_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {}

    for key, value in inputs.items():
        input_type = classify_input(key, value)
        entry: dict[str, Any] = {"type": input_type.value, "key": key}

        if input_type == InputType.DATAFRAME:
            csv_path = data_dir / f"{key}.csv"
            value.to_csv(csv_path, index=False)
            schema = _dataframe_schema(value)
            entry["workspace_path"] = f"inputs/{key}.csv"
            entry["schema"] = schema
            entry["preview"] = (
                f"DataFrame {schema['shape'][0]} rows x {schema['shape'][1]} cols"
            )
            logger.info("Input '%s': DataFrame -> %s", key, csv_path)

        elif input_type == InputType.NDARRAY:
            import numpy as np

            npy_path = data_dir / f"{key}.npy"
            np.save(npy_path, value)
            schema = _ndarray_schema(value)
            entry["workspace_path"] = f"inputs/{key}.npy"
            entry["schema"] = schema
            shape_str = "x".join(str(s) for s in schema["shape"])
            entry["preview"] = f"ndarray {shape_str} dtype={schema['dtype']}"
            logger.info("Input '%s': ndarray -> %s", key, npy_path)

        elif input_type == InputType.IMAGE:
            src = Path(value)
            dst = data_dir / src.name
            shutil.copy2(src, dst)
            meta = _image_metadata(src)
            entry["workspace_path"] = f"inputs/{src.name}"
            entry["original_path"] = value
            entry["image_metadata"] = meta
            dims = f"{meta['width']}x{meta['height']}" if "width" in meta else "unknown"
            entry["preview"] = f"Image: {src.name} ({dims}, {meta['file_size']} bytes)"
            logger.info("Input '%s': Image -> %s", key, dst)

        elif input_type == InputType.FILE_PATH:
            src = Path(value)
            dst = data_dir / src.name
            if src.is_file():
                shutil.copy2(src, dst)
            elif src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            entry["workspace_path"] = f"inputs/{src.name}"
            entry["original_path"] = value
            entry["preview"] = (
                f"File: {src.name} ({src.stat().st_size} bytes)"
                if src.is_file()
                else f"Directory: {src.name}"
            )
            logger.info("Input '%s': File -> %s", key, dst)

        elif input_type == InputType.DICT:
            json_path = data_dir / f"{key}.json"
            json_path.write_text(
                json.dumps(value, indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )
            entry["workspace_path"] = f"inputs/{key}.json"
            preview = json.dumps(value, default=str)
            entry["preview"] = preview[:200] + "..." if len(preview) > 200 else preview
            logger.info("Input '%s': Dict -> %s", key, json_path)

        elif input_type == InputType.LIST:
            json_path = data_dir / f"{key}.json"
            json_path.write_text(
                json.dumps(value, indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )
            entry["workspace_path"] = f"inputs/{key}.json"
            entry["preview"] = f"List with {len(value)} items"
            logger.info("Input '%s': List -> %s", key, json_path)

        elif input_type == InputType.BYTES:
            bin_path = data_dir / f"{key}.bin"
            bin_path.write_bytes(value)
            entry["workspace_path"] = f"inputs/{key}.bin"
            entry["preview"] = f"Binary data ({len(value)} bytes)"
            logger.info("Input '%s': Bytes -> %s", key, bin_path)

        elif input_type == InputType.STRING:
            entry["value"] = value
            entry["preview"] = value[:200] + "..." if len(value) > 200 else value

        elif input_type == InputType.NUMERIC:
            entry["value"] = value
            entry["preview"] = str(value)

        elif input_type == InputType.BOOLEAN:
            entry["value"] = value
            entry["preview"] = str(value)

        elif input_type == InputType.NONE:
            entry["value"] = None
            entry["preview"] = "None"

        manifest[key] = entry

    # Write manifest to workspace
    manifest_path = workspace_dir / "input_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )

    return manifest
