"""Render the local development guide using the existing engineering icons."""
import base64
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1100 430" role="img" aria-labelledby="title desc">',
         '<title id="title">Local development</title>',
         '<desc id="desc">Docker runs databases, messaging emulators and GraphQL for integration checks without accounts. Terraform is validated with a mock provider. Stream Analytics and real models need separate Azure integration.</desc>',
         '<rect width="1100" height="430" rx="16" fill="#f6f8fc"/>',
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
box(550, 240, "GraphQL", ["graphql"], "Queries against SQL")
box(810, 260, "Terraform", ["containers"], "Validate + mock tests")
parts.append('<rect x="30" y="300" width="1040" height="97" rx="12" fill="#eef0f4" stroke="#aeb9c6" stroke-dasharray="6 5"/>')
text("SEPARATE AZURE CHECK", 50, 326, 12, "#5d7185", 700)
text("Stream Analytics · Luke", 50, 363, 20, weight=700)
text("Real models · Identity · Networking · Scale", 420, 363, 20)
parts.append('</svg>')
(ROOT / "local/development.svg").write_text('\n'.join(parts) + '\n')
