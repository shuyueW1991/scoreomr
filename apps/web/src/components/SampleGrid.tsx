import { useMemo, useState } from "react";
import type { Sample } from "../lib/types";
import { classNames } from "../lib/format";
import { useI18n, type MessageKey } from "../lib/i18n";
import { Spinner } from "./Spinner";
import { ArrowRightIcon } from "./icons";

export function SampleGrid({
  samples,
  busyId,
  onRun,
  disabled,
}: {
  samples: Sample[];
  busyId: string | null;
  onRun: (sample: Sample) => void;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const categories = useMemo(() => {
    const found = new Map<string, string>();
    for (const sample of samples) {
      found.set(sample.category, t(`sample.categories.${sample.category}` as MessageKey));
    }
    return [["all", t("sample.all")], ...Array.from(found.entries())] as Array<[string, string]>;
  }, [samples, t]);
  const [active, setActive] = useState("all");
  const filtered = active === "all" ? samples : samples.filter((sample) => sample.category === active);
  const nameOf = (sample: Sample) => t(`sample.${sample.id}.name` as MessageKey);
  const blurbOf = (sample: Sample) => t(`sample.${sample.id}.blurb` as MessageKey);

  return (
    <div className="samples-block">
      <div className="samples-tabs" role="tablist" aria-label={t("sample.tabsAria")}>
        {categories.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={active === key}
            className={classNames("filter-pill", active === key && "filter-pill-active")}
            onClick={() => setActive(key)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="sample-grid">
        {filtered.map((sample) => (
          <button
            key={sample.id}
            type="button"
            className="sample-card"
            onClick={() => onRun(sample)}
            disabled={disabled || busyId !== null}
            aria-label={t("sample.runAria", { name: nameOf(sample) })}
          >
            <span className="sample-image-wrap">
              <img src={sample.image_url} alt="" loading="lazy" />
              <span className="sample-category">{t(`sample.categories.${sample.category}` as MessageKey)}</span>
              <span className="sample-hover">
                {busyId === sample.id ? <Spinner label={t("sample.submitting")} /> : <><ArrowRightIcon size={16} /> {t("sample.run")}</>}
              </span>
            </span>
            <span className="sample-body">
              <strong>{nameOf(sample)}</strong>
              <span className="sample-blurb">{blurbOf(sample)}</span>
              <span className="sample-meta">
                {sample.gt_notes ? t("sample.gtNotes", { count: sample.gt_notes }) : t("sample.noGt")}
                <span>·</span>
                {t("sample.oneJob")}
              </span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
