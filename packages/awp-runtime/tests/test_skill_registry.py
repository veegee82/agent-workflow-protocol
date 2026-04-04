"""Test the Skill Registry — persist, catalog, lazy-load, update across runs."""

import json
import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers to get the class methods without a full DelegationLoopRunner
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path):
    """Create a minimal workspace layout."""
    (tmp_path / "workspace").mkdir()
    (tmp_path / "output").mkdir()
    return tmp_path


def _make_runner(workspace: Path):
    """Build a minimal DelegationLoopRunner pointing at *workspace*."""
    from awp.runtime.delegation_loop_runner import DelegationLoopRunner
    from awp.models.orchestration import (
        DelegationLoopConfig,
        DelegationBudget,
        DelegationLoopModels,
        WorkerPolicy,
        WorkerPolicyEnforced,
        CodeModeEnforcement,
        SandboxEnforcement,
    )

    config = DelegationLoopConfig(
        budget=DelegationBudget(max_loops=3, max_total_workers=5),
        models=DelegationLoopModels(manager="test/model", worker="test/model"),
        worker_policy=WorkerPolicy(
            enforced=WorkerPolicyEnforced(
                sandbox=SandboxEnforcement(type="none"),
                codemode=CodeModeEnforcement(),
                forbidden_tools=[],
            ),
            manager_controlled=["codemode.enabled", "codemode.tool_creation"],
        ),
    )
    runner = DelegationLoopRunner(
        workflow_dir=workspace,
        config=config,
        run_id="test_run_001",
    )
    return runner


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

SAMPLE_SKILL = textwrap.dedent("""\
    # Skill: BTC Trade CSV Processing

    ## Purpose
    Parse and validate BTC trade CSV files with the standard schema.

    ## Key Knowledge
    - CSV schema: entry_time, exit_time, entry_price, exit_price, pnl
    - Times are ISO 8601 UTC, chronologically increasing
    - Prices are USD floats (BTC typically 60,000-100,000 range)
    - PnL = exit_price - entry_price for long positions
    - Empty CSVs are a known failure mode — always validate row count

    ## Implementation Guidance
    ```python
    import pandas as pd
    df = pd.read_csv(path, parse_dates=["entry_time", "exit_time"])
    assert len(df) > 0, "CSV has no data rows"
    ```

    ## Validation Criteria
    - All numeric columns must be parseable as float
    - entry_time < exit_time for every row
    - No NaN values in any column
""")

SAMPLE_SKILL_2 = textwrap.dedent("""\
    # Skill: Matplotlib Charting

    ## Purpose
    Create publication-quality financial charts with consistent styling.

    ## Key Knowledge
    - Use dark theme matching the experiment UI
    - Always save as PNG with dpi=150 for clarity
    - Include grid lines and proper axis labels
    - Use color palette: #40c4ff (blue), #00e676 (green), #ff1744 (red)

    ## Implementation Guidance
    ```python
    import matplotlib.pyplot as plt
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_facecolor('#0d1117')
    fig.patch.set_facecolor('#0d1117')
    ```

    ## Validation Criteria
    - PNG file must be >500 bytes
    - Chart must have title, x-label, y-label
""")


class TestSkillNameExtraction:
    def test_extracts_name_from_skill_heading(self, workspace):
        runner = _make_runner(workspace)
        name = runner._skill_name_from_content(SAMPLE_SKILL)
        assert name == "btc_trade_csv_processing"

    def test_extracts_name_without_skill_prefix(self, workspace):
        runner = _make_runner(workspace)
        name = runner._skill_name_from_content("# Data Analysis\n\nSome content")
        assert name == "data_analysis"

    def test_handles_special_characters(self, workspace):
        runner = _make_runner(workspace)
        name = runner._skill_name_from_content("# Skill: BTC/USD — Price Analysis (v2)\n\nContent")
        assert "btc" in name
        assert "usd" in name

    def test_fallback_for_no_heading(self, workspace):
        runner = _make_runner(workspace)
        name = runner._skill_name_from_content("Just plain text without headings")
        assert name == "unnamed_skill"


class TestSkillDescriptionExtraction:
    def test_extracts_purpose_section(self, workspace):
        runner = _make_runner(workspace)
        desc = runner._skill_description_from_content(SAMPLE_SKILL)
        assert "Parse and validate" in desc

    def test_fallback_to_first_text_line(self, workspace):
        runner = _make_runner(workspace)
        desc = runner._skill_description_from_content("# Title\n\nThis is the first line of content.")
        assert "first line" in desc


