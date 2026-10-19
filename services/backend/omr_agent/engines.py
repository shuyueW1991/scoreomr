"""OMR engine adapters.

Contract: an image in, an uncompressed MusicXML file out (or a structured
failure).  Engines are invoked as subprocesses so a crash, memory blow-up or
timeout cannot take the worker down.  Every temporary path is configurable so
the container does not depend on the current working directory.
"""
from __future__ import annotations

import glob
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from music21 import converter


@dataclass
class EngineResult:
    engine: str
    variant: str
    status: str                 # ok | failed | timeout | missing
    seconds: float = 0.0
    musicxml: str | None = None
    raw: str | None = None
    log: str = ""
    error: str = ""
    meta: dict = field(default_factory=dict)


class EngineTimeout(RuntimeError):
    pass


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _engine_timeout() -> int:
    return _env_int("OMR_ENGINE_TIMEOUT", 900)


def _scratch_root() -> Path:
    root = Path(os.environ.get("OMR_SCRATCH_DIR") or tempfile.gettempdir()) / "scoreomr"
    root.mkdir(parents=True, exist_ok=True)
    return root


def find_audiveris() -> str | None:
    candidates = [
        os.environ.get("AUDIVERIS_BIN", ""),
        "/opt/audiveris/bin/Audiveris",
        "/Applications/Audiveris.app/Contents/MacOS/Audiveris",
    ]
    candidates += glob.glob("/Volumes/Audiveris*/Audiveris.app/Contents/MacOS/Audiveris")
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return shutil.which("audiveris")


