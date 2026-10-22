/** This browser's anonymous viewer id: separate browsers are separate viewers, tabs of one browser share it.
 * It reopens this browser's conversation, so it is an unguessable random UUID (the backend accepts nothing else).
 * Kept in localStorage; when storage is blocked the id lives for this page only (a fresh viewer each load). */
const KEY = "itg-viewer";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

/** A random (version 4) UUID; `crypto.randomUUID` exists only on secure origins, `getRandomValues` everywhere. */
export function randomUuid(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function viewerId(storage: Pick<Storage, "getItem" | "setItem"> | null, uuid: () => string = randomUuid): string {
  try {
    const saved = storage?.getItem(KEY);
    if (saved && UUID.test(saved)) return saved;
  } catch {
    // Storage blocked: fall through to a page-only id.
  }
  const id = uuid();
  try {
    storage?.setItem(KEY, id);
  } catch {
    // Page-only id.
  }
  return id;
}

/** localStorage when the browser allows it. */
export function browserStorage(): Storage | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}