class TestSkillPersistence:
    def test_persist_and_load_catalog(self, workspace):
        runner = _make_runner(workspace)

        # Persist two skills
        runner._persist_skill("csv_processing", SAMPLE_SKILL)
        runner._persist_skill("charting", SAMPLE_SKILL_2)

        # Verify files exist
        skills_dir = workspace / "workspace" / "skills"
        assert (skills_dir / "csv_processing.md").is_file()
        assert (skills_dir / "charting.md").is_file()

        # Load catalog
        catalog = runner._load_skill_catalog()
        assert "csv_processing" in catalog
        assert "charting" in catalog
        assert "Parse and validate" in catalog["csv_processing"]
        assert "publication-quality" in catalog["charting"]

    def test_latest_wins_overwrite(self, workspace):
        runner = _make_runner(workspace)

        runner._persist_skill("my_skill", "# Skill: My Skill\n\n## Purpose\nVersion 1")
        runner._persist_skill("my_skill", "# Skill: My Skill\n\n## Purpose\nVersion 2 improved")

        content = (workspace / "workspace" / "skills" / "my_skill.md").read_text()
        assert "Version 2 improved" in content
        assert "Version 1" not in content


class TestSkillResolve:
    def test_resolve_inline_skill_persists_and_passes_through(self, workspace):
        runner = _make_runner(workspace)

        resolved = runner._resolve_skills([SAMPLE_SKILL])

        # Should pass through the full content
        assert len(resolved) == 1
        assert "BTC Trade CSV" in resolved[0]

        # Should also persist it
        assert (workspace / "workspace" / "skills" / "btc_trade_csv_processing.md").is_file()

    def test_resolve_name_reference_loads_from_disk(self, workspace):
        runner = _make_runner(workspace)

        # First persist a skill
        runner._persist_skill("csv_processing", SAMPLE_SKILL)

        # Then resolve by name
        resolved = runner._resolve_skills(["csv_processing"])

        assert len(resolved) == 1
        assert "BTC Trade CSV" in resolved[0]
        assert "entry_time" in resolved[0]

    def test_resolve_mixed_inline_and_names(self, workspace):
        runner = _make_runner(workspace)

        # Persist one skill
        runner._persist_skill("charting", SAMPLE_SKILL_2)

        # Mix inline + name reference
        resolved = runner._resolve_skills([
            SAMPLE_SKILL,       # inline → persist + pass through
            "charting",         # name → load from disk
        ])

        assert len(resolved) == 2
        assert "BTC Trade CSV" in resolved[0]
        assert "Matplotlib" in resolved[1]

    def test_resolve_unknown_name_passes_through(self, workspace):
        runner = _make_runner(workspace)

        resolved = runner._resolve_skills(["nonexistent_skill"])

        assert len(resolved) == 1
        assert resolved[0] == "nonexistent_skill"

    def test_resolve_empty_entries_filtered(self, workspace):
        runner = _make_runner(workspace)

        resolved = runner._resolve_skills(["", "  ", None, SAMPLE_SKILL])

        assert len(resolved) == 1


class TestWorkerResultSkillPersistence:
    def test_persists_string_skills_from_result(self, workspace):
        runner = _make_runner(workspace)

        result = {
            "confidence": 0.9,
            "skills_created": [SAMPLE_SKILL, SAMPLE_SKILL_2],
        }
        runner._persist_worker_result_skills(result, "data_worker")

        catalog = runner._load_skill_catalog()
        assert "btc_trade_csv_processing" in catalog
        assert "matplotlib_charting" in catalog

    def test_persists_dict_skills_from_result(self, workspace):
        runner = _make_runner(workspace)

        result = {
            "confidence": 0.9,
            "skills_created": [
                {"name": "validation", "content": SAMPLE_SKILL},
            ],
        }
        runner._persist_worker_result_skills(result, "worker_1")

        catalog = runner._load_skill_catalog()
        assert "btc_trade_csv_processing" in catalog

    def test_ignores_short_skills(self, workspace):
        runner = _make_runner(workspace)

        result = {
            "skills_created": ["CSV parsing"],  # too short (<30 words)
        }
        runner._persist_worker_result_skills(result, "worker_1")

        catalog = runner._load_skill_catalog()
        assert len(catalog) == 0

    def test_uses_skills_key_as_fallback(self, workspace):
        runner = _make_runner(workspace)

        result = {
            "confidence": 0.9,
            "skills": [SAMPLE_SKILL],  # "skills" not "skills_created"
        }
        runner._persist_worker_result_skills(result, "worker_1")

        catalog = runner._load_skill_catalog()
        assert "btc_trade_csv_processing" in catalog


