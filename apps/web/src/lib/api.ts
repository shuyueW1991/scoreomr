import type {
  AppConfig,
  CreateJobResponse,
  HealthResponse,
  JobDetail,
  JobListResponse,
  Mode,
  Sample,
} from "./types";

interface ErrorBody {
  error?: {
    code?: string;
    message?: string;
    [key: string]: unknown;
  };
}

export class ApiError extends Error {
  status: number;
  code: string;
  extra: Record<string, unknown>;

  constructor(status: number, code: string, message: string, extra: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.extra = extra;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      credentials: "same-origin",
      ...init,
      headers: {
        Accept: "application/json",
        ...(init.headers || {}),
      },
    });
  } catch {
    throw new ApiError(0, "network_error", "无法连接服务器，请检查网络或稍后重试。");
  }

  const contentType = response.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const body = isJson ? await response.json().catch(() => null) : await response.text();
  if (!response.ok) {
    const parsed = (isJson ? body : null) as ErrorBody | string | null;
    const detail = typeof parsed === "object" && parsed ? parsed.error : null;
    throw new ApiError(
      response.status,
      detail?.code || "http_error",
      detail?.message || (typeof parsed === "string" ? parsed.slice(0, 300) : "请求失败"),
      detail || {},
    );
  }
  return body as T;
}

export const api = {
  config: () => request<AppConfig>("/config"),
  health: () => request<HealthResponse>("/health"),
  samples: () => request<{ samples: Sample[] }>("/samples"),

  createJob: (form: FormData) =>
    request<CreateJobResponse>("/jobs", { method: "POST", body: form }),

  runSample: (sampleId: string, mode: Mode) =>
    request<CreateJobResponse>(`/samples/${encodeURIComponent(sampleId)}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    }),

  jobs: () => request<JobListResponse>("/jobs"),
  job: (jobId: string) => request<JobDetail>(`/jobs/${encodeURIComponent(jobId)}`),

};

export function jobFileUrl(jobId: string, name: string): string {
  return `/api/jobs/${encodeURIComponent(jobId)}/files/${encodeURIComponent(name)}`;
}

export function sampleImageUrl(sample: Sample): string {
  return sample.image_url;
}
