"""Pack an AWP workflow directory into a .awp.zip archive."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def pack_workflow(
    workflow_dir: str | Path,
    output_path: str | Path | None = None,
    include_workspace: bool = False,
    include_runs: bool = False,
) -> Path:
    """Pack an AWP workflow directory into a .awp.zip archive.

    Args:
        workflow_dir: Path to workflow directory containing workflow.awp.yaml.
        output_path: Output .awp.zip path. Defaults to {workflow_name}.awp.zip.
        include_workspace: Include workspace/ (memory) data.
        include_runs: Include runs/ history.

    Returns:
        Path to created archive.

    Raises:
        FileNotFoundError: If workflow.awp.yaml not found.
    """
    wf_dir = Path(workflow_dir).resolve()
    manifest_file = wf_dir / "workflow.awp.yaml"

    if not manifest_file.exists():
        raise FileNotFoundError(f"workflow.awp.yaml not found in {wf_dir}")

    # Determine output path
    if output_path is None:
        output_path = wf_dir.parent / f"{wf_dir.name}.awp.zip"
    output_path = Path(output_path)

    # Collect files
    exclude_dirs = {"__pycache__", ".git", "logs"}
    if not include_workspace:
        exclude_dirs.add("workspace")
    if not include_runs:
        exclude_dirs.add("runs")

    checksums: dict[str, str] = {}

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(wf_dir.rglob("*")):
            if file_path.is_dir():
                continue

            # Skip excluded directories
            rel_parts = file_path.relative_to(wf_dir).parts
            if any(part in exclude_dirs for part in rel_parts):
                continue

            arcname = str(file_path.relative_to(wf_dir))

            # Calculate checksum
            content = file_path.read_bytes()
            checksums[arcname] = hashlib.sha256(content).hexdigest()

            zf.writestr(arcname, content)

        # Count contents
        agents_dir = wf_dir / "agents"
        tools_dir = wf_dir / "mcp"
        tools_dir_alt = wf_dir / "tools"
        skills_dir = wf_dir / "skills"

        num_agents = len(list(agents_dir.iterdir())) if agents_dir.exists() else 0
        num_tools = (len(list(tools_dir.glob("*.py"))) if tools_dir.exists() else 0) + (
            len(list(tools_dir_alt.glob("*.py"))) if tools_dir_alt.exists() else 0
        )
        num_skills = len(list(skills_dir.iterdir())) if skills_dir.exists() else 0

        # Generate package manifest
        package_manifest = {
            "awp_package": "1.0.0",
            "workflow_name": wf_dir.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "checksum": hashlib.sha256(
                json.dumps(checksums, sort_keys=True).encode()
            ).hexdigest(),
            "contents": {
                "agents": num_agents,
                "tools": num_tools,
                "skills": num_skills,
                "has_memory_snapshot": include_workspace,
            },
        }

        zf.writestr("manifest.json", json.dumps(package_manifest, indent=2))
        zf.writestr(
            "checksums.sha256",
            "\n".join(f"{v}  {k}" for k, v in sorted(checksums.items())),
        )

    return output_path
