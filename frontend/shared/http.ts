export type ServiceError = Error & { code?: unknown; status?: number };
interface ErrorBody { detail?: unknown; message?: unknown; error?: unknown; code?: unknown }

/** JSON body of a developer-facing response (lab, /dev/); a failure throws the backend's own message. */
export async function parseResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  let data: unknown;
  try { data = text ? JSON.parse(text) : {}; }
  catch { throw new Error(`The backend returned an unreadable response (${response.status}).`); }
  if (!response.ok) {
    const body = data as ErrorBody;
    const detail = body.detail || body.message || body.error;
    const message = Array.isArray(detail) ? detail.map((issue: { msg?: unknown }) => issue.msg || "Invalid input").join("; ") : detail;
    const error: ServiceError = new Error(typeof message === "string" ? message : `Request failed (${response.status}).`);
    error.code = body.code;
    error.status = response.status;
    throw error;
  }
  return data as T;
}
