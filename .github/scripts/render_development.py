"""Render the local development guide using the existing engineering icons."""
import base64
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1100 560" role="img" aria-labelledby="title desc">',
         '<title id="title">Local development</title>',
         '<desc id="desc">Docker runs databases, messaging emulators and GraphQL for integration checks without accounts. Terraform is validated with a mock provider. A Python stand-in replaces Stream Analytics locally; the real job, Foundry models, identity, networking and scale need separate Azure integration. The demo operator records seeds locally and restores them through the demo-only adapter (DEMO_SEEDS=1).</desc>',
         '<rect width="1100" height="560" rx="16" fill="#f6f8fc"/>',
         '<style>text{font-family:Arial,Helvetica,sans-serif;fill:#17324d}</style>']


def text(value, x, y, size=17, color="#17324d", weight=400):
    parts.append(f'<text x="{x}" y="{y}" font-size="{size}" style="fill:{color}" font-weight="{weight}">{escape(value)}</text>')


def box(x, width, label, icons, subtitle):
    parts.append(f'<rect x="{x}" y="100" width="{width}" height="170" rx="12" fill="white" stroke="#d8e3ed"/>')
    text(label, x + 18, 130, 19, weight=700)
    for i, icon in enumerate(icons):
        data = base64.b64encode((ROOT / ".github/diagram-assets" / f"{icon}.png").read_bytes()).decode()
        parts.append(f'<image href="data:image/png;base64,{data}" x="{x+18+i*65}" y="150" width="48" height="48"/>')
    text(subtitle, x + 18, 242, 15, "#5d7185")


text("DEVELOP LOCALLY", 30, 34, 12, "#147ac1", 700)
text("Docker. No cloud account.", 30, 72, 30, weight=700)
box(30, 240, "Databases", ["postgres", "cosmos", "sql"], "Real reads + writes")
box(290, 240, "Messaging", ["events", "bus"], "Emulator round trips")
box(550, 240, "GraphQL", ["graphql"], "DAB over SQL")
box(810, 260, "Terraform", ["containers"], "Validate + mock tests")
parts.append('<rect x="30" y="295" width="1040" height="105" rx="12" fill="#fffaf0" stroke="#e7b65c"/>')
text("DEMO (backend profile) · DEMO_SEEDS=1", 50, 322, 12, "#9a6500", 700)
text("demo-control: Start demo · Cancel · status · record / capture seeds", 50, 355, 19, weight=700)
text(".local/seeds/ → restore ETL, engine, backend → feed releases held runs", 50, 383, 16, "#5d7185")
parts.append('<rect x="30" y="420" width="1040" height="110" rx="12" fill="#eef0f4" stroke="#aeb9c6" stroke-dasharray="6 5"/>')
text("AZURE · ./dev azure up · deployed 23 Oct", 50, 447, 12, "#5d7185", 700)
text("Stream Analytics job · Foundry gpt-6.1-sol + Microsoft-Decision-1", 50, 482, 19, weight=700)
text("Spend guard · edge proxy (msft-hackathon.koda-software.com) · identity, networking, scale", 50, 510, 16, "#5d7185")
parts.append('</svg>')
(ROOT / "local/development.svg").write_text('\n'.join(parts) + '\n')
