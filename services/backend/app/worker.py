"""Worker process: claim a queued job, run OMR, persist artefacts.

The worker is deliberately a separate container from the API.  It is the only
component that needs Java, OpenCV and the ONNX models, so the public API image
stays small.  Queueing is a single SQLite table; two containers safely share
the data volume thanks to WAL + BEGIN IMMEDIATE.
"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import socket
import threading
import time
import traceback
from datetime import timedelta
from pathlib import Path
from typing import Any

from .config import Settings
from .context import AppContext
from .timeutil import iso, utcnow
from .uploads import resolve_data_path

log = logging.getLogger(__name__)

STALE_SECONDS = 90
CLEANUP_INTERVAL = 3600
RECOVER_INTERVAL = 60
MAX_ATTEMPTS = 2


class JobProcessingError(RuntimeError):
    pass


class Worker:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self.settings.ensure_dirs()
        self.ctx: AppContext = AppContext.build(self.settings, load_samples=False)
        self.worker_id = f"{socket.gethostname()}-{os.getpid()}-{os.urandom(3).hex()}"
        self.current_job: str | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._last_cleanup = 0.0
        self._last_recover = 0.0
        self._configure_engine_env()

    def _configure_engine_env(self) -> None:
        s = self.settings
        os.environ["OMR_MOCK"] = "1" if s.omr_mock else "0"
        os.environ["OMR_SCRATCH_DIR"] = str(s.scratch_dir)
        os.environ["OMR_ENGINE_TIMEOUT"] = str(s.job_timeout_seconds)
        if s.audiveris_bin:
            os.environ["AUDIVERIS_BIN"] = s.audiveris_bin
        if s.homr_bin:
            os.environ["HOMR_BIN"] = s.homr_bin

    # --------------------------------------------------------------- signals
    def install_signals(self) -> None:
        def stop(signum, frame):  # noqa: ARG001
            log.warning("signal %s received; finishing current job then stopping", signum)
            self._stop.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

    # ------------------------------------------------------------- heartbeat
    def _heartbeat_loop(self) -> None:
        from omr_agent.engines import engine_availability

        engines = engine_availability()
        while not self._stop.wait(10):
            with self._lock:
                current = self.current_job
            state = {
                "worker_id": self.worker_id,
                "pid": os.getpid(),
                "current_job": current,
                "engines": engines,
                "mock": self.settings.omr_mock,
                "started_at": self._started_at,
            }
            try:
                self.ctx.db.set_state("worker", state)
                if current:
                    self.ctx.db.touch_job(current)
            except Exception:  # noqa: BLE001
                log.exception("heartbeat failed")
        try:
            self.ctx.db.set_state(
                "worker",
                {
                    "worker_id": self.worker_id,
                    "pid": os.getpid(),
                    "current_job": None,
                    "engines": engines,
                    "mock": self.settings.omr_mock,
                    "started_at": self._started_at,
                    "stopped_at": iso(),
                },
            )
        except Exception:  # noqa: BLE001
            pass

    def start_heartbeat(self) -> None:
        self._started_at = iso()
        from omr_agent.engines import engine_availability

        self.ctx.db.set_state(
            "worker",
            {
                "worker_id": self.worker_id,
                "pid": os.getpid(),
                "current_job": None,
                "engines": engine_availability(),
                "mock": self.settings.omr_mock,
                "started_at": self._started_at,
            },
        )
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True)
        self._heartbeat_thread.start()

    # --------------------------------------------------------------- recovery
    def recover_stale(self) -> None:
        cutoff = iso(utcnow() - timedelta(seconds=STALE_SECONDS))
        rows = self.ctx.db.stale_running_jobs(cutoff)
        for job in rows:
            if job["id"] == self.current_job:
                continue
            if int(job.get("attempts") or 0) >= MAX_ATTEMPTS:
                self.ctx.db.fail_job(
                    job["id"],
                    "识别进程意外中断，已自动退还本次免费额度。请重新提交。",
                    refund=True,
                )
                log.warning("stale job %s failed after %s attempts", job["id"], job.get("attempts"))
            else:
                self.ctx.db.requeue_job(job["id"])
                log.warning("requeued stale job %s", job["id"])

    # ------------------------------------------------------------------ jobs
    def _resolve(self, relative: str) -> Path:
        return resolve_data_path(self.settings, relative)

    def _engines_for(self, mode: str) -> tuple[str, ...]:
        if mode == "audiveris":
            return ("audiveris",)
        if mode == "homr":
            return ("homr",)
        return self.settings.omr_engines

    def process_job(self, job: dict[str, Any]) -> None:
        from omr_agent.compare import run as compare_run

        result_dir = self._resolve(job["result_dir"])
        input_path = self._resolve(job["input_path"])
        if not input_path.is_file():
            raise JobProcessingError("输入图片丢失，请重新上传")
        result_dir.mkdir(parents=True, exist_ok=True)
        gt_path = str(self._resolve(job["gt_path"])) if job.get("gt_path") else None
        engines = self._engines_for(job["mode"])
        log.info("job %s mode=%s engines=%s gt=%s", job["id"], job["mode"], engines, bool(gt_path))
        report = compare_run(
            input_path,
            result_dir,
            gt=gt_path,
            engines=engines,
            mode=job["mode"],
            oracle=False,
            make_audio=True,
        )
        # Intermediates are large; the deliverables are already in result_dir.
        for name in ("preprocessed", "engines"):
            shutil.rmtree(result_dir / name, ignore_errors=True)
        if not report.chosen:
            raise JobProcessingError(self._failure_message(report))
        self.ctx.db.complete_job(
            job["id"],
            report=report.public(),
            chosen=report.chosen,
            confidence=float(report.confidence),
            needs_review=bool(report.needs_review),
        )
        log.info(
            "job %s done chosen=%s confidence=%.2f notes=%s review=%s",
            job["id"], report.chosen, report.confidence, report.notes, report.needs_review,
        )

    @staticmethod
    def _failure_message(report) -> str:
        statuses = {c.engine: c.status for c in report.candidates}
        if not statuses:
            return "识别失败：没有可用的 OMR 引擎。"
        if all(status in {"missing", "failed", "timeout", "invalid"} for status in statuses.values()):
            if any(status == "missing" for status in statuses.values()):
                return "识别失败：worker 中的 OMR 引擎未安装或不可用，请检查部署日志。"
            if any(status == "timeout" for status in statuses.values()):
                return "识别超时。请尝试更小、更清晰的单行乐谱截图。"
        return "识别失败：没有引擎能生成有效的 MusicXML。请换一张更清晰、包含完整谱表的截图。"

    def _fail(self, job_id: str, exc: Exception) -> None:
        if isinstance(exc, JobProcessingError):
            message = str(exc)
        else:
            log.error("job %s crashed: %s\n%s", job_id, exc, traceback.format_exc())
            message = "识别过程出现内部错误，本次免费额度已退还。请稍后重试或换一张图片。"
        try:
            self.ctx.db.fail_job(job_id, message, refund=True)
        except Exception:  # noqa: BLE001
            log.exception("could not mark job %s as failed", job_id)

    # ------------------------------------------------------------- maintenance
    def cleanup(self) -> None:
        cutoff = iso(utcnow() - timedelta(days=self.settings.job_retention_days))
        rows = self.ctx.db.jobs_to_cleanup(cutoff)
        for row in rows:
            try:
                # result_dir is jobs/<id>/result; removing the parent also
                # removes input.png and gt.* so no orphaned uploads remain.
                result_dir = self._resolve(row["result_dir"])
                shutil.rmtree(result_dir.parent, ignore_errors=True)
                self.ctx.db.mark_files_deleted(row["id"])
            except Exception:  # noqa: BLE001
                log.exception("cleanup failed for %s", row["id"])
        self.ctx.db.purge_sessions()
        scratch = self.settings.scratch_dir
        if scratch.exists():
            for child in scratch.iterdir():
                try:
                    if child.is_dir() and time.time() - child.stat().st_mtime > 2 * 86400:
                        shutil.rmtree(child, ignore_errors=True)
                except OSError:
                    pass
        log.info("cleanup: %s job directories removed", len(rows))

    # ------------------------------------------------------------------- loop
    def run_forever(self) -> None:
        self.install_signals()
        self.start_heartbeat()
        from omr_agent.engines import engine_availability

        availability = engine_availability()
        log.info("worker %s ready engines=%s mock=%s", self.worker_id, availability, self.settings.omr_mock)
        if not self.settings.omr_mock and not any(availability.values()):
            log.error("no OMR engine available: check AUDIVERIS_BIN / HOMR_BIN in the worker image")
        self.recover_stale()
        self.cleanup()
        self._last_cleanup = time.monotonic()
        self._last_recover = time.monotonic()

        while not self._stop.is_set():
            now = time.monotonic()
            if now - self._last_recover > RECOVER_INTERVAL:
                self.recover_stale()
                self._last_recover = now
            if now - self._last_cleanup > CLEANUP_INTERVAL:
                self.cleanup()
                self._last_cleanup = now

            try:
                job = self.ctx.db.claim_next_job(self.worker_id)
            except Exception:  # noqa: BLE001
                log.exception("could not claim job")
                self._stop.wait(5)
                continue
            if job is None:
                self._stop.wait(self.settings.worker_poll_seconds)
                continue

            with self._lock:
                self.current_job = job["id"]
            started = time.monotonic()
            try:
                self.process_job(job)
            except Exception as exc:  # noqa: BLE001
                self._fail(job["id"], exc)
            finally:
                with self._lock:
                    self.current_job = None
                log.info("job %s finished in %.1fs", job["id"], time.monotonic() - started)

        log.info("worker stopping")
        try:
            self.ctx.db.set_state(
                "worker",
                {
                    "worker_id": self.worker_id,
                    "current_job": None,
                    "mock": self.settings.omr_mock,
                    "stopped_at": iso(),
                },
            )
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    Worker(settings).run_forever()


if __name__ == "__main__":
    main()
