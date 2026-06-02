from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_image_copies_worker_package():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY workers/ ./workers/" in dockerfile
