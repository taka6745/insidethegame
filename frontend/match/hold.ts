/**
 * Holds complete live states until the live picture reaches their producer time, so data
 * never runs ahead of the footage. Each state supersedes the previous one; only the newest
 * releasable state is returned.
 */
export class HeldUpdates<T> {
  queue: { item: T; seconds: number | null; at: number }[] = [];
  maxHoldMs: number;
  limit: number;
  constructor(maxHoldMs = 15000, limit = 30) {
    this.maxHoldMs = maxHoldMs;
    this.limit = limit;
  }
  get size() {
    return this.queue.length;
  }
  /** `seconds` is the producer video time; null or non-finite never waits. */
  push(item: T, seconds: number | null | undefined, now: number) {
    this.queue.push({ item, seconds: Number.isFinite(seconds) ? Number(seconds) : null, at: now });
    if (this.queue.length > this.limit) this.queue.shift();
  }
  /** `playhead` is the live video time, or null when no live picture is playing. */
  release(playhead: number | null, now: number): T | undefined {
    let released: T | undefined;
    while (this.queue.length) {
      const { item, seconds, at } = this.queue[0]!;
      const ready = playhead === null || seconds === null || seconds <= playhead
        || now - at >= this.maxHoldMs;
      if (!ready) break;
      released = item;
      this.queue.shift();
    }
    return released;
  }
  clear() {
    this.queue = [];
  }
}
