import { useEffect } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { classNames } from "../lib/format";
import { useConfig } from "../lib/config";
import { useI18n } from "../lib/i18n";
import { Brand } from "./Brand";
import { LocaleSwitcher } from "./LocaleSwitcher";

function NavItem({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) => classNames("nav-link", isActive && "active")}
    >
      {label}
    </NavLink>
  );
}

function ScrollManager() {
  const { pathname, hash } = useLocation();
  useEffect(() => {
    if (hash) {
      const element = document.getElementById(hash.slice(1));
      if (element) {
        window.requestAnimationFrame(() => element.scrollIntoView({ behavior: "smooth", block: "start" }));
        return;
      }
    }
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, [pathname, hash]);
  return null;
}

export function Layout() {
  const { error } = useConfig();
  const { t } = useI18n();
  return (
    <div className="site-shell">
      <ScrollManager />
      <header className="site-header">
        <div className="header-inner">
          <Brand />
          <nav className="main-nav" aria-label={t("nav.main")}>
            <NavItem to="/" label={t("nav.studio")} />
            <NavItem to="/account" label={t("nav.history")} />
          </nav>
          <div className="header-actions">
            <LocaleSwitcher />
          </div>
        </div>
        {error && (
          <div className="connection-banner" role="alert">
            <strong>{t("error.connection")}</strong>
            {error}
          </div>
        )}
      </header>

      <main className="site-main">
        <Outlet />
      </main>

      <footer className="site-footer">
        <div className="footer-inner">
          <div className="footer-brand">
            <Brand />
            <p>{t("footer.tagline")}</p>
          </div>
          <div className="footer-col">
            <h4>{t("footer.product")}</h4>
            <Link to="/">{t("nav.studio")}</Link>
            <Link to="/account">{t("nav.history")}</Link>
          </div>
          <div className="footer-col">
            <h4>{t("footer.tech")}</h4>
            <a href="/api/health" target="_blank" rel="noreferrer">
              {t("footer.status")}
            </a>
            <a href="/api/config" target="_blank" rel="noreferrer">
              {t("footer.config")}
            </a>
            <span className="footer-static">Audiveris 5.11 · homr 0.7</span>
          </div>
          <div className="footer-col footer-legal">
            <h4>{t("footer.notes")}</h4>
            <p>{t("footer.demoData")}</p>
            <p>{t("footer.engineLicense")}</p>
          </div>
        </div>
        <div className="footer-bottom">
          <span>{t("footer.copyright", { year: new Date().getFullYear() })}</span>
          <span>{t("footer.disclaimer")}</span>
        </div>
      </footer>
    </div>
  );
}