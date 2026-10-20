import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { formatDateTime, modeLabel } from "../lib/format";
import { localizeJobLabel, useI18n } from "../lib/i18n";
import type { JobSummary } from "../lib/types";
import { StatusBadge } from "../components/StatusBadge";
import { Spinner } from "../components/Spinner";
import { ArrowRightIcon, FileIcon, RefreshIcon } from "../components/icons";

export function AccountPage() {
  const { t } = useI18n();
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .jobs()
      .then((result) => {
        if (alive) setJobs(result.jobs);
      })
      .catch(() => {
        if (alive) setJobs([]);
      });
    return () => {
      alive = false;
    };
  }, []);

  async function reload() {
    setJobs(null);
    try {
      const result = await api.jobs();
      setJobs(result.jobs);
    } catch {
      setJobs([]);
    }
  }

  return (
    <section className="section account-history-section">
      <div className="section-heading section-heading-split">
        <div>
          <span className="eyebrow">{t("account.history")}</span>
          <h1>{t("account.recent")}</h1>
          <p>{t("account.localNote")}</p>
        </div>
        <button type="button" className="btn btn-outline btn-small" onClick={reload}>
          <RefreshIcon size={15} /> {t("account.refreshJobs")}
        </button>
      </div>

      {jobs === null ? (
        <div className="page-loading small">
          <Spinner label={t("account.loadingJobs")} />
        </div>
      ) : jobs.length === 0 ? (
        <div className="empty-state compact">
          <FileIcon size={26} />
          <h3>{t("account.noJobs")}</h3>
          <p>{t("account.noJobsText")}</p>
          <Link to="/" className="btn btn-primary">
            {t("account.goStudio")} <ArrowRightIcon size={16} />
          </Link>
        </div>
      ) : (
        <div className="job-list">
          {jobs.map((job) => (
            <Link to={`/jobs/${job.id}`} className="job-row" key={job.id}>
              <span className="job-row-main">
                <span className="job-row-title">{localizeJobLabel(job.label, t)}</span>
                <span className="job-row-meta">
                  {modeLabel(job.mode)} · {formatDateTime(job.created_at)}
                  {job.chosen ? ` · ${t("job.chosen")} ${job.chosen}` : ""}
                </span>
              </span>
              <StatusBadge status={job.status} dot />
              <ArrowRightIcon size={17} />
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}