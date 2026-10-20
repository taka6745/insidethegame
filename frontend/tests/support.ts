/** Test doubles implement only the surface a test exercises; this names the boundary cast. */
export function stub<T>(value: unknown): T {
  return value as T;
}
export function deferred<T = unknown>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
export interface FetchCall {
  method?: string;
  body?: unknown;
  headers: Record<string, string>;
}
/** Replace global fetch with a typed double for one test. */
export function setFetch(fn: (url: string, options: FetchCall) => Promise<Response>) {
  globalThis.fetch = stub<typeof fetch>(fn);
}
