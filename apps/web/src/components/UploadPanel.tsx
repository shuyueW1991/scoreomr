import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type FormEvent,
} from "react";
import { ApiError, api } from "../lib/api";
import { classNames, formatBytes, resetText } from "../lib/format";
import { errorMessage, useI18n } from "../lib/i18n";
import type { AppConfig, Me, Mode } from "../lib/types";
import { ModePicker } from "./ModePicker";
import { Spinner } from "./Spinner";
import { AlertIcon, ArrowRightIcon, FileIcon, SparkIcon, UploadIcon, XIcon } from "./icons";

const ACCEPT = ".png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.pdf";
const GT_ACCEPT = ".xml,.musicxml,.mxl";

export function UploadPanel({
  config,
  me,
  mode,
  setMode,
  onCreated,
  refreshMe,
}: {
  config: AppConfig;
  me: Me;
  mode: Mode;
  setMode: (mode: Mode) => void;
  onCreated: (jobId: string) => void;
  refreshMe: () => Promise<void>;
}) {
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [gtFile, setGtFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quotaError, setQuotaError] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const exhausted = (me.quota.remaining_today ?? 0) <= 0;
  const limitMb = config.max_upload_mb;

  useEffect(() => {
    if (!file || !file.type.startsWith("image/")) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function acceptFile(next: File | undefined) {
    setError(null);
    setQuotaError(false);
    if (!next) return;
    if (!/\.(png|jpe?g|webp|bmp|tiff?|pdf)$/i.test(next.name)) {
      setError(t("upload.fileTypeError"));
      return;
    }
    if (next.size > limitMb * 1024 * 1024) {
      setError(t("upload.fileSizeError", { size: limitMb }));
      return;
    }
    setFile(next);
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    acceptFile(event.target.files?.[0]);
    event.target.value = "";
  }

  function onDrop(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault();
    setDragging(false);
    acceptFile(event.dataTransfer.files?.[0]);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!file || busy || exhausted) return;
    setBusy(true);
    setError(null);
    setQuotaError(false);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("mode", mode);
      if (gtFile) {
        form.append("use_gt", "1");
        form.append("gt", gtFile);
      }
      const result = await api.createJob(form);
      await refreshMe();
      onCreated(result.job.id);
    } catch (err) {
      if (err instanceof ApiError && err.code === "quota_exceeded") {
        setQuotaError(true);
        setError(t("error.quota_exceeded"));
      } else {
        setError(errorMessage(err, t));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="upload-card" onSubmit={onSubmit} aria-busy={busy}>
      <div className="upload-head">
        <div>
          <span className="eyebrow">{t("upload.eyebrow")}</span>
          <h2>{t("upload.title")}</h2>
        </div>
        <span className="upload-limit">{t("upload.limit", { size: limitMb })}</span>
      </div>

      <input
        ref={inputRef}
        className="visually-hidden"
        type="file"
        accept={ACCEPT}
        onChange={onFileChange}
        tabIndex={-1}
      />
      <button
        type="button"
        className={classNames("dropzone", dragging && "dropzone-active", file && "dropzone-filled")}
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        aria-label={t("upload.selectAria")}
      >
        {file ? (
          <>
            {preview ? (
              <img className="drop-preview" src={preview} alt={t("upload.previewAlt")} />
            ) : (
              <span className="drop-file-icon">
                <FileIcon size={30} />
              </span>
            )}
            <span className="drop-file-meta">
              <strong>{file.name}</strong>
              <span>
                {formatBytes(file.size)} · {file.type === "application/pdf" ? t("upload.pdfFirst") : t("upload.image")}
              </span>
            </span>
            <span
              className="drop-remove"
              role="button"
              tabIndex={0}
              aria-label={t("upload.remove")}
              onClick={(event) => {
                event.stopPropagation();
                setFile(null);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.stopPropagation();
                  event.preventDefault();
                  setFile(null);
                }
              }}
            >
              <XIcon size={16} />
            </span>
          </>
        ) : (
          <>
            <span className="drop-icon">
              <UploadIcon size={26} />
            </span>
            <span className="drop-title">{t("upload.drop")}</span>
            <span className="drop-sub">{t("upload.dropSub")}</span>
          </>
        )}
      </button>

      <ModePicker value={mode} onChange={setMode} disabled={busy} />

      <button
        type="button"
        className="advanced-toggle"
        onClick={() => setShowAdvanced((value) => !value)}
        aria-expanded={showAdvanced}
      >
        {showAdvanced ? t("upload.advancedClose") : t("upload.advancedOpen")}
      </button>
      {showAdvanced && (
        <div className="advanced-box">
          <label className="field-label" htmlFor="gt-file">
            {t("upload.gtLabel")}
          </label>
          <input
            id="gt-file"
            className="file-input"
            type="file"
            accept={GT_ACCEPT}
            onChange={(event) => setGtFile(event.target.files?.[0] || null)}
          />
          <p className="field-hint">
            {t("upload.gtHint")}
          </p>
        </div>
      )}

      {error && (
        <div className={classNames("form-alert", quotaError && "form-alert-quota")} role="alert">
          <AlertIcon size={18} />
          <div>
            <strong>{quotaError ? t("upload.quotaTitle") : t("upload.errorTitle")}</strong>
            <p>{error}</p>
            {quotaError && (
              <p className="form-alert-extra">
                {t("upload.quotaReset", { time: resetText(me.quota) })}
              </p>
            )}
          </div>
        </div>
      )}

      {exhausted ? (
        <div className="quota-blocked">
          <div>
            <strong>{t("upload.exhaustedTitle")}</strong>
            <p>{t("upload.exhaustedText", { time: resetText(me.quota), limit: me.quota.daily_limit })}</p>
          </div>
        </div>
      ) : (
        <button type="submit" className="btn btn-primary btn-submit" disabled={!file || busy}>
          {busy ? (
            <Spinner label={t("upload.busy")} />
          ) : (
            <>
              <SparkIcon size={18} />
              {t("upload.submit")}
              <ArrowRightIcon size={17} />
            </>
          )}
        </button>
      )}

      <div className="upload-foot">
        <span>
          {t("upload.freeFoot", {
            remaining: me.quota.remaining_today ?? 0,
            limit: me.quota.daily_limit ?? 0,
          })}
        </span>
        <span>{t("upload.retention", { days: config.job_retention_days })}</span>
      </div>

      {config.omr_mock && (
        <div className="mock-note">
          <SparkIcon size={15} />
          {t("upload.mock")}
        </div>
      )}
    </form>
  );
}
