import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../lib/api";
import { errorMessage, useI18n, type MessageKey } from "../lib/i18n";
import { useMe } from "../lib/me";
import { useToast } from "../lib/toast";
import { Spinner } from "../components/Spinner";
import { AlertIcon, ArrowRightIcon, CheckIcon, GoogleIcon, MusicIcon, ShieldIcon } from "../components/icons";

function safeNext(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/";
  return value;
}

const GOOGLE_ERRORS: Record<string, MessageKey> = {
  google_not_configured: "auth.googleNotConfigured",
  google_state: "auth.googleState",
  google_denied: "auth.googleDenied",
  google_exchange_failed: "auth.googleExchange",
  google_email_unverified: "auth.googleUnverified",
  google_account_exists: "auth.googleAccountExists",
  google_email_mismatch: "auth.googleEmailMismatch",
  google_already_linked: "auth.googleAlreadyLinked",
  google_failed: "auth.googleFailed",
};

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { me, config, loading, setMe } = useMe();
  const { t } = useI18n();
  const navigate = useNavigate();
  const { notify } = useToast();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(() => {
    const code = params.get("error");
    return code ? t(GOOGLE_ERRORS[code] || "auth.googleFailed") : null;
  });

  const isRegister = mode === "register";

  useEffect(() => {
    if (!loading && me?.user) {
      navigate(next, { replace: true });
    }
  }, [loading, me?.user, navigate, next]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (isRegister && password !== confirm) {
      setError(t("auth.errorMismatch"));
      return;
    }
    if (password.length < 8) {
      setError(t("auth.errorMin"));
      return;
    }
    setBusy(true);
    try {
      const result = isRegister ? await api.register(email, password) : await api.login(email, password);
      setMe(result);
      notify(isRegister ? t("auth.created") : t("auth.signedIn"), "success");
      navigate(next, { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError(t("auth.badCredentials"));
      } else if (err instanceof ApiError && err.status === 409) {
        setError(t("auth.emailTaken"));
      } else {
        setError(errorMessage(err, t));
      }
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="page-loading">
        <Spinner label={t("auth.loading")} />
      </div>
    );
  }

  return (
    <section className="auth-section">
      <div className="auth-shell">
        <aside className="auth-aside">
          <span className="eyebrow">
            <MusicIcon size={14} /> {t("auth.eyebrow")}
          </span>
          <h1>{isRegister ? t("auth.titleRegister") : t("auth.titleLogin")}</h1>
          <p>{t("auth.asideDesc")}</p>
          <ul className="auth-points">
            <li>
              <CheckIcon size={17} /> {t("auth.point1")}
            </li>
            <li>
              <CheckIcon size={17} /> {t("auth.point2")}
            </li>
            <li>
              <ShieldIcon size={17} /> {t("auth.point3")}
            </li>
          </ul>
          <div className="auth-quote">
            <span>“</span>
            {t("auth.quote")}
          </div>
        </aside>

        <div className="auth-card">
          <div className="auth-card-head">
            <span className="eyebrow">{isRegister ? t("auth.cardEyebrowRegister") : t("auth.cardEyebrowLogin")}</span>
            <h2>{isRegister ? t("auth.cardTitleRegister") : t("auth.cardTitleLogin")}</h2>
            <p>{isRegister ? t("auth.cardDescRegister") : t("auth.cardDescLogin")}</p>
          </div>

          {config?.google_auth_enabled ? (
            <a
              className="google-btn"
              href={`/api/auth/google/start?next=${encodeURIComponent(next)}`}
            >
              <GoogleIcon size={20} />
              {t("auth.google")}
            </a>
          ) : (
            <div className="google-unavailable">
              {t("auth.googleUnavailable")}
            </div>
          )}

          <div className="auth-divider">
            <span>{t("auth.divider")}</span>
          </div>

          <form onSubmit={onSubmit} className="auth-form">
            <label className="field-label" htmlFor="email">
              {t("auth.email")}
            </label>
            <input
              id="email"
              className="text-input"
              type="email"
              autoComplete="email"
              required
              maxLength={254}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
            />

            <label className="field-label" htmlFor="password">
              {t("auth.password")}
            </label>
            <input
              id="password"
              className="text-input"
              type="password"
              autoComplete={isRegister ? "new-password" : "current-password"}
              required
              minLength={8}
              maxLength={128}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={t("auth.passwordPlaceholder")}
            />

            {isRegister && (
              <>
                <label className="field-label" htmlFor="confirm">
                  {t("auth.confirm")}
                </label>
                <input
                  id="confirm"
                  className="text-input"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={8}
                  maxLength={128}
                  value={confirm}
                  onChange={(event) => setConfirm(event.target.value)}
                  placeholder={t("auth.confirmPlaceholder")}
                />
              </>
            )}

            {error && (
              <div className="form-alert" role="alert">
                <AlertIcon size={18} />
                <div>
                  <strong>{isRegister ? t("auth.errorRegister") : t("auth.errorLogin")}</strong>
                  <p>{error}</p>
                </div>
              </div>
            )}

            <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
              {busy ? (
                <Spinner label={isRegister ? t("auth.creating") : t("auth.loggingIn")} />
              ) : (
                <>
                  {isRegister ? t("auth.register") : t("auth.login")} <ArrowRightIcon size={17} />
                </>
              )}
            </button>
          </form>

          <p className="auth-switch">
            {isRegister ? (
              <>
                {t("auth.switchLoginText")}{" "}
                <Link to={`/login?next=${encodeURIComponent(next)}`}>{t("auth.switchLoginLink")}</Link>
              </>
            ) : (
              <>
                {t("auth.switchRegisterText")}{" "}
                <Link to={`/register?next=${encodeURIComponent(next)}`}>{t("auth.switchRegisterLink")}</Link>
              </>
            )}
          </p>
          <p className="auth-fineprint">
            {t("auth.fineprint", { days: config?.job_retention_days ?? 7 })}
          </p>
        </div>
      </div>
    </section>
  );
}
