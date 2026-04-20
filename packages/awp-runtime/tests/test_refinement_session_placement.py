"""Test for optional session_sidecar_dir parameter in RefinementLoop."""

from pathlib import Path

from awp.refinement.loop import RefinementLoop
from awp.refinement.session import write_session_sidecar_at, RefinementSession


def test_write_session_sidecar_at_custom_dir(tmp_path: Path) -> None:
    """Test that write_session_sidecar_at writes session.json to custom dir."""
    target_dir = tmp_path / "custom_refinements"
    target_dir.mkdir(parents=True)

    session = RefinementSession(
        session_id="test_session_123",
        seed_run_id="seed_run_456",
        started_at="2026-04-20T10:00:00Z",
        completed_at="2026-04-20T10:05:00Z",
        stop_reason="max_iterations",
        best_iter=1,
        iterations=[],
    )

    result_path = write_session_sidecar_at(target_dir=target_dir, session=session)

    # Verify that session.json was written to target_dir
    assert result_path == target_dir / "session.json"
    assert result_path.exists()

    # Verify content
    import json
    content = json.loads(result_path.read_text(encoding="utf-8"))
    assert content["session_id"] == "test_session_123"
    assert content["seed_run_id"] == "seed_run_456"


def test_refinement_loop_stores_session_sidecar_dir(tmp_path: Path) -> None:
    """Test that RefinementLoop stores session_sidecar_dir in __init__."""
    seed_run_dir = tmp_path / "seed"
    seed_run_dir.mkdir()

    custom_dir = tmp_path / "custom_sessions"

    loop = RefinementLoop(
        seed_run_dir=seed_run_dir,
        session_sidecar_dir=custom_dir,
    )

    assert loop._session_sidecar_dir == custom_dir
