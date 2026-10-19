import type { Mode } from "../lib/types";
import { CameraIcon, LayersIcon, ScanIcon } from "./icons";
import { classNames } from "../lib/format";
import { useI18n, type MessageKey } from "../lib/i18n";

const MODES: Array<{
  id: Mode;
  icon: typeof LayersIcon;
  tagline: boolean;
  points: MessageKey[];
}> = [
  { id: "compare", tagline: true, icon: LayersIcon, points: ["mode.compare.point1", "mode.compare.point2"] },
  { id: "audiveris", tagline: false, icon: ScanIcon, points: ["mode.audiveris.point1", "mode.audiveris.point2"] },
  { id: "homr", tagline: false, icon: CameraIcon, points: ["mode.homr.point1", "mode.homr.point2"] },
];

export function ModePicker({
  value,
  onChange,
  disabled,
}: {
  value: Mode;
  onChange: (mode: Mode) => void;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  return (
    <fieldset className="mode-fieldset" disabled={disabled}>
      <legend className="field-label">{t("mode.legend")}</legend>
      <div className="mode-grid">
        {MODES.map((mode) => {
          const Icon = mode.icon;
          const active = value === mode.id;
          return (
            <label
              key={mode.id}
              className={classNames("mode-card", active && "mode-card-active")}
            >
              <input
                type="radio"
                name="mode"
                value={mode.id}
                checked={active}
                onChange={() => onChange(mode.id)}
              />
              <span className="mode-card-head">
                <span className="mode-icon">
                  <Icon size={19} />
                </span>
                <span className="mode-name">{t(`mode.${mode.id}.name` as MessageKey)}</span>
                {mode.tagline && (
                  <span className={classNames("mode-tag", active && "mode-tag-active")}>
                    {t("mode.compare.tag")}
                  </span>
                )}
              </span>
              <span className="mode-desc">{t(`mode.${mode.id}.desc` as MessageKey)}</span>
              <span className="mode-points">
                {mode.points.map((point) => (
                  <span key={point}>{t(point)}</span>
                ))}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
