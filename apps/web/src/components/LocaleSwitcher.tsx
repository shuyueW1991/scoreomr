import { LOCALES, useI18n, type Locale } from "../lib/i18n";

export function LocaleSwitcher() {
  const { locale, setLocale, t } = useI18n();
  return (
    <div className="language-switch" role="group" aria-label={t("nav.language")}>
      {LOCALES.map((item) => (
        <button
          key={item.id}
          type="button"
          className={item.id === locale ? "active" : undefined}
          aria-pressed={item.id === locale}
          title={item.label}
          lang={item.id}
          onClick={() => setLocale(item.id as Locale)}
        >
          {item.short}
        </button>
      ))}
    </div>
  );
}
