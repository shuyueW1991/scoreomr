import { getLocale, getLocaleTag, translate, type MessageKey } from "./i18n";
import type { Mode, Quota } from "./types";

export function classNames(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(getLocaleTag(), {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(getLocaleTag(), {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}


export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value < 60) return translate(getLocale(), "common.seconds", { value: value.toFixed(1) });
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value - minutes * 60);
  return translate(getLocale(), "common.minutesSeconds", { m: minutes, s: seconds });
}


export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function modeLabel(mode: Mode): string {
  const key = `mode.${mode}.name` as MessageKey;
  return translate(getLocale(), key);
}


export function statusLabel(status: string): string {
  const known = new Set(["queued", "running", "done", "error", "ok", "missing", "timeout", "failed", "invalid"]);
  if (!known.has(status)) return status;
  return translate(getLocale(), `status.${status}` as MessageKey);
}

export function statusTone(status: string): string {
  switch (status) {
    case "done":
    case "ok":
      return "good";
    case "queued":
      return "neutral";
    case "running":
      return "warning";
    case "error":
    case "failed":
    case "timeout":
    case "missing":
    case "invalid":
      return "bad";
    default:
      return "neutral";
  }
}

export function quotaText(quota: Quota): string {
  if (quota.remaining_today <= 0) return translate(getLocale(), "quota.exhausted");
  return translate(getLocale(), "quota.remaining", { count: quota.remaining_today });
}

export function resetText(quota: Quota): string {
  if (!quota.resets_at) return "";
  try {
    return new Intl.DateTimeFormat(getLocaleTag(), {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: quota.timezone || "Asia/Shanghai",
    }).format(new Date(quota.resets_at));
  } catch {
    return "";
  }
}

export function elapsedSince(iso: string | null | undefined): number {
  if (!iso) return 0;
  const started = new Date(iso).getTime();
  if (Number.isNaN(started)) return 0;
  return Math.max(0, Math.round((Date.now() - started) / 1000));
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

export function downloadName(name: string): string {
  const key = `download.${name}` as MessageKey;
  if (["best.musicxml", "best.mid", "best.wav", "notes.csv", "piano_roll.png", "report.json"].includes(name)) {
    return translate(getLocale(), key);
  }
  return name;
}
