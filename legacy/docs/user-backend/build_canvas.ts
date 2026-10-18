// Builds user-backend.excalidraw from canvas.json and the engineering icon library.
// Run: bun run docs/user-backend/build_canvas.ts
import { join } from "node:path";

type El = Record<string, any>;
type Box = { x: number; y: number; w: number; h: number };
const here = import.meta.dir;
const plan = await Bun.file(join(here, "canvas.json")).json();
const library = await Bun.file(join(here, "../icon-libraries/engineering.excalidrawlib")).json();

const INK = "#1e1e1e", MUTED = "#495057", GREY = "#868e96", GREY_FILL = "#f1f3f5", ARROW = "#343a40";
const NAME = 16, NOTE = 14, LABEL = 14, GAP = 6;
// Helvetica/Arial advance widths per 1000 em, so centred text lines up when Excalidraw renders it.
const ADV: Record<string, number> = { " ": 278, ",": 278, ".": 278, "/": 278, ":": 278, "-": 333, "(": 333, ")": 333, "+": 584, "&": 667, "·": 278, "→": 1000, "≤": 549 };
"abcdeghnopqu0123456789".split("").forEach((c) => (ADV[c] = 556));
"fijlt".split("").forEach((c) => (ADV[c] = c === "f" || c === "t" ? 278 : 222));
Object.assign(ADV, { c: 500, k: 500, s: 500, v: 500, x: 500, y: 500, z: 500, m: 833, r: 333, w: 722, I: 278, J: 500, L: 556, F: 611, T: 611, Z: 611, M: 833, W: 944 });
"ABEKPSVXY".split("").forEach((c) => (ADV[c] = 667));
"CDHNRU".split("").forEach((c) => (ADV[c] = 722));
"GOQ".split("").forEach((c) => (ADV[c] = 778));
const lineW = (l: string, size: number) => [...l].reduce((w, c) => w + (ADV[c] ?? 556), 0) * size / 1000;
const textW = (s: string, size: number) => Math.max(...s.split("\n").map((l) => lineW(l, size)));

let seed = 1;
const out: El[] = [];
const byId = new Map<string, El>();
const push = (e: El) => (out.push(e), byId.set(e.id, e), e);

function base(id: string, type: string, b: Box, extra: El = {}): El {
  return {
    id, type, x: b.x, y: b.y, width: b.w, height: b.h, angle: 0, strokeColor: INK, backgroundColor: "transparent",
    fillStyle: "solid", strokeWidth: 1, strokeStyle: "solid", roughness: 0, opacity: 100, groupIds: [], frameId: null,
    roundness: null, seed: seed++, version: 1, versionNonce: seed++, isDeleted: false, boundElements: [], updated: 1,
    link: null, locked: false, ...extra,
  };
}
function text(id: string, s: string, cx: number, y: number, size: number, extra: El = {}): El {
  const w = textW(s, size), lines = s.split("\n").length;
  return base(id, "text", { x: cx - w / 2, y, w, h: lines * size * 1.25 }, {
    text: s, originalText: s, fontSize: size, fontFamily: 2, textAlign: "center", verticalAlign: "top",
    containerId: null, autoResize: true, lineHeight: 1.25, ...extra,
  });
}
const leftText = (id: string, s: string, x: number, y: number, size: number, extra: El = {}) =>
  text(id, s, x + textW(s, size) / 2, y, size, { textAlign: "left", ...extra });

