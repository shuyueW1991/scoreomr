import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, jobFileUrl } from "../lib/api";
import {
  classNames,
  downloadName,
  elapsedSince,
  formatDateTime,
  formatPct,
  formatSeconds,
  modeLabel,
  shortId,
} from "../lib/format";
import { errorMessage, localizeJobLabel, useI18n } from "../lib/i18n";
import type { Candidate, JobDetail } from "../lib/types";
import { StatusBadge } from "../components/StatusBadge";
import { Spinner } from "../components/Spinner";
import {
  AlertIcon,
  ArrowLeftIcon,
  ArrowRightIcon,
  CheckIcon,
  ClockIcon,
  DownloadIcon,
  FileIcon,
  MusicIcon,
  SparkIcon,
  WaveIcon,
} from "../components/icons";

function parseCsv(text: string): string[][] {
  return text
    .trim()
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => line.split(","));
}

function CandidateTable({ candidates, chosen }: { candidates: Candidate[]; chosen: string | null }) {
  const { t } = useI18n();
  return (
    <div className="table-wrap">
      <table className="data-table candidate-table">
        <thead>
          <tr>
            <th>{t("job.engineView")}</th>
            <th>{t("job.statusCol")}</th>
            <th>{t("job.notesCol")}</th>
            <th>{t("job.measuresCol")}</th>
            <th>{t("job.validCol")}</th>
            <th>{t("job.qualityCol")}</th>
            <th>note-F1</th>
            <th>{t("job.timeCol")}</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((candidate) => {
            const id = `${candidate.engine}/${candidate.variant}`;
            const isChosen = id === chosen;
            return (
              <tr key={id} className={isChosen ? "chosen-row" : undefined}>
                <td>
                  <span className="engine-cell">
                    {candidate.engine}
                    {candidate.mock && <span className="mini-tag">mock</span>}
                    {isChosen && <span className="mini-tag mini-tag-chosen">{t("job.chosenTag")}</span>}
                  </span>
                  <span className="engine-variant">{candidate.variant}</span>
                </td>
                <td>
                  <StatusBadge status={candidate.status} />
                </td>
                <td>{candidate.notes}</td>
                <td>{candidate.measures}</td>
                <td>{formatPct(candidate.valid_ratio, 0)}</td>
                <td>{formatPct(candidate.quality, 0)}</td>
                <td>{candidate.f1 === null ? "—" : formatPct(candidate.f1)}</td>
                <td>{candidate.seconds.toFixed(1)}s</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function JobPage() {
  const { id = "" } = useParams();
  const { t } = useI18n();
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [csv, setCsv] = useState<string | null>(null);
  const [showDetails, setShowDetails] = useState(false);
  const terminalRef = useRef(false);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    terminalRef.current = false;
    setJob(null);
    setError(null);
    setNotFound(false);
    setCsv(null);

    async function poll() {
      try {
        const data = await api.job(id);
        if (!alive) return;
        setJob(data);
        setError(null);
        setElapsed(elapsedSince(data.started_at || data.created_at));
        if (data.status === "queued" || data.status === "running") {
          timer = window.setTimeout(poll, 1500);
        } else if (!terminalRef.current) {
          terminalRef.current = true;
        }
      } catch (err) {
        if (!alive) return;
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          setError(errorMessage(err, t));
        }
      }
    }

    void poll();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [id]);

  const active = job?.status === "queued" || job?.status === "running";

  useEffect(() => {
    if (!active || !job) return;
    setElapsed(elapsedSince(job.started_at || job.created_at));
    const timer = window.setInterval(() => {
      setElapsed(elapsedSince(job.started_at || job.created_at));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [active, job]);

  useEffect(() => {
    if (!job || job.status !== "done" || !job.files.includes("notes.csv")) return;
    let alive = true;
    fetch(jobFileUrl(job.id, "notes.csv"), { credentials: "same-origin" })
      .then((response) => (response.ok ? response.text() : ""))
      .then((text) => {
        if (alive) setCsv(text);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [job]);

  useEffect(() => {
    document.title = job ? `${localizeJobLabel(job.label, t)} · ScoreOMR` : "ScoreOMR";
    return () => {
      document.title = "ScoreOMR";
    };
  }, [job, t]);

  const csvRows = useMemo(() => (csv ? parseCsv(csv) : []), [csv]);
  const jobLabel = localizeJobLabel(job?.label ?? "", t);

  if (notFound) {
    return (
      <section className="section narrow">
        <div className="empty-state">
          <FileIcon size={32} />
          <h1>{t("job.notFound")}</h1>
          <p>{t("job.notFoundText")}</p>
          <Link to="/" className="btn btn-primary">
            {t("common.backStudio")} <ArrowRightIcon size={16} />
          </Link>
        </div>
      </section>
    );
  }

  if (!job && error) {
    return (
      <section className="section narrow">
        <div className="empty-state">
          <AlertIcon size={32} />
          <h1>{t("job.loadError")}</h1>
          <p>{error}</p>
          <button type="button" className="btn btn-dark" onClick={() => window.location.reload()}>
            {t("common.reload")}
          </button>
        </div>
      </section>
    );
  }

  if (!job) {
    return (
      <div className="page-loading">
        <Spinner label={t("job.loading")} />
      </div>
    );
  }

  const report = job.report;
  const totalSeconds =
    job.started_at && job.finished_at
      ? Math.max(0, (new Date(job.finished_at).getTime() - new Date(job.started_at).getTime()) / 1000)
      : null;
  const processingLabel =
    totalSeconds === null ? null : totalSeconds < 1 ? t("job.underOne") : formatSeconds(totalSeconds);

  return (
    <>
      <section className="job-header">
        <div className="job-header-top">
          <Link to="/" className="back-link">
            <ArrowLeftIcon size={16} /> {t("job.back")}
          </Link>
          <StatusBadge status={job.status} dot />
        </div>
        <h1>{jobLabel}</h1>
        <div className="job-header-meta">
          <span>{modeLabel(job.mode)}</span>
          <span>·</span>
          <span>{formatDateTime(job.created_at)}</span>
          <span>·</span>
          <span>#{shortId(job.id)}</span>
          {totalSeconds !== null && (
            <>
              <span>·</span>
              <span>{t("job.usedFor", { time: processingLabel ?? "—" })}</span>
            </>
          )}
        </div>
      </section>

      {active && (
        <section className="section job-progress-section">
          <div className="job-progress-grid">
            <div className="job-preview-panel">
              <span className="panel-kicker">{t("job.input")}</span>
              <img className="job-input-image" src={jobFileUrl(job.id, "input.png")} alt={t("job.inputAlt")} />
            </div>
            <div className="job-progress-panel">
              <span className="panel-kicker">{job.status === "queued" ? t("job.queuedLabel") : t("job.processingLabel")}</span>
              <h2>{job.status === "queued" ? t("job.queued") : t("job.processing")}</h2>
              <p>{job.status === "queued" ? t("job.queuedDesc") : t("job.processingDesc")}</p>
              <div className="progress-staff" aria-hidden="true">
                <span />
                <span />
                <span />
                <span />
                <span />
                <i className="progress-note" />
              </div>
              <div className="progress-meta">
                <span>
                  <ClockIcon size={15} /> {t("job.waiting", { time: formatSeconds(elapsed) })}
                </span>
                <span>
                  <MusicIcon size={15} /> {modeLabel(job.mode)}
                </span>
              </div>
              {elapsed > 90 && (
                <p className="progress-tip">
                  {t("job.tooLong")}
                </p>
              )}
              <Link to="/" className="text-link">
                {t("job.submitAnother")} <ArrowRightIcon size={14} />
              </Link>
            </div>
          </div>
        </section>
      )}

      {job.status === "error" && (
        <section className="section narrow-section">
          <div className="result-error">
            <div className="result-error-icon">
              <AlertIcon size={26} />
            </div>
            <div>
              <span className="eyebrow">{t("job.failedEyebrow")}</span>
              <h2>{t("job.failed")}</h2>
              <p>{job.error || t("job.failedDesc")}</p>
              <p className="result-error-note">{t("job.failedNote")}</p>
              <div className="result-error-actions">
                <Link to="/" className="btn btn-primary">
                  {t("job.retryUpload")} <ArrowRightIcon size={16} />
                </Link>
              </div>
            </div>
          </div>
        </section>
      )}

      {job.status === "done" && report && (
        <>
          <section className="section result-section">
            <div className="result-summary">
              <div className="result-summary-main">
                <span className="eyebrow">
                  <CheckIcon size={14} /> {t("job.readyEyebrow")}
                </span>
                <h2>{t("job.ready")}</h2>
                <p>
                  {t("job.selected", {
                    engine: report.chosen ?? "—",
                    notes: report.notes,
                    duration: formatSeconds(report.duration_s),
                  })}
                </p>
              </div>
              <div className="result-score">
                <span>{t("job.quality")}</span>
                <strong>{formatPct(report.confidence, 0)}</strong>
                <small>{report.selection === "oracle" ? t("job.oracle") : t("job.heuristic")}</small>
              </div>
            </div>

            {report.mock && (
              <div className="result-banner result-banner-mock">
                <SparkIcon size={18} />
                <div>
                  <strong>{t("job.mockTitle")}</strong>
                  <p>{t("job.mockDesc")}</p>
                </div>
              </div>
            )}
            {report.needs_review && (
              <div className="result-banner result-banner-warn">
                <AlertIcon size={18} />
                <div>
                  <strong>{t("job.reviewTitle")}</strong>
                  <p>{t("job.reviewDesc")}</p>
                </div>
              </div>
            )}

            <div className="result-media">
              <figure className="result-figure">
                <img src={jobFileUrl(job.id, "input.png")} alt={t("job.inputAlt")} />
                <figcaption>{t("job.input")}</figcaption>
              </figure>
              <figure className="result-figure">
                <img src={jobFileUrl(job.id, "piano_roll.png")} alt={t("job.rollAlt")} />
                <figcaption>{t("job.roll")}</figcaption>
              </figure>
            </div>

            {job.files.includes("best.wav") ? (
              <div className="audio-panel">
                <div className="audio-panel-head">
                  <span className="audio-icon">
                    <WaveIcon size={20} />
                  </span>
                  <div>
                    <strong>{t("job.listen")}</strong>
                    <span>
                      {report.audio.bpm ? `${report.audio.bpm.toFixed(0)} BPM · ` : ""}
                      {formatSeconds(report.audio.seconds ?? report.duration_s)}
                    </span>
                  </div>
                </div>
                <audio controls preload="metadata" src={jobFileUrl(job.id, "best.wav")}>
                  {t("job.browserAudio")}
                </audio>
              </div>
            ) : (
              report.audio.error && (
                <div className="inline-error">{t("job.audioFailed", { message: report.audio.error })}</div>
              )
            )}

            <div className="download-panel">
              <div className="download-head">
                <div>
                  <span className="eyebrow">
                    <DownloadIcon size={14} /> {t("job.deliverables")}
                  </span>
                  <h3>{t("job.downloadEdit")}</h3>
                  <p>{t("job.downloadDesc")}</p>
                </div>
              </div>
              <div className="download-grid">
                {job.files.map((file) => (
                  <a
                    key={file}
                    className={classNames("download-item", file === "best.musicxml" && "download-primary")}
                    href={jobFileUrl(job.id, file)}
                    download
                  >
                    <span className="download-icon">
                      {file === "best.musicxml" ? <MusicIcon size={19} /> : <FileIcon size={19} />}
                    </span>
                    <span>
                      <strong>{downloadName(file)}</strong>
                      <small>{file}</small>
                    </span>
                    <DownloadIcon size={17} />
                  </a>
                ))}
              </div>
            </div>

            <div className="result-detail-grid">
              <div className="result-detail-card">
                <h3>{t("job.candidateTitle")}</h3>
                <p className="muted-text">{t("job.candidateDesc")}</p>
                <CandidateTable candidates={report.candidates} chosen={report.chosen} />
              </div>

              <div className="result-detail-card">
                <h3>{t("job.inputFeatures")}</h3>
                <dl className="style-list">
                  <div>
                    <dt>{t("job.dimensions")}</dt>
                    <dd>
                      {String(report.style.width ?? "—")} × {String(report.style.height ?? "—")}
                    </dd>
                  </div>
                  <div>
                    <dt>{t("job.inputType")}</dt>
                    <dd>{report.style.scan_like ? t("job.scan") : t("job.clean")}</dd>
                  </div>
                  <div>
                    <dt>{t("job.lowRes")}</dt>
                    <dd>{report.style.low_res ? t("common.yes") : t("common.no")}</dd>
                  </div>
                  <div>
                    <dt>{t("job.selection")}</dt>
                    <dd>{report.selection === "oracle" ? t("job.oracleSelect") : t("job.heuristicSelect")}</dd>
                  </div>
                  <div>
                    <dt>{t("job.notesCount")}</dt>
                    <dd>{report.notes}</dd>
                  </div>
                  <div>
                    <dt>{t("job.duration")}</dt>
                    <dd>{formatSeconds(report.duration_s)}</dd>
                  </div>
                </dl>
                <button
                  type="button"
                  className="btn btn-outline btn-small"
                  onClick={() => setShowDetails((value) => !value)}
                >
                  {showDetails ? t("job.hideDetails") : t("job.showDetails")}
                </button>
                {showDetails && (
                  <div className="explain-box">
                    <p>{t("job.explain1")}</p>
                    <p>{t("job.explain2")}</p>
                  </div>
                )}
              </div>
            </div>

            <div className="notes-panel">
              <div className="notes-head">
                <div>
                  <h3>{t("job.notesTable")}</h3>
                  <p className="muted-text">{t("job.notesDesc")}</p>
                </div>
                {job.files.includes("notes.csv") && (
                  <a className="text-link" href={jobFileUrl(job.id, "notes.csv")} download>
                    {t("job.downloadCsv")} <DownloadIcon size={14} />
                  </a>
                )}
              </div>
              {csv ? (
                <div className="table-wrap">
                  <table className="data-table notes-table">
                    <thead>
                      <tr>
                        {csvRows[0]?.map((heading) => <th key={heading}>{heading}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {csvRows.slice(1, 41).map((row, index) => (
                        <tr key={index}>
                          {row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="muted-text">{t("job.notesLoading")}</p>
              )}
            </div>

            <div className="result-footer-actions">
              <Link to="/" className="btn btn-primary">
                {t("job.again")} <ArrowRightIcon size={16} />
              </Link>
            </div>
          </section>
        </>
      )}

      {job.status === "done" && !report && (
        <section className="section narrow">
          <div className="empty-state">
            <FileIcon size={30} />
            <h1>{t("job.resultLost")}</h1>
            <p>{t("job.resultLostDesc")}</p>
            <Link to="/" className="btn btn-primary">
              {t("job.retryUpload")} <ArrowRightIcon size={16} />
            </Link>
          </div>
        </section>
      )}
    </>
  );
}
