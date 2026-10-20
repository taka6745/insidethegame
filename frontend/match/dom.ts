export function node<K extends keyof HTMLElementTagNameMap>(
  document: Document,
  tag: K,
  text = "",
  className = "",
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  element.textContent = text;
  element.className = className;
  return element;
}
/** Reuse unchanged children; replacing one event never rebuilds the rest of a feed. */
export function keyedList<T>(
  container: HTMLElement,
  rows: readonly T[],
  key: (row: T) => unknown,
  render: (row: T, previous: HTMLElement | undefined) => HTMLElement,
): void {
  const existing = new Map(
    [...container.children].map((child) => [
      (child as HTMLElement).dataset.key,
      child as HTMLElement,
    ]),
  );
  const wanted = new Set<string | undefined>();
  rows.forEach((row, index) => {
    const id = String(key(row));
    wanted.add(id);
    const signature = JSON.stringify(row);
    let child = existing.get(id);
    if (!child || child.dataset.signature !== signature) {
      const replacement = render(row, child);
      replacement.dataset.key = id;
      replacement.dataset.signature = signature;
      if (child && child !== replacement) child.replaceWith(replacement);
      child = replacement;
    }
    if (container.children[index] !== child)
      container.insertBefore(child, container.children[index] || null);
  });
  for (const child of [...container.children])
    if (!wanted.has((child as HTMLElement).dataset.key)) child.remove();
}
