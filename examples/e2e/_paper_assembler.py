"""Deterministic paper assembler for bilingual_arxiv_8page_paper_v2.

Runs as a Phase 2 DeterministicPhase callable after the LLM delegation
loop exits. Reads the workers' paper_en.md / paper_de.md / figures / bib,
emits a two-column arxiv LaTeX doc per language with the canonical
author line ("AWP, Silvio Jurk*"), compiles with tectonic, and tunes
spacing until each PDF has exactly 8 pages (max 6 attempts per lang).

Pure under R33: no LLM imports. Tuning heuristics adapted from
/tmp/build_final_papers.py (which hit 8 pages in 3 attempts during the
v1 post-mortem repair).
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# LaTeX template — identical preamble for DE + EN; babel differs via slot.

_PREAMBLE = r"""\documentclass[11pt,twocolumn,letterpaper]{article}
\usepackage[margin=0.95in,columnsep=0.35in]{geometry}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{microtype}
\usepackage{graphicx}
\usepackage{amsmath,amssymb}
\usepackage{url}
\usepackage{hyperref}
\usepackage{cite}
\usepackage{caption}
\usepackage{booktabs}
\usepackage{xcolor}
\usepackage{authblk}
\hypersetup{colorlinks=true,citecolor=blue!55!black,linkcolor=blue!55!black,urlcolor=blue!55!black}
\setlength{\parskip}{5pt}
\setlength{\parindent}{12pt}
\renewcommand{\baselinestretch}{1.18}
\captionsetup{font=small,skip=4pt}
\pagestyle{plain}
%LANGUAGE_HOOK%
"""

_DOC = r"""
\title{%TITLE%}
\author{AWP, Silvio Jurk$^{*}$}
\affil{\texttt{https://github.com/veegee82/agent-workflow-protocol}}
\date{\today}

\begin{document}
\twocolumn[\maketitle
\begin{abstract}
\noindent
%ABSTRACT%
\end{abstract}]

%BODY%

\bibliographystyle{plain}
\bibliography{references}
\end{document}
"""

_LANG_HOOKS = {
    "en": r"\usepackage[english]{babel}",
    "de": r"\usepackage[ngerman]{babel}",
}

_FORBIDDEN_TOKENS = (
    "TODO", "FIXME", "XXX", "Lorem ipsum",
    "TITLE GOES HERE", "PLACEHOLDER", "to be filled", "tbd",
)


def _assert_no_placeholders(text: str, label: str) -> None:
    low = text.lower()
    for tok in _FORBIDDEN_TOKENS:
        if tok.lower() in low:
            raise ValueError(f"placeholder token '{tok}' found in {label}")


# Markdown -> LaTeX (minimal, deterministic; no pandoc dependency).


def _inline(text: str) -> str:
    # [@k] / [@a, @b] -> \cite{a,b}
    def _cite(m: re.Match[str]) -> str:
        keys = [p.strip().lstrip("@") for p in m.group(1).split(",")]
        keys = [k for k in keys if k]
        return "\\cite{" + ",".join(keys) + "}" if keys else ""
    text = re.sub(r"\[((?:@[A-Za-z0-9_]+\s*,?\s*)+)\]", _cite, text)
    text = re.sub(r"`([^`\n]+)`", r"\\texttt{\1}", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\\textbf{\1}", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\\emph{\1}", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\\href{\2}{\1}", text)
    return text


def _md_body(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    in_list = False

    def _close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("\\end{itemize}")
            in_list = False

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if s.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            _close_list()
            out.append("\\begin{verbatim}")
            out.extend(lines[i + 1:j])
            out.append("\\end{verbatim}")
            i = j + 1
            continue
        mh = re.match(r"^\s*(#{1,3})\s+(.+?)\s*$", ln)
        if mh:
            _close_list()
            lvl, txt = len(mh.group(1)), _inline(mh.group(2))
            if lvl == 2:
                out.append(f"\\section{{{txt}}}")
            elif lvl == 3:
                out.append(f"\\subsection{{{txt}}}")
            # lvl == 1: skipped (title goes to \title{...})
            i += 1
            continue
        mi = re.match(r"^\s*!\[[^\]]*\]\(([^)]+)\)\s*$", ln)
        if mi:
            _close_list()
            out.append("\\begin{figure}[t]")
            out.append("\\centering")
            out.append(f"\\includegraphics[width=0.88\\linewidth]{{{mi.group(1)}}}")
            out.append("\\caption{Figure.}")
            out.append("\\end{figure}")
            i += 1
            continue
        ml = re.match(r"^\s*[-*]\s+(.+?)\s*$", ln)
        if ml:
            if not in_list:
                out.append("\\begin{itemize}")
                in_list = True
            out.append("\\item " + _inline(ml.group(1)))
            i += 1
            continue
        if in_list and not s:
            _close_list()
        out.append(_inline(ln))
        i += 1
    _close_list()
    return "\n".join(out)


def _split_abstract(md: str) -> tuple[str, str]:
    """(abstract_text, rest_md). Abstract = ``## Abstract`` block or first paragraph."""
    m = re.search(
        r"^\s*##\s+Abstract\s*\n(?P<body>.+?)(?=^\s*##\s+|\Z)",
        md, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if m:
        return m.group("body").strip(), md[:m.start()] + md[m.end():]
    parts = md.split("\n\n", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1]
    return (parts[0].strip() if parts else ""), ""


# Compile + 8-page tuning (adapted from /tmp/build_final_papers.py).


def _count_pages(pdf: Path) -> Optional[int]:
    try:
        from PyPDF2 import PdfReader  # type: ignore
    except ImportError:
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            return None
    try:
        return len(PdfReader(str(pdf)).pages)
    except Exception:  # noqa: BLE001
        return None


def _compile_once(tex_dir: Path) -> Optional[int]:
    try:
        proc = subprocess.run(
            ["tectonic", "-X", "compile", "main.tex", "--keep-intermediates"],
            cwd=str(tex_dir), capture_output=True, text=True, timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("tectonic invocation failed in %s: %s", tex_dir, exc)
        return None
    if proc.returncode != 0:
        logger.error("tectonic rc=%s stderr=%s", proc.returncode, proc.stderr[-600:])
        return None
    pdf = tex_dir / "main.pdf"
    return _count_pages(pdf) if pdf.exists() else None


_RE_STRETCH = re.compile(r"\\renewcommand\{\\baselinestretch\}\{[0-9.]+\}")
_RE_PARSKIP = re.compile(r"\\setlength\{\\parskip\}\{[0-9]+pt\}")
_RE_GEO = re.compile(r"margin=[0-9.]+in,columnsep=[0-9.]+in")


def _rewrite(content: str, stretch: float, parskip: int, margin: float,
             colsep: float, docclass_swap: Optional[str]) -> str:
    content = _RE_STRETCH.sub(
        f"\\\\renewcommand{{\\\\baselinestretch}}{{{stretch:.2f}}}",
        content, count=1,
    )
    content = _RE_PARSKIP.sub(
        f"\\\\setlength{{\\\\parskip}}{{{parskip}pt}}",
        content, count=1,
    )
    content = _RE_GEO.sub(
        f"margin={margin:.2f}in,columnsep={colsep:.2f}in",
        content, count=1,
    )
    if docclass_swap is not None:
        content = content.replace("documentclass[11pt,", docclass_swap, 1)
    return content


def _tune_to_eight(tex_dir: Path, max_attempts: int = 6) -> tuple[Optional[int], int]:
    """Compile + adjust spacing until page count == 8 or cap hit."""
    tex = tex_dir / "main.tex"
    pages = _compile_once(tex_dir)
    attempts = 1
    if pages is None:
        return None, attempts
    while pages != 8 and attempts < max_attempts:
        step = attempts
        content = tex.read_text(encoding="utf-8")
        if pages < 8:
            # Loosen: more page area per line -> more pages.
            content = _rewrite(
                content,
                stretch=1.18 + 0.10 * step,
                parskip=5 + 2 * step,
                margin=min(1.30, 0.95 + 0.06 * step),
                colsep=0.40,
                docclass_swap="documentclass[12pt," if step >= 3 else None,
            )
        else:
            # Tighten: less page area -> fewer pages.
            content = _rewrite(
                content,
                stretch=max(0.95, 1.18 - 0.05 * step),
                parskip=max(1, 5 - step),
                margin=max(0.55, 0.95 - 0.06 * step),
                colsep=0.25,
                docclass_swap="documentclass[10pt," if step >= 3 else None,
            )
        tex.write_text(content, encoding="utf-8")
        attempts += 1
        pages = _compile_once(tex_dir)
        if pages is None:
            return None, attempts
    return pages, attempts


# Public entrypoint — dispatched by DeterministicPhaseRunner.


def _build_one(lang: str, md_src: Path, bib: Path, figs: Path, out: Path) -> Dict[str, Any]:
    if not md_src.is_file():
        raise FileNotFoundError(f"markdown source missing: {md_src}")
    md_text = md_src.read_text(encoding="utf-8", errors="replace")
    _assert_no_placeholders(md_text, md_src.name)

    mt = re.search(r"^\s*#\s+(.+?)\s*$", md_text, flags=re.MULTILINE)
    title = mt.group(1).strip() if mt else (
        "Bilingual AWP Paper" if lang == "en" else "Zweisprachiges AWP-Paper"
    )
    abstract_raw, rest = _split_abstract(md_text)
    abstract = _inline(abstract_raw)
    body = _md_body(rest)

    preamble = _PREAMBLE.replace("%LANGUAGE_HOOK%", _LANG_HOOKS.get(lang, _LANG_HOOKS["en"]))
    doc = (_DOC.replace("%TITLE%", title)
                .replace("%ABSTRACT%", abstract)
                .replace("%BODY%", body))
    tex_src = preamble + doc

    tex_dir = out / f"latex_{lang}"
    tex_dir.mkdir(parents=True, exist_ok=True)
    (tex_dir / "figures").mkdir(exist_ok=True)
    if figs.is_dir():
        for p in figs.glob("*.png"):
            shutil.copy2(p, tex_dir / "figures" / p.name)
    if bib.is_file():
        shutil.copy2(bib, tex_dir / "references.bib")
    else:
        (tex_dir / "references.bib").write_text("", encoding="utf-8")
    (tex_dir / "main.tex").write_text(tex_src, encoding="utf-8")

    pages, attempts = _tune_to_eight(tex_dir)
    pdf_src = tex_dir / "main.pdf"
    pdf_dst = out / f"paper_{lang}.pdf"
    if pdf_src.is_file():
        shutil.copy2(pdf_src, pdf_dst)
    md_dst = out / f"paper_{lang}.md"
    if md_dst.resolve() != md_src.resolve():
        shutil.copy2(md_src, md_dst)
    return {
        "lang": lang,
        "pdf": str(pdf_dst) if pdf_dst.is_file() else None,
        "md": str(md_dst) if md_dst.is_file() else None,
        "pages": pages,
        "tuning_attempts": attempts,
    }


def build_bilingual_papers(
    input_md_en: str,
    input_md_de: str,
    refs_bib: str,
    figures_dir: str,
    output_dir: str,
    template_path: str = "",
) -> Dict[str, Any]:
    """Assemble + compile DE/EN papers to exactly 8 pages each.

    Dispatched by DeterministicPhaseRunner; args flow from the phase's
    ``args`` dict. Returns a structured result consumed by invariants +
    the E2E verifier (exit_code, paths, pages, tuning_attempts, errors).
    """
    md_en = Path(input_md_en)
    md_de = Path(input_md_de)
    bib = Path(refs_bib)
    figs = Path(figures_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _ = template_path  # accepted for symmetry; template is embedded

    errors: list[str] = []
    results: Dict[str, Dict[str, Any]] = {}
    for lang, src in (("en", md_en), ("de", md_de)):
        try:
            results[lang] = _build_one(lang, src, bib, figs, out)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s assembly failed", lang)
            errors.append(f"{lang}: {type(exc).__name__}: {exc}")
            results[lang] = {
                "lang": lang, "pdf": None, "md": None,
                "pages": None, "tuning_attempts": 0,
            }

    exit_code = 0 if all(
        r.get("pages") == 8 and r.get("pdf") for r in results.values()
    ) else 1

    return {
        "exit_code": exit_code,
        "paths": {
            "pdf_en": results["en"].get("pdf"),
            "pdf_de": results["de"].get("pdf"),
            "md_en": results["en"].get("md"),
            "md_de": results["de"].get("md"),
            "latex_en": str(out / "latex_en"),
            "latex_de": str(out / "latex_de"),
        },
        "pages": {
            "en": results["en"].get("pages"),
            "de": results["de"].get("pages"),
        },
        "tuning_attempts": {
            "en": results["en"].get("tuning_attempts", 0),
            "de": results["de"].get("tuning_attempts", 0),
        },
        "errors": errors,
    }


# R33 python_predicate invariant hook.


def verify_eight_pages(result: Dict[str, Any]) -> bool:
    """Return True iff both PDFs compiled to exactly 8 pages."""
    if not isinstance(result, dict):
        return False
    pages = result.get("pages") or {}
    return pages.get("en") == 8 and pages.get("de") == 8
