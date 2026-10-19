import { classNames, statusLabel, statusTone } from "../lib/format";

export function StatusBadge({
  status,
  label,
  tone,
  dot = false,
}: {
  status?: string;
  label?: string;
  tone?: string;
  dot?: boolean;
}) {
  const resolvedTone = tone || (status ? statusTone(status) : "neutral");
  return (
    <span className={classNames("badge", `badge-${resolvedTone}`)}>
      {dot && <span className="badge-dot" />}
      {label || (status ? statusLabel(status) : "")}
    </span>
  );
}
