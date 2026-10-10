import { z } from "zod";

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const errorEnvelope = z.object({
  error: z.object({ code: z.string(), message: z.string(), details: z.unknown().optional() }),
});

function readCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

async function ensureCsrf(): Promise<string> {
  let token = readCookie("el_csrf");
  if (!token) {
    const r = await fetch("/api/v1/auth/csrf", { credentials: "include" });
    const body = (await r.json()) as { csrf_token: string };
    token = readCookie("el_csrf") ?? body.csrf_token;
  }
  return token;
}

export type Query = Record<string, string | number | boolean | string[] | null | undefined>;

export function toSearch(params?: Query): string {
  if (!params) return "";
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, x));
    else sp.append(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export async function api<T>(
  path: string,
  opts: { method?: string; body?: unknown; query?: Query; schema?: z.ZodType<T>; form?: FormData } = {},
): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-CSRF-Token"] = await ensureCsrf();
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}${toSearch(opts.query)}`, { method, headers, body, credentials: "include" });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the server. Check your connection and try again.");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let json: unknown = undefined;
  try {
    json = text ? JSON.parse(text) : undefined;
  } catch {
    throw new ApiError(res.status, "invalid_response", `Unexpected response from server (HTTP ${res.status})`);
  }
  if (!res.ok) {
    const parsed = errorEnvelope.safeParse(json);
    if (parsed.success) {
      const e = parsed.data.error;
      throw new ApiError(res.status, e.code, e.message, e.details);
    }
    throw new ApiError(res.status, "http_error", `Request failed (HTTP ${res.status})`);
  }
  if (opts.schema) {
    const parsed = opts.schema.safeParse(json);
    if (!parsed.success) {
      console.error("Response validation failed", path, parsed.error.issues.slice(0, 5));
      throw new ApiError(res.status, "invalid_response", "The server returned data in an unexpected shape.");
    }
    return parsed.data;
  }
  return json as T;
}
