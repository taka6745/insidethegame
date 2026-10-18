export function node(document, tag, text = "", className = "") {
  const element = document.createElement(tag);
  element.textContent = text;
  element.className = className;
  return element;
}
/** Reuse unchanged children; replacing one event never rebuilds the rest of a feed. */
export function keyedList(container, rows, key, render) {
  const existing = new Map(
    [...container.children].map((child) => [child.dataset.key, child]),
  );
  const wanted = new Set();
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
    if (!wanted.has(child.dataset.key)) child.remove();
}
