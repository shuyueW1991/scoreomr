import { Link } from "react-router-dom";
import { ArrowRightIcon, MusicIcon } from "../components/icons";
import { useI18n } from "../lib/i18n";

export function NotFoundPage() {
  const { t } = useI18n();
  return (
    <section className="section narrow">
      <div className="empty-state">
        <MusicIcon size={34} />
        <span className="eyebrow">404</span>
        <h1>{t("notfound.title")}</h1>
        <p>{t("notfound.desc")}</p>
        <Link to="/" className="btn btn-primary">
          {t("common.backStudio")} <ArrowRightIcon size={16} />
        </Link>
      </div>
    </section>
  );
}
