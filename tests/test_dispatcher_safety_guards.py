from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_approval_and_result_ingestion_use_row_locks_for_dispatch_idempotency():
    approvals_source = (ROOT / "app" / "routes" / "approvals.py").read_text(encoding="utf-8")
    results_source = (ROOT / "app" / "dispatchers" / "results.py").read_text(encoding="utf-8")

    assert ".with_for_update()" in approvals_source
    assert ".with_for_update()" in results_source


def test_result_archive_does_not_use_overwriting_replace():
    results_source = (ROOT / "app" / "dispatchers" / "results.py").read_text(encoding="utf-8")

    assert "os.replace" not in results_source
    assert "open(\"xb\")" in results_source or ".open(\"xb\")" in results_source
