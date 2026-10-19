import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { formatDateTime, modeLabel, resetText } from "../lib/format";
import { localizeJobLabel, useI18n, type MessageKey } from "../lib/i18n";
import { useMe } from "../lib/me";
import { useToast } from "../lib/toast";
import type { JobSummary } from "../lib/types";
import { StatusBadge } from "../components/StatusBadge";
import { Spinner } from "../components/Spinner";
import {
  ArrowRightIcon,
  ClockIcon,
  FileIcon,
  LogoutIcon,
  ShieldIcon,
  SparkIcon,
  UserIcon,
} from "../components/icons";

const GOOGLE_BIND_ERRORS: Record<string, MessageKey> = {
  google_email_mismatch: "account.bindErrorMismatch",
  google_already_linked: "account.bindErrorLinked",
  google_not_configured: "account.bindErrorNotConfigured",
  google_state: "account.bindErrorState",
  google_exchange_failed: "account.bindErrorExchange",
  google_email_unverified: "account.bindErrorUnverified",
  google_failed: "account.bindErrorGeneric",
};

export function AccountPage() {
  const { me, config, loading, logout, refresh } = useMe();
  const { t } = useI18n();
  const navigate = useNavigate();
  const { notify } = useToast();
  const [params] = useSearchParams();
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    if (!loading && !me?.user) {
      navigate("/login?next=/account", { replace: true });
    }
  }, [loading, me?.user, navigate]);

  useEffect(() => {
    const code = params.get("google_error");
    if (!code) return;
    notify(t(GOOGLE_BIND_ERRORS[code] || "account.bindErrorGeneric"), "error");
    navigate("/account", { replace: true });
  }, [params, notify, navigate, t]);

  useEffect(() => {
    if (!me?.user) return;
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
  }, [me?.user]);

  async function onLogout() {
    setLoggingOut(true);
    try {
      await logout();
      notify(t("account.signedOut"), "info");
      navigate("/");
    } catch {
      notify(t("error.logout"), "error");
    } finally {
      setLoggingOut(false);
    }
  }

  if (loading || !me?.user) {
    return (
      <div className="page-loading">
        <Spinner label={t("account.loading")} />
      </div>
    );
  }

  const user = me.user;
  const quota = me.quota;
  const jobCount = jobs === null ? "—" : String(jobs.length);

  return (
    <>
      <section className="account-hero">
        <div>
          <span className="eyebrow">
            <UserIcon size={14} /> {t("account.title")}
          </span>
          <h1>{t("account.title")}</h1>
          <p>
            {user.email}
            {user.google_linked && <span className="account-provider">{t("account.googleLinked")}</span>}
          </p>
        </div>
        <div className="account-hero-actions">
          {config?.google_auth_enabled && !user.google_linked && (
            <a className="btn btn-outline" href="/api/auth/google/start?next=/account">
              {t("account.bindGoogle")}
            </a>
          )}
          <button type="button" className="btn btn-outline" onClick={onLogout} disabled={loggingOut}>
            {loggingOut ? <Spinner label={t("account.loggingOut")} /> : <><LogoutIcon size={16} /> {t("account.logout")}</>}
          </button>
        </div>
      </section>

      <section className="section account-grid-section">
        <div className="account-grid">
          <article className="account-card">
            <span className="account-card-kicker">{t("account.todayQuota")}</span>
            <div className="account-card-value">
              <ShieldIcon size={20} /> {t("account.freeUse", { remaining: quota.remaining_today, limit: quota.daily_limit })}
            </div>
            <p>{t("account.reset", { time: resetText(quota), timezone: quota.timezone })}</p>
          </article>

          <article className="account-card">
            <span className="account-card-kicker">{t("account.savedJobs")}</span>
            <div className="account-card-value">
              <FileIcon size={19} /> {jobCount}
            </div>
            <p>{t("account.savedJobsText")}</p>
          </article>

          <article className="account-card">
            <span className="account-card-kicker">{t("account.created")}</span>
            <div className="account-card-value">
              <ClockIcon size={19} /> {formatDateTime(user.created_at)}
            </div>
            <p>{t("account.retention", { days: config?.job_retention_days ?? 7 })}</p>
          </article>

          <article className="account-card account-card-soft">
            <span className="account-card-kicker">{t("account.openTitle")}</span>
            <div className="account-card-value">
              <SparkIcon size={19} /> {t("account.openValue")}
            </div>
            <p>{t("account.openText")}</p>
          </article>
        </div>
      </section>

      <section className="section">
        <div className="section-heading section-heading-split">
          <div>
            <span className="eyebrow">{t("account.history")}</span>
            <h2>{t("account.recent")}</h2>
          </div>
          <button type="button" className="btn btn-outline btn-small" onClick={() => refresh()}>
            {t("account.refresh")}
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
    </>
  );
}