// ---------- icons: library glyph with its caption dropped, scaled into a size×size box centred on (cx, cy) ----------
const items = new Map<string, El>(library.libraryItems.map((i: El) => [i.name, i]));
function bbox(e: El): Box {
  if (!e.points) return { x: e.x, y: e.y, w: e.width, h: e.height };
  const xs = e.points.map((p: number[]) => p[0]), ys = e.points.map((p: number[]) => p[1]);
  return { x: e.x + Math.min(...xs), y: e.y + Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
}
function union(bs: Box[]): Box {
  const x = Math.min(...bs.map((b) => b.x)), y = Math.min(...bs.map((b) => b.y));
  return { x, y, w: Math.max(...bs.map((b) => b.x + b.w)) - x, h: Math.max(...bs.map((b) => b.y + b.h)) - y };
}
function icon(id: string, name: string, cx: number, cy: number, size: number): El[] {
  const item = items.get(name);
  if (!item) throw new Error(`icon not in library: ${name}`);
  const glyph = item.elements.filter((e: El) => e.type !== "text");
  const gb = union(glyph.map(bbox)), s = size / Math.max(gb.w, gb.h);
  const ox = cx - (gb.w * s) / 2 - gb.x * s, oy = cy - (gb.h * s) / 2 - gb.y * s;
  return glyph.map((e: El, i: number) => ({
    ...e, id: `${id}~${i}`, x: ox + e.x * s, y: oy + e.y * s, width: e.width * s, height: e.height * s,
    points: e.points?.map((p: number[]) => [p[0] * s, p[1] * s]), roughness: 0, opacity: 100, groupIds: [],
    boundElements: [], containerId: null, frameId: null, seed: seed++, versionNonce: seed++, updated: 1, locked: false,
  }));
}
function greyOut(e: El) {
  if (e.strokeColor !== "transparent") e.strokeColor = GREY;
  if (e.backgroundColor !== "transparent") e.backgroundColor = e.type === "text" ? "transparent" : GREY_FILL;
}

// ---------- title ----------
push(leftText("title", plan.title, 60, -40, 36));
push(leftText("subtitle", plan.subtitle, 60, 10, 16, { strokeColor: MUTED }));

// ---------- zones: rounded box, title (+ optional logo), optional inline notes ----------
const boxes = new Map<string, Box>();
for (const z of plan.zones) {
  const els: El[] = [base(z.id, "rectangle", z, {
    backgroundColor: z.fill, strokeColor: z.stroke, strokeWidth: z.small ? 1 : 2, roundness: { type: 3, value: 16 },
  })];
  const size = z.small ? 28 : 40, tx = z.x + 20 + (z.icon ? size + 12 : 0), ty = z.y + 18;
  if (z.icon && !z.notes) els.push(...icon(`${z.id}-logo`, z.icon, z.x + 20 + size / 2, ty + size / 2, size));
  els.push(leftText(`${z.id}-title`, z.title, z.icon && !z.notes ? tx : z.x + 20, ty + (z.small ? 4 : 0), z.small ? 16 : 22, { strokeColor: z.stroke }));
  if (z.sub) els.push(leftText(`${z.id}-sub`, z.sub, z.icon && !z.notes ? tx : z.x + 20, ty + 30, NOTE, { strokeColor: MUTED }));
  if (z.notes) {
    // Engine-style zone: big logo on the left, notes beside it.
    const lx = z.x + 40, ly = z.y + 80;
    els.push(...icon(`${z.id}-logo`, z.icon, lx + 36, ly + 36, 72));
    z.notes.forEach((n: string, i: number) => els.push(leftText(`${z.id}-n${i}`, n, lx + 100, ly + 4 + i * 22, NOTE, { strokeColor: MUTED })));
  }
  for (const e of els) { e.groupIds = [z.id]; push(e); }
  boxes.set(z.id, z);
}

// ---------- nodes: invisible (Phase 2: dashed grey) binding box, logo, name, short notes ----------
const centre = new Map<string, [number, number]>();
for (const n of plan.nodes) {
  const size = n.size ?? 72, p2 = !!n.phase2;
  const els: El[] = n.icon2
    ? [...icon(`${n.id}-a`, n.icon, n.x - size * 0.45, n.y, size * 0.85), ...icon(`${n.id}-b`, n.icon2, n.x + size * 0.45, n.y, size * 0.85)]
    : icon(`${n.id}-a`, n.icon, n.x, n.y, size);
  let y = n.y + size / 2 + 10;
  els.push(text(`${n.id}-name`, n.name, n.x, y, NAME, { strokeColor: INK }));
  y += NAME * 1.25 + 4;
  n.notes.forEach((s: string, i: number) => els.push(text(`${n.id}-n${i}`, s, n.x, y + i * NOTE * 1.3, NOTE, { strokeColor: MUTED })));
  y += n.notes.length * NOTE * 1.3;
  const w = Math.max(size * (n.icon2 ? 1.8 : 1), textW(n.name, NAME), ...n.notes.map((s: string) => textW(s, NOTE))) + 28;
  const b = { x: n.x - w / 2, y: n.y - size / 2 - 12, w, h: y - (n.y - size / 2 - 12) + 10 };
  const hit = base(n.id, "rectangle", b, {
    strokeColor: p2 ? GREY : "transparent", strokeStyle: p2 ? "dashed" : "solid", roundness: { type: 3, value: 12 },
    backgroundColor: p2 ? "#ffffff" : "transparent",
  });
  for (const e of [hit, ...els]) {
    e.groupIds = [n.id];
    if (p2 && e !== hit) greyOut(e);
    push(e);
  }
  boxes.set(n.id, b);
  centre.set(n.id, [n.x, n.y]);
}

// ---------- arrows: straight (or via waypoints), bound at both ends, native bound label ----------
function anchor(id: string, side: string, dx = 0, dy = 0, fx?: number): [number, number] {
  const b = boxes.get(id)!, [cx, cy] = centre.get(id) ?? [b.x + b.w / 2, b.y + b.h / 2];
  const x = fx ?? cx;
  if (side === "t") return [x + dx, b.y - GAP];
  if (side === "b") return [x + dx, b.y + b.h + GAP];
  if (side === "l") return [b.x - GAP, cy + dy];
  return [b.x + b.w + GAP, cy + dy];
}
plan.arrows.forEach((a: El, i: number) => {
  const id = `arrow-${a.from}-${a.to}`;
  const p2 = !!a.phase2, color = p2 ? GREY : ARROW;
  const s = anchor(a.from, a.fs, a.fdx, a.fdy, a.fx);
  let t = anchor(a.to, a.ts, a.tdx, a.tdy);
  const via: [number, number][] = a.via ?? [];
  if (a.ts === "l" || a.ts === "r") t = [t[0], via.length ? via[via.length - 1][1] : t[1]];
  const abs = [s, ...via, t];
  const xs = abs.map((p) => p[0]), ys = abs.map((p) => p[1]);
  const arrow = push(base(id, "arrow", { x: s[0], y: s[1], w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) }, {
    points: abs.map(([x, y]) => [x - s[0], y - s[1]]), strokeColor: color, strokeWidth: 2, strokeStyle: p2 ? "dashed" : "solid",
    roundness: null, startBinding: { elementId: a.from, focus: 0, gap: GAP }, endBinding: { elementId: a.to, focus: 0, gap: GAP },
    startArrowhead: a.both ? "arrow" : null, endArrowhead: "arrow", lastCommittedPoint: null, elbowed: false,
  }));
  for (const end of [a.from, a.to]) byId.get(end)!.boundElements.push({ id, type: "arrow" });
  if (a.label) {
    // Excalidraw centres a bound label on the middle point (odd count) or the middle segment (even count).
    const k = abs.length;
    const [mx, my] = k % 2 ? abs[(k - 1) / 2] : [(abs[k / 2 - 1][0] + abs[k / 2][0]) / 2, (abs[k / 2 - 1][1] + abs[k / 2][1]) / 2];
    const t = text(`${id}-label`, a.label, mx, my - (LABEL * 1.25) / 2, LABEL, { strokeColor: color, containerId: id, verticalAlign: "middle" });
    arrow.boundElements.push({ id: t.id, type: "text" });
    push(t);
  }
});

