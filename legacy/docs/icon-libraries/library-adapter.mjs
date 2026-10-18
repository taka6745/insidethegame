// Built-in icons are served from disk, avoiding localStorage's small quota.
// User additions and removals remain private to each browser.
const CUSTOM_KEY = 'excalidraw-canvas-library';
const REMOVED_KEY = 'engineering-library-removed';
let basePromise;
const baseItems = () => basePromise ??= fetch('/engineering.excalidrawlib')
  .then(response => {
    if (!response.ok) throw new Error(`Icon library HTTP ${response.status}`);
    return response.json();
  }).then(data => data.libraryItems).catch(error => {
    basePromise = undefined;
    throw error;
  });

export const libraryAdapter = {
  async load() {
    const custom = JSON.parse(localStorage.getItem(CUSTOM_KEY) || '[]');
    const removed = new Set(JSON.parse(localStorage.getItem(REMOVED_KEY) || '[]'));
    const base = await baseItems();
    const overrides = new Set(custom.map(item => item.id));
    return { libraryItems: [...custom, ...base.filter(item =>
      !removed.has(item.id) && !overrides.has(item.id))] };
  },
  async save({ libraryItems }) {
    const base = await baseItems();
    const originals = new Map(base.map(item => [item.id, item]));
    const present = new Set(libraryItems.map(item => item.id));
    // Excalidraw normalizes element fields on load. Do not mistake those changes
    // for user additions and copy the 10 MB built-in pack into localStorage.
    // Editing a library symbol on the canvas and re-adding it creates a new ID.
    const custom = libraryItems.filter(item => !originals.has(item.id));
    localStorage.setItem(CUSTOM_KEY, JSON.stringify(custom));
    localStorage.setItem(REMOVED_KEY, JSON.stringify(base.filter(item =>
      !present.has(item.id)).map(item => item.id)));
  }
};