class TestSkillCatalogSection:
    def test_empty_when_no_skills(self, workspace):
        runner = _make_runner(workspace)
        section = runner._build_skill_catalog_section()
        assert section == ""

    def test_lists_available_skills(self, workspace):
        runner = _make_runner(workspace)
        runner._persist_skill("csv_processing", SAMPLE_SKILL)
        runner._persist_skill("charting", SAMPLE_SKILL_2)

        section = runner._build_skill_catalog_section()

        assert "csv_processing" in section
        assert "charting" in section
        assert "Parse and validate" in section
        assert "publication-quality" in section
        assert "Reference these by name" in section


class TestMultiRunScenario:
    """Simulate a realistic multi-run experiment."""

    def test_skills_persist_across_runs(self, workspace):
        """Run 1 creates skills, Run 2 reuses and updates them."""

        # --- RUN 1 ---
        runner1 = _make_runner(workspace)

        # Manager sends inline skill to worker
        resolved = runner1._resolve_skills([SAMPLE_SKILL])
        assert len(resolved) == 1

        # Worker creates a new skill in its result
        worker_result = {
            "confidence": 0.85,
            "findings": "Analysis complete",
            "skills_created": [SAMPLE_SKILL_2],
        }
        runner1._persist_worker_result_skills(worker_result, "chart_worker")

        # Verify both skills persisted
        catalog = runner1._load_skill_catalog()
        assert len(catalog) == 2

        # --- RUN 2 (new runner, same workspace) ---
        runner2 = DelegationLoopRunner_from_workspace(workspace)

        # Manager sees catalog
        section = runner2._build_skill_catalog_section()
        assert "csv_processing" in section or "btc_trade_csv_processing" in section
        assert "charting" in section or "matplotlib_charting" in section

        # Manager references skills by name (few tokens!)
        resolved2 = runner2._resolve_skills([
            "btc_trade_csv_processing",
            "matplotlib_charting",
        ])
        assert len(resolved2) == 2
        assert "entry_time" in resolved2[0]  # full content loaded
        assert "dark_background" in resolved2[1]  # full content loaded

        # Manager updates a skill with improved version
        updated_skill = textwrap.dedent("""\
            # Skill: BTC Trade CSV Processing

            ## Purpose
            Parse and validate BTC trade CSV files — UPDATED with new columns.

            ## Key Knowledge
            - CSV schema: entry_time, exit_time, entry_price, exit_price, pnl, volume, fee
            - Added volume and fee columns in latest data format
            - Times are ISO 8601 UTC
            - Validate: volume > 0 and fee >= 0

            ## Implementation Guidance
            ```python
            import pandas as pd
            df = pd.read_csv(path, parse_dates=["entry_time", "exit_time"])
            assert "volume" in df.columns, "Missing volume column"
            assert "fee" in df.columns, "Missing fee column"
            ```

            ## Validation Criteria
            - Must have volume and fee columns
            - volume > 0 for all rows
            - fee >= 0 for all rows
        """)
        resolved_update = runner2._resolve_skills([updated_skill])
        assert len(resolved_update) == 1

        # Verify the update overwrote the old version
        content = (workspace / "workspace" / "skills" / "btc_trade_csv_processing.md").read_text()
        assert "volume" in content
        assert "UPDATED" in content

        # --- RUN 3 (another new runner) ---
        runner3 = DelegationLoopRunner_from_workspace(workspace)

        # Load by name — should get the updated version
        resolved3 = runner3._resolve_skills(["btc_trade_csv_processing"])
        assert "volume" in resolved3[0]
        assert "UPDATED" in resolved3[0]


def DelegationLoopRunner_from_workspace(workspace: Path):
    """Helper to create a new runner pointing at the same workspace (simulating a new run)."""
    return _make_runner(workspace)
