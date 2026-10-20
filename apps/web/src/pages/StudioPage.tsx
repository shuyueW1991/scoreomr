import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../lib/api";
import { classNames, formatPct } from "../lib/format";
import { errorMessage, useI18n, type MessageKey } from "../lib/i18n";
import { useConfig } from "../lib/config";
import { useToast } from "../lib/toast";
import type { Mode, Sample } from "../lib/types";
import { SampleGrid } from "../components/SampleGrid";
import { Spinner } from "../components/Spinner";
import { UploadPanel } from "../components/UploadPanel";
import {
  ArrowRightIcon,
  CameraIcon,
  LayersIcon,
  ScanIcon,
  ShieldIcon,
  SparkIcon,
  WaveIcon,
} from "../components/icons";

const EVIDENCE: Array<{
  label: MessageKey;
  audiveris: number | null;
  homr: number;
  best: string;
}> = [
  { label: "home.evidence.row.clean", audiveris: 1.0, homr: 0.099, best: "Audiveris" },
  { label: "home.evidence.row.fragment", audiveris: 0.193, homr: 0.907, best: "homr" },
  { label: "home.evidence.row.phone", audiveris: 1.0, homr: 0.827, best: "Audiveris" },
  { label: "home.evidence.row.scanA", audiveris: 0.351, homr: 1.0, best: "homr" },
  { label: "home.evidence.row.lowres", audiveris: 0.0, homr: 0.617, best: "homr" },
  { label: "home.evidence.row.degraded", audiveris: null, homr: 1.0, best: "homr" },
];

const WORKFLOW: Array<{
  icon: typeof ScanIcon;
  title: MessageKey;
  text: MessageKey;
}> = [
  { icon: ScanIcon, title: "home.workflow.1.title", text: "home.workflow.1.text" },
  { icon: LayersIcon, title: "home.workflow.2.title", text: "home.workflow.2.text" },
  { icon: ShieldIcon, title: "home.workflow.3.title", text: "home.workflow.3.text" },
  { icon: WaveIcon, title: "home.workflow.4.title", text: "home.workflow.4.text" },
];

function EvidenceBar({ value, tone }: { value: number | null; tone: "a" | "h" }) {
  const { t } = useI18n();
  if (value === null) {
    return <span className="bar-failed">{t("home.evidence.failed")}</span>;
  }
  return (
    <span className="bar-track">
      <span
        className={classNames("bar-fill", tone === "a" ? "bar-a" : "bar-h")}
        style={{ width: `${Math.max(value * 100, 1.5)}%` }}
      />
      <span className="bar-value">{formatPct(value, value === 0 ? 0 : 1)}</span>
    </span>
  );
}

