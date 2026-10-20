export type Mode = "compare" | "audiveris" | "homr";
export type JobStatus = "queued" | "running" | "done" | "error";

export interface AppConfig {
  app_name: string;
  app_env: "production" | "development" | "test";
  max_upload_mb: number;
  omr_mock: boolean;
  engines: string[];
  samples: number;
  server_time: string;
}

export interface Sample {
  id: string;
  name: string;
  category: string;
  category_label: string;
  blurb: string;
  gt_notes: number | null;
  image_url: string;
}

export interface Candidate {
  engine: string;
  variant: string;
  status: string;
  seconds: number;
  notes: number;
  measures: number;
  valid_ratio: number;
  coverage: number;
  quality: number;
  f1: number | null;
  mock: boolean;
}

export interface AudioInfo {
  seconds?: number;
  notes?: number;
  bpm?: number;
  sample_rate?: number;
  error?: string;
}

export interface JobReport {
  image: string;
  mode: Mode;
  style: Record<string, number | boolean>;
  candidates: Candidate[];
  chosen: string | null;
  selection: "heuristic" | "oracle";
  confidence: number;
  needs_review: boolean;
  mock: boolean;
  audio: AudioInfo;
  notes: number;
  duration_s: number;
}

export interface JobSummary {
  id: string;
  status: JobStatus;
  mode: Mode;
  label: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  chosen: string | null;
  confidence: number | null;
  needs_review: boolean;
  error: string | null;
  files_ready: boolean;
}

export interface JobDetail extends JobSummary {
  report: JobReport | null;
  files: string[];
}

export interface JobListResponse {
  jobs: JobSummary[];
}

export interface CreateJobResponse {
  job: JobSummary;
}

export interface HealthResponse {
  ok: boolean;
  version: string;
  db: string;
  queue: { queued: number; running: number };
  worker: {
    online: boolean;
    last_seen: string | null;
    engines: Record<string, boolean> | null;
    mock: boolean | null;
  };
  server_time: string;
}

export type DownloadFile =
  | "best.musicxml"
  | "best.mid"
  | "best.wav"
  | "notes.csv"
  | "piano_roll.png"
  | "report.json";
