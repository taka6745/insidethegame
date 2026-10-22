/**
 * Holds complete live states until the live picture reaches their producer time, so data
 * never runs ahead of the footage. Each state supersedes the previous one; only the newest
 * releasable state is returned. No state waits longer than `maxHoldMs`: overflow drops the
 * oldest states but keeps their arrival time, so a full queue still releases on time.
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
    if (this.queue.length > this.limit) {
      const dropped = this.queue.shift()!;
      this.queue[0]!.at = Math.min(this.queue[0]!.at, dropped.at);
    }
  }
  /** `playhead` is the live video time, or null when no live picture is playing. */
  release(playhead: number | null, now: number): T | undefined {
    let last = -1;
    this.queue.forEach(({ seconds, at }, index) => {
      if (playhead === null || seconds === null || seconds <= playhead || now - at >= this.maxHoldMs)
        last = index;
    });
    if (last < 0) return undefined;
    return this.queue.splice(0, last + 1)[last]!.item;
  }
  clear() {
    this.queue = [];
  }
}
