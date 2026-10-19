from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
from PIL import Image

from omr_agent.engines import run_audiveris, run_homr


def make_png(path: Path) -> Path:
    Image.new("RGB", (640, 240), "white").save(path, format="PNG")
    return path


def write_script(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
    path.chmod(0o755)
    return path


GT = Path(__file__).resolve().parents[1] / "samples/gt/clean_piano.musicxml"


def test_fake_audiveris_contract(tmp_path, monkeypatch):
    script = write_script(
        tmp_path / "fake-audiveris",
        f"""
        import os, shutil, sys
        from pathlib import Path
        out = Path(sys.argv[sys.argv.index("-output") + 1])
        shutil.copy2(os.environ["FAKE_GT"], out / "input.musicxml")
        print("fake audiveris ok")
        """,
    )
    image = make_png(tmp_path / "score.png")
    monkeypatch.setenv("AUDIVERIS_BIN", str(script))
    monkeypatch.setenv("FAKE_GT", str(GT))
    monkeypatch.setenv("OMR_SCRATCH_DIR", str(tmp_path / "scratch"))
    monkeypatch.delenv("OMR_MOCK", raising=False)
    result = run_audiveris(image, tmp_path / "out", "upright")
    assert result.status == "ok", result.error
    assert result.musicxml and Path(result.musicxml).exists()
    assert result.engine == "audiveris"


def test_fake_homr_contract(tmp_path, monkeypatch):
    script = write_script(
        tmp_path / "fake-homr",
        f"""
        import os, shutil, sys
        from pathlib import Path
        src = Path(sys.argv[-1])
        shutil.copy2(os.environ["FAKE_GT"], src.with_suffix(".musicxml"))
        print("fake homr ok")
        """,
    )
    image = make_png(tmp_path / "score.png")
    monkeypatch.setenv("HOMR_BIN", str(script))
    monkeypatch.setenv("FAKE_GT", str(GT))
    monkeypatch.setenv("OMR_SCRATCH_DIR", str(tmp_path / "scratch"))
    monkeypatch.delenv("OMR_MOCK", raising=False)
    result = run_homr(image, tmp_path / "out", "native")
    assert result.status == "ok", result.error
    assert result.musicxml and Path(result.musicxml).exists()


def test_engine_timeout_kills_process(tmp_path, monkeypatch):
    script = write_script(
        tmp_path / "slow-homr",
        """
        import time
        time.sleep(10)
        """,
    )
    image = make_png(tmp_path / "score.png")
    monkeypatch.setenv("HOMR_BIN", str(script))
    monkeypatch.setenv("OMR_ENGINE_TIMEOUT", "1")
    monkeypatch.setenv("OMR_SCRATCH_DIR", str(tmp_path / "scratch"))
    monkeypatch.delenv("OMR_MOCK", raising=False)
    result = run_homr(image, tmp_path / "out", "native")
    assert result.status == "timeout"


def test_missing_engine_is_structured(tmp_path, monkeypatch):
    image = make_png(tmp_path / "score.png")
    monkeypatch.setenv("HOMR_BIN", str(tmp_path / "does-not-exist"))
    monkeypatch.setenv("OMR_DISABLE_UVX", "1")
    monkeypatch.setenv("OMR_SCRATCH_DIR", str(tmp_path / "scratch"))
    monkeypatch.delenv("OMR_MOCK", raising=False)
    result = run_homr(image, tmp_path / "out", "native")
    assert result.status == "missing"
