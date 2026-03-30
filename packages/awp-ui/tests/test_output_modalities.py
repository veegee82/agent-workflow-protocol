"""Tests for handling all output modalities.

Creates fictional run data exercising every input/output type and verifies
the graph builder and store correctly handle them.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from server.models import GraphData
from server.services.graph_builder import build_graph
from tests.conftest import make_run_dir


# ---------------------------------------------------------------------------
# Output modality: Markdown text
# ---------------------------------------------------------------------------


class TestMarkdownOutput:
    def test_markdown_result(self, temp_dir: Path) -> None:
        run_dir = make_run_dir(
            temp_dir,
            task="Write a report",
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "writer": {
                            "envelope": {"instructions": "Write markdown report"},
                            "result": {
                                "confidence": 0.92,
                                "answer": "# Report\n\n## Summary\nAll good.\n\n## Details\n- Item 1\n- Item 2",
                                "output_type": "markdown",
                            },
                        }
                    },
                }
            ],
            completion={"status": "complete"},
        )
        graph = build_graph(run_dir)
        workers = [n for n in graph.nodes if n.type == "worker"]
        assert len(workers) == 1
        assert workers[0].data["confidence"] == 0.92


# ---------------------------------------------------------------------------
# Output modality: Code output
# ---------------------------------------------------------------------------


class TestCodeOutput:
    def test_python_code_result(self, temp_dir: Path) -> None:
        code = "def hello():\n    return 'Hello, World!'"
        run_dir = make_run_dir(
            temp_dir,
            task="Generate Python code",
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "coder": {
                            "envelope": {"instructions": "Write a function"},
                            "result": {
                                "confidence": 0.88,
                                "answer": code,
                                "output_type": "code",
                                "language": "python",
                            },
                        }
                    },
                }
            ],
        )
        graph = build_graph(run_dir)
        assert graph.stats["total_workers"] == 1

    def test_sql_code_result(self, temp_dir: Path) -> None:
        sql = "SELECT product, SUM(revenue) FROM sales GROUP BY product ORDER BY 2 DESC;"
        run_dir = make_run_dir(
            temp_dir,
            task="Write SQL query",
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "sql_writer": {
                            "envelope": {"instructions": "Write SQL"},
                            "result": {
                                "confidence": 0.95,
                                "answer": sql,
                                "output_type": "code",
                                "language": "sql",
                            },
                        }
                    },
                }
            ],
        )
        graph = build_graph(run_dir)
        workers = [n for n in graph.nodes if n.type == "worker"]
        assert workers[0].data["confidence"] == 0.95


# ---------------------------------------------------------------------------
# Output modality: Image output (base64)
# ---------------------------------------------------------------------------


class TestImageOutput:
    def test_base64_image_result(self, temp_dir: Path) -> None:
        # Minimal valid PNG as base64
        tiny_png = base64.b64encode(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        ).decode()

        run_dir = make_run_dir(
            temp_dir,
            task="Generate chart image",
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "chart_gen": {
                            "envelope": {"instructions": "Create chart"},
                            "result": {
                                "confidence": 0.90,
                                "answer": "Chart generated",
                                "output_type": "image",
                                "image_base64": tiny_png,
                                "mime_type": "image/png",
                            },
                        }
                    },
                }
            ],
        )
        graph = build_graph(run_dir)
        assert graph.stats["total_workers"] == 1

    def test_file_path_image_result(self, temp_dir: Path) -> None:
        run_dir = make_run_dir(
            temp_dir,
            task="Save chart to file",
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "chart_gen": {
                            "envelope": {"instructions": "Save chart"},
                            "result": {
                                "confidence": 0.87,
                                "answer": "Chart saved to output.png",
                                "artifacts": ["output.png"],
                            },
                        }
                    },
                }
            ],
        )
        graph = build_graph(run_dir)
        workers = [n for n in graph.nodes if n.type == "worker"]
        assert workers[0].data["confidence"] == 0.87


# ---------------------------------------------------------------------------
# Output modality: Table / CSV
# ---------------------------------------------------------------------------


class TestTableOutput:
    def test_csv_result(self, temp_dir: Path) -> None:
        csv_data = "product,revenue\nWidget A,15900\nWidget B,24000\nWidget C,46750"
        run_dir = make_run_dir(
            temp_dir,
            task="Compute revenue table",
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "analyzer": {
                            "envelope": {"instructions": "Compute table"},
                            "result": {
                                "confidence": 0.82,
                                "answer": csv_data,
                                "output_type": "table",
                            },
                        }
                    },
                }
            ],
        )
        graph = build_graph(run_dir)
        assert graph.stats["total_workers"] == 1


# ---------------------------------------------------------------------------
# Output modality: Structured JSON
# ---------------------------------------------------------------------------


class TestJsonOutput:
    def test_json_structured_result(self, temp_dir: Path) -> None:
        structured = {
            "total_revenue": 86650,
            "by_product": {"A": 15900, "B": 24000, "C": 46750},
        }
        run_dir = make_run_dir(
            temp_dir,
            task="Return structured data",
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "data_proc": {
                            "envelope": {"instructions": "Return JSON"},
                            "result": {
                                "confidence": 0.91,
                                "answer": json.dumps(structured),
                                "output_type": "json",
                                "data": structured,
                            },
                        }
                    },
                }
            ],
        )
        graph = build_graph(run_dir)
        assert graph.stats["total_workers"] == 1


# ---------------------------------------------------------------------------
# Output modality: Error output
# ---------------------------------------------------------------------------


class TestErrorOutput:
    def test_error_result(self, temp_dir: Path) -> None:
        run_dir = make_run_dir(
            temp_dir,
            task="Failing task",
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "failer": {
                            "envelope": {"instructions": "This will fail"},
                            "result": {
                                "confidence": 0.0,
                                "error": "ModuleNotFoundError: No module named 'pandas'",
                            },
                        }
                    },
                }
            ],
            completion={"status": "failed", "total_iterations": 1},
        )
        graph = build_graph(run_dir)
        workers = [n for n in graph.nodes if n.type == "worker"]
        assert workers[0].data["hasError"] is True
        assert "pandas" in workers[0].data["error"]

        comp = [n for n in graph.nodes if n.type == "completion"]
        assert comp[0].data["status"] == "failed"


# ---------------------------------------------------------------------------
# Output modality: Mixed output
# ---------------------------------------------------------------------------


class TestMixedOutput:
    def test_multiple_output_types(self, temp_dir: Path) -> None:
        """A worker returning text, code, and data in one result."""
        run_dir = make_run_dir(
            temp_dir,
            task="Analyze and code",
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "multi_out": {
                            "envelope": {"instructions": "Do everything"},
                            "result": {
                                "confidence": 0.88,
                                "answer": "Analysis complete with code and data",
                                "code": "print('hello')",
                                "data": {"key": "value"},
                                "artifacts": ["result.csv", "plot.png"],
                                "output_types": ["text", "code", "data", "file"],
                            },
                        }
                    },
                }
            ],
        )
        graph = build_graph(run_dir)
        assert graph.stats["total_workers"] == 1


# ---------------------------------------------------------------------------
# Output modality: Chart data (JSON)
# ---------------------------------------------------------------------------


class TestChartDataOutput:
    def test_chart_json(self, temp_dir: Path) -> None:
        chart = {
            "type": "bar",
            "title": "Revenue by Product",
            "labels": ["A", "B", "C"],
            "values": [15900, 24000, 46750],
        }
        run_dir = make_run_dir(
            temp_dir,
            task="Create chart data",
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "charter": {
                            "envelope": {"instructions": "Create chart JSON"},
                            "result": {
                                "confidence": 0.93,
                                "answer": "Chart data ready",
                                "chart_data": chart,
                                "output_type": "chart",
                            },
                        }
                    },
                }
            ],
        )
        graph = build_graph(run_dir)
        assert graph.stats["total_workers"] == 1


# ---------------------------------------------------------------------------
# Output modality: File artifacts
# ---------------------------------------------------------------------------


class TestFileArtifacts:
    def test_multiple_artifacts(self, temp_dir: Path) -> None:
        run_dir = make_run_dir(
            temp_dir,
            task="Generate files",
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "file_gen": {
                            "envelope": {"instructions": "Generate output files"},
                            "result": {
                                "confidence": 0.85,
                                "answer": "Generated 3 files",
                                "artifacts": [
                                    "report.pdf",
                                    "data.xlsx",
                                    "summary.md",
                                ],
                            },
                        }
                    },
                }
            ],
        )
        graph = build_graph(run_dir)
        assert graph.stats["total_workers"] == 1


# ---------------------------------------------------------------------------
# Output modality: Nested agent outputs (sub-delegation)
# ---------------------------------------------------------------------------


class TestNestedOutput:
    def test_nested_delegation_results(self, temp_dir: Path) -> None:
        """Two iterations with different workers produce a layered graph."""
        run_dir = make_run_dir(
            temp_dir,
            task="Complex multi-step analysis",
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "data_reader": {
                            "envelope": {"instructions": "Read data"},
                            "result": {"confidence": 0.85, "answer": "Data loaded"},
                        },
                        "data_cleaner": {
                            "envelope": {"instructions": "Clean data"},
                            "result": {"confidence": 0.80, "answer": "Data cleaned"},
                        },
                    },
                },
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "analyzer": {
                            "envelope": {"instructions": "Analyze"},
                            "result": {"confidence": 0.90, "answer": "Analysis done"},
                        },
                    },
                },
            ],
            completion={"status": "complete", "total_iterations": 2},
        )
        graph = build_graph(run_dir)
        workers = [n for n in graph.nodes if n.type == "worker"]
        assert len(workers) == 3
        assert graph.stats["total_workers"] == 3
        assert graph.stats["total_iterations"] == 2


# ---------------------------------------------------------------------------
# Input modalities
# ---------------------------------------------------------------------------


class TestInputModalities:
    """Verify that various input types are handled in tool calls."""

    def test_csv_input_via_tool_call(self, temp_dir: Path) -> None:
        run_dir = make_run_dir(
            temp_dir,
            task="Process CSV file",
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "reader": {
                            "envelope": {
                                "instructions": "Read the CSV",
                                "tools_allowed": ["file.read"],
                            },
                            "result": {"confidence": 0.85},
                            "tool_calls": [
                                {
                                    "tool": "file.read",
                                    "args": {"path": "data.csv"},
                                    "result": {
                                        "ok": True,
                                        "data": {
                                            "stdout": "col1,col2\na,1\nb,2",
                                            "stderr": "",
                                        },
                                    },
                                }
                            ],
                        }
                    },
                }
            ],
        )
        graph = build_graph(run_dir)
        tc = [n for n in graph.nodes if n.type == "toolCall"]
        assert len(tc) == 1
        assert tc[0].data["tool"] == "file.read"
        assert tc[0].data["ok"] is True

    def test_json_input_via_tool_call(self, temp_dir: Path) -> None:
        run_dir = make_run_dir(
            temp_dir,
            task="Process JSON config",
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "config_reader": {
                            "envelope": {"instructions": "Read config"},
                            "result": {"confidence": 0.90},
                            "tool_calls": [
                                {
                                    "tool": "file.read",
                                    "args": {"path": "config.json"},
                                    "result": {
                                        "ok": True,
                                        "data": {
                                            "stdout": '{"key": "value"}',
                                            "stderr": "",
                                        },
                                    },
                                }
                            ],
                        }
                    },
                }
            ],
        )
        graph = build_graph(run_dir)
        assert graph.stats["tools_ok"] == 1

    def test_code_execution_input(self, temp_dir: Path) -> None:
        run_dir = make_run_dir(
            temp_dir,
            task="Run analysis code",
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "executor": {
                            "envelope": {"instructions": "Execute code"},
                            "result": {"confidence": 0.88},
                            "tool_calls": [
                                {
                                    "tool": "code.execute",
                                    "args": {"code": "print(2 + 2)"},
                                    "result": {
                                        "ok": True,
                                        "data": {"stdout": "4\n", "stderr": ""},
                                    },
                                }
                            ],
                        }
                    },
                }
            ],
        )
        graph = build_graph(run_dir)
        tc = [n for n in graph.nodes if n.type == "toolCall"]
        assert tc[0].data["stdout"] == "4\n"

    def test_failed_tool_call(self, temp_dir: Path) -> None:
        run_dir = make_run_dir(
            temp_dir,
            task="Handle tool failure",
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "worker": {
                            "envelope": {"instructions": "Try something"},
                            "result": {"confidence": 0.3},
                            "tool_calls": [
                                {
                                    "tool": "code.execute",
                                    "args": {"code": "import nonexistent"},
                                    "result": {
                                        "ok": False,
                                        "error": "ModuleNotFoundError",
                                        "data": {
                                            "stdout": "",
                                            "stderr": "ModuleNotFoundError: No module named 'nonexistent'",
                                        },
                                    },
                                }
                            ],
                        }
                    },
                }
            ],
        )
        graph = build_graph(run_dir)
        tc = [n for n in graph.nodes if n.type == "toolCall"]
        assert tc[0].data["ok"] is False
        assert graph.stats["tools_failed"] == 1
        assert graph.stats["tools_ok"] == 0
