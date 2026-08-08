export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
  }
}

interface RequestOpts {
  keepalive?: boolean;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts?: RequestOpts,
): Promise<T> {
  const isForm = body instanceof FormData;
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    keepalive: opts?.keepalive,
    headers: {
      // CSRF contract with the server: mutations require this header.
      "X-Requested-With": "fetch",
      ...(body !== undefined && !isForm
        ? { "Content-Type": "application/json" }
        : {}),
    },
    body: isForm ? body : body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let message = res.statusText;
    let detail: unknown;
    try {
      const data = await res.json();
      detail = data.detail;
      if (typeof data.detail === "string") message = data.detail;
      else if (data.detail?.message) message = data.detail.message;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  postForm: <T>(path: string, form: FormData) => request<T>("POST", path, form),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body?: unknown, opts?: RequestOpts) =>
    request<T>("PUT", path, body, opts),
  delete: <T>(path: string) => request<T>("DELETE", path),
};

export interface UserOut {
  id: number;
  email: string;
}

export interface HealthOut {
  status: string;
  database: string;
  ai_node: { online: boolean; last_seen_at: string | null };
}

export interface JobOut {
  id: number;
  job_type: string;
  queue: "cpu" | "gpu";
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress_pct: number | null;
  progress_note: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface CourseOut {
  id: number;
  code: string;
  name: string;
  description: string | null;
  instructor: string | null;
  term: string | null;
  accent_color: string | null;
  position: number;
  module_count: number;
}

export interface ModuleOut {
  id: number;
  course_id: number;
  title: string;
  position: number;
  content_version: number;
  document_count: number;
  has_note: boolean;
}

export interface ModuleDetail extends ModuleOut {
  course_code: string;
  course_name: string;
  course_accent_color: string | null;
}

export type ExtractStatus = "pending" | "processing" | "ready" | "failed";

export interface DocumentOut {
  id: number;
  module_id: number;
  kind: "pdf" | "pptx";
  filename: string;
  byte_size: number;
  extract_status: ExtractStatus;
  error: string | null;
  page_count: number | null;
  job_id: number | null;
  progress_pct: number | null;
  progress_note: string | null;
}

export interface PageOut {
  page_no: number;
  title: string | null;
  speaker_notes: string | null;
  has_render: boolean;
  width: number | null;
  height: number | null;
}

export interface DocumentDetail extends DocumentOut {
  pages: PageOut[];
}

export interface NoteOut {
  pm_json: Record<string, unknown>;
  updated_at: string | null;
}

export interface DeleteConsequences {
  requires_confirmation: boolean;
  modules?: number;
  documents: number;
  notes: number;
}
