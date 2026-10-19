import { Link } from "react-router-dom";
import { useI18n } from "../lib/i18n";

export function Brand({ compact = false }: { compact?: boolean }) {
  const { t } = useI18n();
  return (
    <Link to="/" className="brand" aria-label={t("brand.home")}>
      <svg className="brand-mark" viewBox="0 0 56 56" aria-hidden="true">
        <rect width="56" height="56" fill="#111111" />
        <circle cx="19" cy="36" r="10" fill="#f2c200" />
        <rect x="28" y="9" width="6" height="29" fill="#f3efe4" />
        <path d="M34 9h12l-3 8h-9z" fill="#e63329" />
        <rect x="9" y="49" width="38" height="2.5" fill="#1f4fd8" />
      </svg>
      <span className="brand-text">
        <strong>ScoreOMR</strong>
        {!compact && <small>OMR WORKBENCH</small>}
      </span>
    </Link>
  );
}
