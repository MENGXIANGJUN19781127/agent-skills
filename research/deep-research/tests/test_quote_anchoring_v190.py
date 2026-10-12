#!/usr/bin/env python3
"""Unit tests for the v1.9.0 quote-anchoring / budget / citation-map surface.

Run:  python -m pytest research/deep-research/tests/test_quote_anchoring_v190.py -q

No network required. Stdlib-only module under test.
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import research_validation as rv  # noqa: E402


def _cq_args(**kw):
    return argparse.Namespace(file=kw.get("file"), dir=kw.get("dir"),
                              source_id=kw.get("source_id"),
                              snippet=kw.get("snippet") or [])


def _cq(tmp_path, page_text, snippets, **kw):
    """Write a page text and run cmd_check_quote against it via --file."""
    p = tmp_path / "page.txt"
    p.write_text(page_text, encoding="utf-8")
    return rv.cmd_check_quote(_cq_args(file=str(p), snippet=snippets, **kw))


class TestCheckQuote:
    def test_exact_match_file(self, tmp_path, capsys):
        page = "Acme revenue grew 40 percent in 2024.\nQ2 margins held steady."
        rc = _cq(tmp_path, page, ["revenue grew 40 percent in 2024"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert out["ok"] is True and out["snippets"][0]["snippet_ok"] is True
        assert out["snippets"][0]["chars"] > 8

    def test_match_reports_line_number(self, tmp_path, capsys):
        page = "intro\nsecond line\nthe target snippet lives here\nafter"
        rc = _cq(tmp_path, page, ["target snippet lives"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert out["snippets"][0]["line"] == 3

    def test_whitespace_runs_normalize(self, tmp_path, capsys):
        # Multi-space / blank-line runs in the page still match a flat snippet.
        page = "Revenue  was\n\n  1,200 units in the first quarter."
        rc = _cq(tmp_path, page, ["Revenue was 1,200 units in"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0 and out["snippets"][0]["snippet_ok"] is True

    def test_mismatch_exit_1(self, tmp_path, capsys):
        page = "Acme revenue grew 40 percent in 2024.\n"
        rc = _cq(tmp_path, page, ["revenue grew 45 percent in 2024"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 1 and out["ok"] is False
        assert out["snippets"][0]["snippet_ok"] is False

    def test_quote_style_hint(self, tmp_path, capsys):
        page = "He said 'never paraphrase' to the team.\n"
        rc = _cq(tmp_path, page, ["He said \u2018never paraphrase\u2019 to the team"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 1
        assert "hint" in out["snippets"][0]

    def test_short_snippet_warning(self, tmp_path, capsys):
        page = "Acme revenue grew 40 percent in 2024.\n"
        rc = _cq(tmp_path, page, ["Acme"])
        out = json.loads(capsys.readouterr().out)
        assert "warning" in out["snippets"][0]

    def test_cjk_anchors(self, tmp_path, capsys):
        page = "营收增长率为百分之四十，全年保持稳定。\n"
        rc = _cq(tmp_path, page, ["增长率为百分之四十"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0 and out["snippets"][0]["snippet_ok"] is True

    def test_resolution_error_unknown_file(self, capsys):
        rc = rv.cmd_check_quote(_cq_args(file="/nonexistent/page.txt",
                                         snippet=["something here"]))
        out = json.loads(capsys.readouterr().out)
        assert rc == 2 and out["ok"] is False
        assert "file not found" in out["error"]

    def test_resolution_error_both_modes(self, tmp_path, capsys):
        rc = rv.cmd_check_quote(_cq_args(file="x.txt", dir=str(tmp_path),
                                         source_id="s1", snippet=["a snippet"]))
        assert rc == 2

    def test_dir_flow_registered_source(self, tmp_path, capsys):
        (tmp_path / "sources.jsonl").write_text(
            json.dumps({"source_id": "s1"}) + "\n", encoding="utf-8")
        pages = tmp_path / "pages"
        pages.mkdir()
        (pages / "s1.txt").write_text("verified verbatim evidence line.\n",
                                      encoding="utf-8")
        rc = rv.cmd_check_quote(_cq_args(dir=str(tmp_path), source_id="s1",
                                         snippet=["verbatim evidence line"]))
        out = json.loads(capsys.readouterr().out)
        assert rc == 0 and out["snippets"][0]["snippet_ok"] is True

    def test_dir_flow_unknown_source(self, tmp_path, capsys):
        rc = rv.cmd_check_quote(_cq_args(dir=str(tmp_path), source_id="missing",
                                         snippet=["a snippet there"]))
        out = json.loads(capsys.readouterr().out)
        assert rc == 2 and "register-source" in out["error"]

    def test_dir_flow_missing_page_file(self, tmp_path, capsys):
        (tmp_path / "sources.jsonl").write_text(
            json.dumps({"source_id": "s1"}) + "\n", encoding="utf-8")
        rc = rv.cmd_check_quote(_cq_args(dir=str(tmp_path), source_id="s1",
                                         snippet=["a snippet there"]))
        out = json.loads(capsys.readouterr().out)
        assert rc == 2 and "page text not saved" in out["error"]


class TestEstimateBudget:
    def test_flat(self, capsys):
        rc = rv.cmd_estimate_budget(argparse.Namespace(breadth=3, rounds=5,
                                                       halving=False))
        out = json.loads(capsys.readouterr().out)
        assert rc == 0 and out["max_searches"] == 15 and out["mode"] == "flat"

    def test_tree_halving_b4_r2(self, capsys):
        # level 1: 4 nodes; width ceil(4/2)=2 -> level 2: 4*2=8; total 12
        rc = rv.cmd_estimate_budget(argparse.Namespace(breadth=4, rounds=2,
                                                       halving=True))
        out = json.loads(capsys.readouterr().out)
        assert rc == 0 and out["max_searches"] == 12 and out["mode"] == "tree"

    def test_tree_halving_b4_r3(self, capsys):
        # +level 3: width ceil(2/2)=1, nodes=8*1=8 -> total 20
        rv.cmd_estimate_budget(argparse.Namespace(breadth=4, rounds=3,
                                                  halving=True))
        out = json.loads(capsys.readouterr().out)
        assert out["max_searches"] == 20

    def test_out_of_range_exits_2(self, capsys):
        rc = rv.cmd_estimate_budget(argparse.Namespace(breadth=9, rounds=2,
                                                       halving=False))
        out = json.loads(capsys.readouterr().out)
        assert rc == 2 and out["ok"] is False


def _mc_args(report, citation=None):
    return argparse.Namespace(report=str(report), citation=citation)


class TestMapCitations:
    REPORT = (
        "## Findings\n\n"
        "First block cites [1] here and nothing else.\n\n"
        "Second block cites [2] and also [1].\n"
        "It spans two lines on purpose.\n\n"
        "Third block has no citation.\n\n"
        "```python\nprint('code fence citing [1] is skipped')\n```\n\n"
        "## Sources\n\n"
        "**Quality distribution:** 1 primary · 1 secondary\n\n"
        "| # | Title | URL | Quality | Accessed |\n"
        "|---|---|---|---|---|\n"
        "| 1 | Source one | https://example.com/one | primary | 2026-10-12 |\n"
        "| 2 | Source two | https://example.com/two | secondary | 2026-10-12 |\n"
    )

    def _write(self, tmp_path):
        p = tmp_path / "report.md"
        p.write_text(self.REPORT, encoding="utf-8")
        return p

    def test_body_citations(self, tmp_path, capsys):
        rc = rv.cmd_map_citations(_mc_args(self._write(tmp_path)))
        out = json.loads(capsys.readouterr().out)
        assert rc == 0 and out["ok"] is True
        assert out["citations"][ "1"] == [0, 1]
        assert out["citations"]["2"] == [1]
        assert out["sources_count"] == 2
        # the code-fence block must not count as a citing block
        assert all("code fence" not in b["preview"] for b in out["blocks"])

    def test_citation_filter(self, tmp_path, capsys):
        rc = rv.cmd_map_citations(_mc_args(self._write(tmp_path), citation=2))
        out = json.loads(capsys.readouterr().out)
        assert rc == 0 and out["total_blocks"] == 1
        assert out["blocks"][0]["start_line"] < out["blocks"][0]["end_line"]

    def test_uncited_number_exits_1(self, tmp_path, capsys):
        rc = rv.cmd_map_citations(_mc_args(self._write(tmp_path), citation=7))
        out = json.loads(capsys.readouterr().out)
        assert rc == 1
        assert out["citations_in_body"] == [1, 2]

    def test_missing_report_exits_2(self, tmp_path, capsys):
        rc = rv.cmd_map_citations(_mc_args(tmp_path / "nope.md"))
        out = json.loads(capsys.readouterr().out)
        assert rc == 2 and out["ok"] is False