export function StudioPage() {
  const { config, loading, error } = useConfig();
  const { t } = useI18n();
  const { notify } = useToast();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("compare");
  const [samples, setSamples] = useState<Sample[] | null>(null);
  const [samplesError, setSamplesError] = useState<string | null>(null);
  const [busySample, setBusySample] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .samples()
      .then((result) => {
        if (alive) setSamples(result.samples);
      })
      .catch((err) => {
        if (alive) setSamplesError(errorMessage(err, t));
      });
    return () => {
      alive = false;
    };
  }, [t]);

  async function runSample(sample: Sample) {
    if (busySample) return;
    setBusySample(sample.id);
    try {
      const result = await api.runSample(sample.id, "compare");
      navigate(`/jobs/${result.job.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "active_job_exists") {
        const activeJob = typeof err.extra.active_job === "string" ? err.extra.active_job : null;
        if (activeJob) {
          notify(t("error.active_job_exists"), "info");
          navigate(`/jobs/${activeJob}`);
        } else {
          notify(t("error.active_job_exists"), "error");
        }
      } else {
        notify(errorMessage(err, t), "error");
      }
    } finally {
      setBusySample(null);
    }
  }

  if (loading) {
    return (
      <div className="page-loading">
        <Spinner label={t("common.loading")} />
      </div>
    );
  }

  if (!config) {
    return (
      <section className="section narrow">
        <div className="empty-state">
          <SparkIcon size={30} />
          <h1>{t("common.unavailable")}</h1>
          <p>{error || t("error.loadConfig")}</p>
          <button type="button" className="btn btn-dark" onClick={() => window.location.reload()}>
            {t("common.reload")}
          </button>
        </div>
      </section>
    );
  }

  return (
    <>
      <section className="hero">
        <div className="hero-grid">
          <div className="hero-copy">
            <span className="eyebrow">
              <span className="live-dot" />
              {t("home.eyebrow")}
            </span>
            <h1>
              {t("home.title1")}
              <br />
              <em>{t("home.title2")}</em>
            </h1>
            <p className="hero-lede">{t("home.lede")}</p>
            <div className="hero-actions">
              <a className="btn btn-primary" href="#samples">
                {t("home.try")} <ArrowRightIcon size={17} />
              </a>
              <a className="btn btn-outline" href="#workflow">
                {t("home.how")}
              </a>
            </div>
            <ul className="hero-points">
              <li>
                <ShieldIcon size={16} /> {t("home.pointLocal")}
              </li>
              <li>
                <CameraIcon size={16} /> {t("home.pointInput")}
              </li>
            </ul>
            <div className="hero-specs">
              <span><b>{t("home.spec1a")}</b> {t("home.spec1b")}</span>
              <span><b>{t("home.spec2a")}</b> {t("home.spec2b")}</span>
              <span><b>{t("home.spec3a")}</b> {t("home.spec3b")}</span>
            </div>
          </div>

          <div className="hero-panel">
            <UploadPanel
              config={config}
              mode={mode}
              setMode={setMode}
              onCreated={(jobId) => navigate(`/jobs/${jobId}`)}
            />
          </div>
        </div>

        <div className="hero-stats">
          <div className="stat">
            <strong>9</strong>
            <span>{t("home.stats.samples")}</span>
          </div>
          <div className="stat">
            <strong>6 / 9</strong>
            <span>{t("home.stats.f1")}</span>
          </div>
          <div className="stat">
            <strong>2</strong>
            <span>{t("home.stats.engines")}</span>
          </div>
          <div className="stat stat-wide">
            <strong>{t("home.stats.noSingle")}</strong>
            <span>{t("home.stats.noSingleSub")}</span>
          </div>
        </div>
      </section>

      {config.omr_mock && (
        <div className="global-notice">
          <SparkIcon size={17} />
          <span>{t("home.mock")}</span>
        </div>
      )}

      <section className="section" id="workflow">
        <div className="section-heading">
          <span className="eyebrow">{t("home.workflow.eyebrow")}</span>
          <h2>{t("home.workflow.title")}</h2>
          <p>{t("home.workflow.lede")}</p>
        </div>
        <div className="workflow-grid">
          {WORKFLOW.map((step, index) => {
            const Icon = step.icon;
            return (
              <div className="workflow-card" key={step.title}>
                <span className="workflow-index">0{index + 1}</span>
                <span className="workflow-icon">
                  <Icon size={22} />
                </span>
                <h3>{t(step.title)}</h3>
                <p>{t(step.text)}</p>
              </div>
            );
          })}
        </div>
      </section>

      <section className="section samples-section" id="samples">
        <div className="section-heading">
          <span className="eyebrow">{t("home.samples.eyebrow")}</span>
          <h2>{t("home.samples.title")}</h2>
          <p>{t("home.samples.lede")}</p>
        </div>

        {samples ? (
          <SampleGrid samples={samples} busyId={busySample} onRun={runSample} />
        ) : samplesError ? (
          <div className="inline-error">{t("home.samples.loadError", { message: samplesError })}</div>
        ) : (
          <div className="sample-grid">
            {Array.from({ length: 6 }).map((_, index) => (
              <div className="sample-skeleton" key={index} />
            ))}
          </div>
        )}
      </section>

      <section className="section evidence-section" id="evidence">
        <div className="section-heading">
          <span className="eyebrow">{t("home.evidence.eyebrow")}</span>
          <h2>{t("home.evidence.title")}</h2>
          <p>{t("home.evidence.lede")}</p>
        </div>
        <div className="evidence-card">
          <div className="evidence-legend">
            <span>
              <i className="legend-dot legend-a" /> Audiveris
            </span>
            <span>
              <i className="legend-dot legend-h" /> homr
            </span>
            <span className="legend-note">{t("home.evidence.legend")}</span>
          </div>
          <div className="evidence-rows">
            {EVIDENCE.map((row) => (
              <div className="evidence-row" key={row.label}>
                <span className="evidence-label">{t(row.label)}</span>
                <div className="evidence-bars">
                  <div className="evidence-bar-line">
                    <EvidenceBar value={row.audiveris} tone="a" />
                  </div>
                  <div className="evidence-bar-line">
                    <EvidenceBar value={row.homr} tone="h" />
                  </div>
                </div>
                <span className="evidence-best">{t("home.evidence.best", { engine: row.best })}</span>
              </div>
            ))}
          </div>
          <p className="evidence-footnote">{t("home.evidence.note")}</p>
        </div>
      </section>

    </>
  );
}