def find_homr() -> str | None:
    candidates = [
        os.environ.get("HOMR_BIN", ""),
        str(Path(sys.executable).with_name("homr")),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return shutil.which("homr")


def find_uvx() -> str | None:
    disabled = os.environ.get("OMR_DISABLE_UVX", "").lower() in {"1", "true", "yes", "on"}
    return None if disabled else shutil.which("uvx")


def engine_availability() -> dict[str, bool]:
    mock = os.environ.get("OMR_MOCK", "").lower() in {"1", "true", "yes", "on"}
    return {
        "audiveris": bool(find_audiveris()),
        "homr": bool(find_homr() or find_uvx()),
        "mock": mock,
    }


def _process_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    home = _scratch_root() / "home"
    tmp = _scratch_root() / "tmp"
    home.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "HOME": str(home),
            "TMPDIR": str(tmp),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "MPLCONFIGDIR": str(home / ".cache" / "matplotlib"),
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    if extra:
        env.update(extra)
    return env


def _run(cmd: list[str], *, env: dict[str, str], timeout: int, cwd: Path | None = None) -> tuple[int, str]:
    """Run a process group and always reap grandchildren on timeout."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        env=env,
        cwd=str(cwd) if cwd else None,
        start_new_session=True,
    )
    try:
        output, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        output, _ = proc.communicate()
        raise EngineTimeout(f"engine exceeded {timeout}s") from None
    return proc.returncode, output or ""


def _to_musicxml(src: Path, dst: Path) -> str:
    score = converter.parse(str(src))
    dst.parent.mkdir(parents=True, exist_ok=True)
    score.write("musicxml", fp=str(dst))
    return str(dst)


def _tail(log: str, limit: int = 4000) -> str:
    return (log or "")[-limit:]


def run_audiveris(image: Path, out_dir: Path, variant: str = "upright") -> EngineResult:
    binary = find_audiveris()
    if not binary:
        return EngineResult(
            "audiveris", variant, "missing",
            error="Audiveris 未安装（设置 AUDIVERIS_BIN 或使用 worker 镜像）",
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    local = out_dir / f"input{image.suffix.lower() or '.png'}"
    shutil.copy2(image, local)
    java_tmp = _scratch_root() / "tmp"
    java_tmp.mkdir(parents=True, exist_ok=True)
    java_opts = os.environ.get("AUDIVERIS_JAVA_OPTIONS", "")
    java_opts = (
        f"-Djava.awt.headless=true -Duser.home={_scratch_root() / 'home'} "
        f"-Djava.io.tmpdir={java_tmp} {java_opts}"
    ).strip()
    env = _process_env({"_JAVA_OPTIONS": java_opts})
    cmd = [binary, "-batch", "-transcribe", "-export", "-output", str(out_dir), str(local)]
    t0 = time.time()
    try:
        _, log = _run(cmd, env=env, timeout=_engine_timeout(), cwd=out_dir)
    except EngineTimeout as exc:
        return EngineResult("audiveris", variant, "timeout", seconds=time.time() - t0, log=str(exc), error=str(exc))
    except OSError as exc:
        return EngineResult("audiveris", variant, "failed", seconds=time.time() - t0, error=f"启动失败：{exc}")
    elapsed = time.time() - t0

    # Prefer an already-exported MusicXML; otherwise convert Audiveris' .mxl.
    xmls = sorted(out_dir.rglob("*.musicxml"), key=lambda p: p.stat().st_mtime)
    if xmls:
        return EngineResult(
            "audiveris", variant, "ok", seconds=elapsed, musicxml=str(xmls[-1]),
            raw=str(xmls[-1]), log=_tail(log),
        )
    mxls = sorted(out_dir.rglob("*.mxl"), key=lambda p: p.stat().st_mtime)
    if mxls:
        try:
            mx = _to_musicxml(mxls[-1], out_dir / "audiveris.musicxml")
        except Exception as exc:  # noqa: BLE001
            return EngineResult(
                "audiveris", variant, "failed", seconds=elapsed, raw=str(mxls[-1]),
                log=_tail(log), error=f"MusicXML 解析失败：{exc}",
            )
        return EngineResult(
            "audiveris", variant, "ok", seconds=elapsed, musicxml=mx,
            raw=str(mxls[-1]), log=_tail(log),
        )

    logs = sorted(out_dir.rglob("*.log"), key=lambda p: p.stat().st_mtime)
    error = ""
    if logs:
        try:
            error = logs[-1].read_text(errors="ignore")[-1500:]
        except OSError:
            error = ""
    return EngineResult(
        "audiveris", variant, "failed", seconds=elapsed, log=_tail(log),
        error=error or "Audiveris 未生成 MusicXML（常见原因：图片过小/谱线检测失败）",
    )


def _homr_command(binary: str | None, local: Path) -> tuple[list[str] | None, dict[str, str], str]:
    if binary:
        return [binary, str(local)], {}, ""
    uvx = find_uvx()
    if not uvx:
        return None, {}, "homr 未安装（设置 HOMR_BIN，或在 dev 环境安装 uv）"
    env = {
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(_scratch_root() / "uv-cache")),
        "UV_PYTHON_INSTALL_DIR": os.environ.get("UV_PYTHON_INSTALL_DIR", str(_scratch_root() / "uv-python")),
        "UV_TOOL_DIR": os.environ.get("UV_TOOL_DIR", str(_scratch_root() / "uv-tools")),
        "UV_TOOL_BIN_DIR": os.environ.get("UV_TOOL_BIN_DIR", str(_scratch_root() / "uv-bin")),
    }
    return [uvx, "--from", "homr==0.7.0", "homr", str(local)], env, ""


def run_homr(image: Path, out_dir: Path, variant: str = "native") -> EngineResult:
    binary = find_homr()
    out_dir.mkdir(parents=True, exist_ok=True)
    local = out_dir / f"input{image.suffix.lower() or '.png'}"
    shutil.copy2(image, local)
    cmd, extra_env, error = _homr_command(binary, local)
    if cmd is None:
        return EngineResult("homr", variant, "missing", error=error)
    env = _process_env(extra_env)
    t0 = time.time()
    try:
        _, log = _run(cmd, env=env, timeout=_engine_timeout(), cwd=out_dir)
    except EngineTimeout as exc:
        return EngineResult("homr", variant, "timeout", seconds=time.time() - t0, log=str(exc), error=str(exc))
    except OSError as exc:
        return EngineResult("homr", variant, "failed", seconds=time.time() - t0, error=f"启动失败：{exc}")
    elapsed = time.time() - t0

    xmls = sorted(out_dir.rglob("*.musicxml"), key=lambda p: p.stat().st_mtime)
    if xmls:
        return EngineResult(
            "homr", variant, "ok", seconds=elapsed, musicxml=str(xmls[-1]),
            raw=str(xmls[-1]), log=_tail(log),
        )
    return EngineResult(
        "homr", variant, "failed", seconds=elapsed, log=_tail(log),
        error="homr 未生成 MusicXML（常见原因：谱线不足、图片模糊或模型缺失）",
    )


def run_mock(engine: str, image: Path, out_dir: Path, variant: str = "mock") -> EngineResult:
    """Dev-only deterministic output so the whole product can be tested offline."""
    from .mock import write_demo_score

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"mock-{engine}.musicxml"
    write_demo_score(target)
    return EngineResult(
        engine, variant, "ok", seconds=0.01, musicxml=str(target), raw=str(target),
        log="MOCK engine: deterministic demo score, not actual recognition",
        meta={"mock": True},
    )


def run_engine(engine: str, image: Path, out_dir: Path, variant: str = "upright") -> EngineResult:
    if os.environ.get("OMR_MOCK", "").lower() in {"1", "true", "yes", "on"}:
        return run_mock(engine, image, out_dir, "mock")
    if engine == "audiveris":
        return run_audiveris(image, out_dir, variant)
    if engine == "homr":
        return run_homr(image, out_dir, variant)
    if engine == "oemer":
        return run_oemer(image, out_dir, variant)
    return EngineResult(engine, variant, "missing", error=f"unknown engine: {engine}")


def find_oemer() -> str | None:
    candidate = os.environ.get("OEMER_BIN") or str(Path(sys.executable).with_name("oemer"))
    return candidate if Path(candidate).is_file() else None


def run_oemer(image: Path, out_dir: Path, variant: str = "upright") -> EngineResult:
    """Legacy adapter kept for the CLI; not enabled in the web product."""
    binary = find_oemer()
    if not binary:
        return EngineResult("oemer", variant, "missing", error="oemer 未安装")
    out_dir.mkdir(parents=True, exist_ok=True)
    local = out_dir / f"input{image.suffix.lower() or '.png'}"
    shutil.copy2(image, local)
    t0 = time.time()
    try:
        _, log = _run(
            [binary, str(local), "-o", str(out_dir)],
            env=_process_env(), timeout=_engine_timeout(), cwd=out_dir,
        )
    except EngineTimeout as exc:
        return EngineResult("oemer", variant, "timeout", seconds=time.time() - t0, error=str(exc))
    except OSError as exc:
        return EngineResult("oemer", variant, "failed", seconds=time.time() - t0, error=str(exc))
    xmls = sorted(out_dir.rglob("*.musicxml"), key=lambda p: p.stat().st_mtime)
    if not xmls:
        return EngineResult(
            "oemer", variant, "failed", seconds=time.time() - t0,
            log=_tail(log), error="oemer 未输出 MusicXML",
        )
    return EngineResult(
        "oemer", variant, "ok", seconds=time.time() - t0,
        musicxml=str(xmls[-1]), log=_tail(log),
    )


ENGINES = {
    "audiveris": run_audiveris,
    "homr": run_homr,
    "oemer": run_oemer,
    "mock": run_mock,
}
