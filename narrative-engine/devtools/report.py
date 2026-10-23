"""One match's engine output as a single HTML page, in the order it was produced: minute
summaries, compressions (with the blocks they replaced) and narrative steps for each bucket.

    python -m devtools.azure report --match-id itg-syn-0001-az2   # from Cosmos DB
"""
from collections import defaultdict
from html import escape

from narrative_engine.context.compression import EARLIER, FIVE_MINUTE, MINUTE
from doubles.targets import DEFAULT_BUCKETS

LEVELS = {MINUTE: "Minute summary", FIVE_MINUTE: "5-minute compression", EARLIER: "Period compression"}

STYLE = """
:root { --bg: #f7f7f5; --card: #fff; --text: #1d1d1b; --muted: #6b6b66; --line: #e2e2dc;
        --minute: #3b6fb6; --compress: #8a5cc2; --narrative: #2f8f5b; --tag: #efefea; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161615; --card: #20201e; --text: #ececE8; --muted: #9a9a94; --line: #34342f;
          --minute: #6b9be0; --compress: #b48ae6; --narrative: #5cc08a; --tag: #2b2b28; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 15px/1.5 system-ui, sans-serif; }
header { position: sticky; top: 0; background: var(--bg); border-bottom: 1px solid var(--line); padding: 12px 16px; z-index: 1; }
h1 { font-size: 18px; margin: 0 0 4px; }
.stats { color: var(--muted); font-size: 13px; }
.controls { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 8px; font-size: 14px; align-items: center; }
main { max-width: 860px; margin: 0 auto; padding: 16px; }
.card { background: var(--card); border: 1px solid var(--line); border-left: 4px solid; border-radius: 6px;
        padding: 10px 14px; margin: 0 0 10px; }
.card.minute { border-left-color: var(--minute); }
.card.compress { border-left-color: var(--compress); }
.card.narrative { border-left-color: var(--narrative); }
.head { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: baseline; margin-bottom: 4px; }
.time { font-weight: 600; font-variant-numeric: tabular-nums; }
.kind { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }
.meta { font-size: 12px; color: var(--muted); margin-top: 4px; }
.tag { background: var(--tag); border-radius: 4px; padding: 0 6px; font-size: 12px; }
.superseded { opacity: .6; }
.bucket { border-top: 1px solid var(--line); padding: 6px 0; }
.bucket:first-of-type { border-top: 0; }
.bucket b { font-size: 13px; }
.reason { color: var(--muted); font-size: 13px; }
.hide-minute .card.minute, .hide-compress .card.compress, .hide-narrative .card.narrative { display: none; }
"""

SCRIPT = """
const main = document.querySelector('main');
for (const box of document.querySelectorAll('input[data-kind]'))
  box.addEventListener('change', () => main.classList.toggle('hide-' + box.dataset.kind, !box.checked));
const pick = document.getElementById('bucket');
function showBucket() {
  for (const el of document.querySelectorAll('.bucket'))
    el.hidden = pick.value !== 'all' && el.dataset.bucket !== pick.value;
}
pick.addEventListener('change', showBucket); showBucket();
"""


def _meta(model, prompt, tokens, extra=""):
    total = (tokens or {}).get("total_tokens")
    bits = [b for b in (model, prompt, f"{total} tokens" if total else None, extra) if b]
    return f'<div class="meta">{escape(" · ".join(bits))}</div>'


def render(match_id, blocks, narratives):
    """blocks: every ContextBlock, superseded ones included; narratives: every bucket's Narrative."""
    by_id = {b.id: b for b in blocks}
    replaced = defaultdict(list)
    for b in blocks:
        if b.supersededBy:
            replaced[b.supersededBy].append(b)
    steps = defaultdict(list)
    for n in narratives:
        steps[n.stepId].append(n)

    items = [(b.createdAt, 0, b) for b in blocks]
    items += [(min(n.createdAt for n in group), 1, group) for group in steps.values()]
    cards = []
    for _, kind, item in sorted(items, key=lambda x: (x[0], x[1])):
        if kind == 0:
            b = item
            span = b.coversFrom.label if b.coversFrom == b.coversTo else f"{b.coversFrom.label} – {b.coversTo.label}"
            css = "minute" if b.level == MINUTE else "compress"
            later = by_id.get(b.supersededBy)
            extra = f"later compressed into {later.coversFrom.label} – {later.coversTo.label}" if later else ""
            inputs = replaced.get(b.id, [])
            note = f'<span class="tag">replaced {len(inputs)} blocks</span>' if inputs else ""
            cards.append(f'<div class="card {css}{" superseded" if later else ""}"><div class="head">'
                         f'<span class="time">{escape(span)}</span><span class="kind">{LEVELS[b.level]}</span>{note}</div>'
                         f'<div>{escape(b.summary)}</div>{_meta(b.model, b.promptVersion, b.tokens, extra)}</div>')
        else:
            group = sorted(item, key=bucket_order)
            first = group[0]
            buckets = "".join(
                f'<div class="bucket" data-bucket="{n.userType}"><b>{escape(n.userType)}</b> '
                f'<span class="tag">#{n.seq}</span><div>{escape(n.text)}</div>'
                f'{_meta(n.model, n.promptVersion, n.tokens)}</div>' for n in group)
            cards.append(f'<div class="card narrative"><div class="head"><span class="time">{escape(first.matchTime.label)}</span>'
                         f'<span class="kind">Narrative · {escape(first.trigger.type)}</span>'
                         f'<span class="tag">{len(group)} buckets</span></div>'
                         f'<div class="reason">{escape(first.trigger.reason)}</div>{buckets}</div>')

    minutes = sum(1 for b in blocks if b.level == MINUTE)
    tokens = sum((x.tokens or {}).get("total_tokens", 0) for x in [*blocks, *narratives])
    present = sorted({n.userType for n in narratives}, key=bucket_order_id)
    options = '<option value="all">all buckets</option>' + "".join(
        f'<option{" selected" if t == "neutral:casual" else ""}>{t}</option>' for t in present)
    checks = "".join(f'<label><input type="checkbox" data-kind="{k}" checked> {label}</label>'
                     for k, label in (("minute", "minute summaries"), ("compress", "compressions"),
                                      ("narrative", "narratives")))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Engine report {escape(match_id)}</title>
<style>{STYLE}</style></head><body><header><h1>{escape(match_id)} <span class="kind">synthetic match</span></h1>
<div class="stats">{minutes} minute summaries · {len(blocks) - minutes} compressions · {len(steps)} narrative steps ·
{len(narratives)} narratives · {tokens:,} tokens</div>
<div class="controls">{checks}<label>bucket <select id="bucket">{options}</select></label></div></header>
<main>{''.join(cards)}</main><script>{SCRIPT}</script></body></html>"""


def bucket_order_id(bucket_id):
    return (DEFAULT_BUCKETS.index(bucket_id), "") if bucket_id in DEFAULT_BUCKETS else (len(DEFAULT_BUCKETS), bucket_id)


def bucket_order(narrative):
    return bucket_order_id(narrative.userType)
