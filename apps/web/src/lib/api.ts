export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: {
      // CSRF contract with the server: mutations require this header.
      "X-Requested-With": "fetch",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
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
