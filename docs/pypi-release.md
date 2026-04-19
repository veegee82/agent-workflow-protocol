# PyPI Release Runbook (awp-agents)

Authoritative build-and-publish procedure for the `awp-agents` PyPI package. Referenced from `CLAUDE.md` §"PyPI Build Rules"; read this before every release.

## Architecture: What Gets Published

Only **one package** is published to PyPI: **`awp-agents`** (built from `reference/python/`). It is a meta-package that bundles everything — core models, runtime, UI server, and the **pre-built frontend assets**. The `awp-core` and `awp-runtime` packages are NOT published separately — their code is vendored into `reference/python/src/`.

The PyPI token in `~/.pypirc` is scoped to `awp-agents` only.

## Source of Truth for Code

| Component | Developed in | Copied/mirrored to (for PyPI bundle) |
|-----------|-------------|--------------------------------------|
| Core (models, parser, validator) | `packages/awp-core/src/awp/` | `reference/python/src/awp/` (same namespace) |
| Runtime (engines, LLM, tools) | `packages/awp-runtime/src/awp/` | `reference/python/src/awp/` (same namespace) |
| UI server (FastAPI, routes) | `packages/awp-ui/server/` | `reference/python/src/server/` |
| **Frontend (Vite/React)** | `packages/awp-ui/frontend/` | `reference/python/src/server/frontend/dist/` |

**CRITICAL**: The frontend is a **built artifact**. The source lives in `packages/awp-ui/frontend/src/`, the build output goes to `packages/awp-ui/frontend/dist/`, and it must be **manually copied** to `reference/python/src/server/frontend/dist/` before building the PyPI package. If you skip this step, the published package ships with stale frontend assets.

The mirror gate (`scripts/check_mirror_drift.py`) blocks commits that let `packages/` and `reference/python/src/` diverge, so in practice the Python-side sync is enforced pre-commit. The frontend copy is not covered by the mirror gate and must be done manually per release.

## Full Build + Publish Sequence

Follow these steps **in exact order** every time you publish to PyPI:

```bash
# 0. Bump versions (see Version Sync Checklist below)

# 1. Rebuild the frontend
cd packages/awp-ui/frontend && npm run build

# 2. Copy fresh frontend build into the PyPI bundle source
rm -rf reference/python/src/server/frontend/dist/
cp -r packages/awp-ui/frontend/dist/ reference/python/src/server/frontend/dist/

# 3. Sync any changed Python files from packages/ → reference/python/src/
#    (prompts.py, workflow.py, delegation_loop_runner.py, routes.py, etc.)
#    Ensure reference/python/src/ mirrors the latest packages/ code.

# 4. Build the awp-agents wheel
cd reference/python && rm -rf dist/ build/ && python -m build

# 5. Verify the wheel contains new frontend assets
python -c "import zipfile, glob; z = zipfile.ZipFile(glob.glob('dist/*.whl')[0]); [print(f) for f in z.namelist() if 'frontend/dist/assets/index' in f]"
# → Should show the NEW hash-named index-*.js and index-*.css files

# 6. Upload to PyPI
twine upload dist/*

# 7. Smoke test from PyPI
pip install --no-cache-dir awp-agents==<NEW_VERSION>
awp studio
```

## Common Mistakes

- **Forgetting to rebuild frontend**: The most common error. If you only change frontend code but skip `npm run build` + copy, the PyPI package ships the old JS/CSS.
- **Forgetting to copy frontend to `reference/python/`**: Even after `npm run build`, the output is in `packages/awp-ui/frontend/dist/` — it does NOT automatically appear in `reference/python/src/server/frontend/dist/`.
- **Python file drift**: Changes to `packages/awp-runtime/src/` or `packages/awp-ui/server/` must also be reflected in `reference/python/src/`. These directories are **not symlinked** — they are independent copies. The mirror gate catches this pre-commit; fix drift before releasing.
- **Version already uploaded**: PyPI does not allow re-uploading the same version. If you uploaded a broken build, you must bump the version again.

## Version Sync Checklist

When bumping versions, update ALL of these in one commit:

| File | Field |
|------|-------|
| `packages/awp-core/pyproject.toml` | `version` |
| `packages/awp-runtime/pyproject.toml` | `version` + `awp-core>=` dependency |
| `packages/awp-ui/pyproject.toml` | `version` + `awp-core>=` and `awp-runtime>=` dependencies |
| `reference/python/pyproject.toml` | `version` (awp-agents meta-package) |

## Pre-Release Gates

Per `CLAUDE.md`, no PyPI publish may proceed until:

1. The E2E run (see `docs/e2e.md`) reaches `complete` with the expected output and **covers all new features** introduced since the last commit pushed to GitHub.
2. All unit + integration test suites are green:
   ```bash
   pytest packages/awp-core/tests/ packages/awp-runtime/tests/
   ```
3. The three blocking doc gates pass (`check_docs_drift.py`, `check_sync_coverage.py`, `check_mirror_drift.py`).

A single failing or skipped-due-to-error test blocks the publish. Fix the root cause, do not disable or xfail tests to unblock a release.