// ---------- legend, well clear of the diagram ----------
{
  const { x, y } = plan.legend;
  const row = (i: number, label: string, style: string, color: string) => {
    const ly = y + 50 + i * 34;
    push(base(`legend-line${i}`, "arrow", { x, y: ly, w: 70, h: 0 }, {
      points: [[0, 0], [70, 0]], strokeColor: color, strokeWidth: 2, strokeStyle: style, startBinding: null, endBinding: null,
      startArrowhead: null, endArrowhead: "arrow", lastCommittedPoint: null, elbowed: false, groupIds: ["legend"],
    }));
    push(leftText(`legend-t${i}`, label, x + 90, ly - 9, NOTE, { strokeColor: MUTED, groupIds: ["legend"] }));
  };
  push(leftText("legend-title", "Legend", x, y, 18, { groupIds: ["legend"] }));
  row(0, "Phase 1 (hackathon) flow", "solid", ARROW);
  row(1, "Phase 2: Jev subscriptions, replay, playback-aware behaviour", "dashed", GREY);
}

const scene = { type: "excalidraw", version: 2, source: "docs/user-backend/build_canvas.ts", elements: out, appState: { viewBackgroundColor: "#ffffff", gridSize: 20 }, files: {} };
await Bun.write(join(here, "user-backend.excalidraw"), JSON.stringify(scene));
const arrows = out.filter((e) => e.type === "arrow" && e.startBinding);
console.log(`${out.length} elements, ${arrows.length} bound arrows`);
