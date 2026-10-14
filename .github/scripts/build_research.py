#!/usr/bin/env python3
"""Render concise research diagrams; dated technology comes from technology.json."""
from datetime import date
from html import escape
import json
from math import pi
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'research'
INK, MUTED, BG = '#edf5fa', '#a4bbc9', '#101e2b'
COLORS = ['#73e3ae', '#69baff', '#c2a4ff', '#f3c678', '#fa9dac']


def text(x, y, label, size=18, color=INK, anchor='start', weight=400):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" text-anchor="{anchor}" font-weight="{weight}">{escape(label)}</text>'


def line(x1, y1, x2, y2, color=MUTED, arrow=False):
    marker = ' marker-end="url(#arrow)"' if arrow else ''
    return f'<path d="M{x1} {y1} L{x2} {y2}" stroke="{color}" stroke-width="2" fill="none"{marker}/>'


def box(x, y, w, h, color):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{color}" fill-opacity=".1" stroke="{color}" stroke-opacity=".6"/>'


def save(name, title, desc, height, parts):
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{height}" viewBox="0 0 1000 {height}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title><desc id="desc">{escape(desc)}</desc>
<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10" fill="{MUTED}"/></marker></defs>
<rect width="1000" height="{height}" rx="14" fill="{BG}"/>
<g font-family="Arial, Helvetica, sans-serif">{text(28, 38, title, 24, weight=700)}{''.join(parts)}</g></svg>'''
    (OUT / name).write_text(svg + '\n')


def main():
    parts = [text(28, 66, 'Official asks → viewing improvements → audience demand', 15, MUTED)]
    parts += [text(28, 103, 'MICROSOFT ASKS FOR', 12, MUTED, weight=700),
              text(365, 103, 'WHY THAT MATTERS TO A FAN', 12, MUTED, weight=700)]
    rows = [
        ('Explain pressure & rhythm', 'Understand the turning point'),
        ('Player / club focus', 'See the story I care about'),
        ('Casual / analyst modes', 'Follow at my level'),
        ('Multilingual stories', 'Follow in my language'),
        ('Live overlays & recaps', 'Catch up; stay with the match'),
    ]
    for i, (ask, benefit) in enumerate(rows):
        y = 118 + i * 65
        c = COLORS[i]
        parts += [box(28, y, 285, 47, c), text(43, y+29, ask, 18, c, weight=700),
                  line(314, y+24, 350, y+24, arrow=True),
                  text(365, y+29, benefit, 17), line(630, y+24, 687, y+24)]
    parts += [line(687,142,687,402), line(687,272,722,272,arrow=True),
              box(734,184,238,178,COLORS[0]),
              text(853,219,'Audience demand',22,COLORS[0],'middle',700),
              text(853,252,'Keep watching',18,anchor='middle'),
              text(853,284,'Come back',18,anchor='middle'),
              text(853,316,'Follow more matches',18,anchor='middle'),
              text(28,464,'Benefits and viewing gains are hypotheses to test. Sources and evidence: research/cases.md.',13,MUTED)]
    save('business.svg','What they want — and why it matters',
         'Five explicit asks in Microsoft rules section 4.1 connect to fan benefits. '
         'All paths end at audience demand: continued viewing, return visits and interest in more matches. '
         'These are testable benefits, not established gains.',486,parts)

    parts=[]
    nodes=[(28,85,'Competition','Fixtures · rules',COLORS[0]),(680,85,'Commercial','Rights · partners',COLORS[1]),(28,220,'Development','Academies · community',COLORS[3]),(680,220,'Media & fans','Studios · products',COLORS[2])]
    for x,y,title,sub,c in nodes:
        parts += [line(500,190,x+292 if x<500 else x,y+46),box(x,y,292,95,c),text(x+146,y+38,title,22,c,'middle',700),text(x+146,y+65,sub,16,MUTED,'middle')]
    parts += [f'<circle cx="500" cy="190" r="84" fill="{BG}" stroke="{INK}"/>',text(500,185,'Premier',23,anchor='middle',weight=700),text(500,215,'League',23,anchor='middle',weight=700)]
    save('premier-league.svg','What the League looks after','The League coordinates competition, commercial rights, development and central media and fan products.',340,parts)

    parts=[]
    for i,(verb,product,c) in enumerate([('Follow','myPL · alerts',COLORS[0]),('Play','FPL · quizzes',COLORS[1]),('Watch','PL+ · video',COLORS[2]),('Listen','PL Radio',COLORS[3]),('Explore','Companion',COLORS[4])]):
        x=28+i*194
        parts += [box(x,82,168,123,c),f'<circle cx="{x+84}" cy="110" r="5" fill="{c}"/>',text(x+84,149,verb,23,c,'middle',700),text(x+84,181,product,15,MUTED,'middle')]
    parts += [text(28,238,'PL+ launched in Singapore • Radio excludes UK / Ireland • sources and availability below',14,MUTED)]
    save('fans.svg','Five ways fans already participate','Follow with myPL, play fantasy, watch PL+ or video, listen to Radio, and explore using Companion. Availability varies.',265,parts)

    # Sources and populations: research/cases.md; percentages are not comparable samples.
    parts=[text(28,65,'Different surveys and populations • stated experience / preference',14,MUTED)]
    for i,(value,title,sub,source,c) in enumerate([
        (72,'VAR reduces enjoyment','Regular PL viewers','YouGov · May 2026',COLORS[4]),
        (32,'Want tailored highlights','US sports fans','Deloitte · 2026 report',COLORS[1]),
        (22,'Would stream more¹','US entertainment fans','Deloitte · 2026 report',COLORS[0])]):
        x=170+i*330; circumference=2*pi*62
        parts += [f'<circle cx="{x}" cy="162" r="62" fill="none" stroke="#263d4c" stroke-width="13"/>',f'<circle cx="{x}" cy="162" r="62" fill="none" stroke="{c}" stroke-width="13" stroke-dasharray="{circumference*value/100} {circumference}" transform="rotate(-90 {x} 162)"/>',text(x,173,f'{value}%',34,c,'middle',700),text(x,265,title,20,anchor='middle',weight=700),text(x,292,sub,16,MUTED,'middle'),text(x,317,source,14,MUTED,'middle')]
    parts += [text(28,357,'¹ With more personalised AI recommendations. Intention is not an observed increase in viewing.',14,MUTED)]
    save('demand.svg','Where fans report friction or demand','72% of regular PL viewers say VAR reduces enjoyment. Separately, 32% of US sports fans want personalised highlights; 22% of US entertainment fans say personalised AI recommendations would increase streaming use.',382,parts)

    parts=[]
    for i,(title,c) in enumerate(zip(['Ingest','Interpret','Explain','Render','Personalise'],COLORS)):
        x=28+i*194
        parts += [box(x,83,166,68,c),text(x+83,125,title,21,c,'middle',700)]
        if i<4: parts.append(line(x+167,117,x+190,117,arrow=True))
    parts += [text(28,191,'Synthetic events',15,MUTED),text(416,191,'Why it matters',15,MUTED),text(804,191,'For this fan',15,MUTED)]
    save('challenge.svg','Microsoft’s five-stage brief','Synthetic events flow through ingestion, interpretation, explanation, rendering and personalisation. Source: official rules section 4.1.',218,parts)

    parts=[text(28,66,'One fictional match • shared IDs, units and clock',14,MUTED)]
    parts += [box(28,115,230,115,COLORS[0]),text(143,160,'Synthetic match',23,COLORS[0],'middle',700),text(143,192,'State + events',17,MUTED,'middle')]
    for y,label,c in [(100,'Statistics + evidence',COLORS[1]),(195,'Positions → replay',COLORS[2])]:
        parts += [line(258,172,325,y+32,arrow=True),box(340,y,300,64,c),text(490,y+40,label,20,c,'middle',700)]
    parts += [line(640,132,700,172,arrow=True),line(640,227,700,172,arrow=True),box(715,115,257,115,COLORS[3]),text(843,158,'Fan experience',22,COLORS[3],'middle',700),text(843,190,'Overlay · story · recap',16,MUTED,'middle'),text(28,299,'Tracking supports movement claims • expected answers stay separate from live inputs',14,MUTED)]
    save('match-data.svg','Facts first, then the experience','A coherent synthetic match provides events and state. Metrics and evidence support stories; time-aligned tracking drives a visual replay. The fan experience combines them.',324,parts)

    # The example scores remain on their design scale, separate from repo evidence.
    parts=[text(28,66,'Four fan jobs · independently challenged design scores /100 · examples only',14,MUTED)]
    for i,(name,job,score) in enumerate([
        ('Together','Watch with a newcomer',76),
        ('Race','Follow your club across matches',72),
        ('Suspense','Catch up without spoilers',68),
        ('Read','Learn to read the play',64),
    ]):
        y=110+i*62; c=COLORS[i]
        parts += [text(28,y,name,19,c,weight=700),text(28,y+22,job,14,MUTED),
                  f'<rect x="345" y="{y-17}" width="550" height="27" rx="4" fill="#263d4c"/>',
                  f'<rect x="345" y="{y-17}" width="{score*5.5}" height="27" rx="4" fill="{c}"/>',
                  text(355+score*5.5,y+3,str(score),17,weight=700)]
    x=345+90*5.5
    parts += [f'<path d="M{x} 80 V318" stroke="{INK}" stroke-dasharray="5 5"/>',
              text(x,340,'90 ambition',13,MUTED,'middle'),
              text(28,370,'Scores compare designs, not built products. Fan demand and impact still need testing.',14,MUTED)]
    save('ideas.svg','Different ways to make the match matter',
         'Together 76, Race 72, Suspense 68, Read 64. Independently challenged example designs; none reached the 90-point ambition.',394,parts)

    render=json.loads((ROOT/'data/GoogleResearchFootball/render-benchmark.json').read_text())
    parts=[text(28,66,'One AI-vs-AI run · synchronized video and telemetry · measured '+render['measured_date'],14,MUTED)]
    stats=[(str(round(render['in_play_physics_seconds']/60))+' min','Actual play'),
           (str(render['width'])+' × '+str(render['height']),'Video at '+str(render['fps'])+' fps'),
           (f"{render['data_summary']['player_rows']/1_000_000:.2f}M",'Player rows')]
    for i,(value,label) in enumerate(stats):
        x=28+i*322; c=COLORS[i]
        parts += [box(x,91,300,106,c),text(x+150,137,value,30,c,'middle',700),text(x+150,170,label,16,MUTED,'middle')]
    for i,(label,c) in enumerate([('Save match state',COLORS[0]),('Change an action',COLORS[1]),('Compare the replay',COLORS[2])]):
        x=28+i*322
        parts += [box(x,233,275,52,c),text(x+137,266,label,19,c,'middle',700)]
        if i<2: parts.append(line(x+279,259,x+313,259,arrow=True))
    score='–'.join(map(str,render['score']))
    parts += [text(28,321,'Separate checkpoint test passed. Full-match score '+score+': capture verified; football realism needs work.',14,MUTED)]
    save('simulator.svg','Synthetic football we can inspect and replay',
         'The measured full run has 90 minutes of actual play, 4K video at 25 fps and 12.71 million player rows. A separate checkpoint test reproduced an original rollout and changed its trajectory after intervention.',347,parts)

    parts=[text(28,66,'Working rules for assistants in this codebase',14,MUTED)]
    for i,(title,sub,c) in enumerate([
        ('Inspect','Preserve local work',COLORS[0]),('Build','Small, reusable code',COLORS[1]),
        ('Verify','Test actual output',COLORS[2]),('Report','Evidence + limits',COLORS[3]),
    ]):
        x=28+i*242
        parts += [box(x,94,213,91,c),text(x+106,132,title,23,c,'middle',700),text(x+106,162,sub,15,MUTED,'middle')]
        if i<3: parts.append(line(x+215,139,x+237,139,arrow=True))
    parts += [text(28,222,'Credentials stay local · data keeps provenance · example ideas do not choose the product',14,MUTED)]
    save('working.svg','How we work in this repo',
         'Inspect and preserve local work, build small reusable code, verify actual output, report evidence and limits. Keep secrets local and preserve data provenance. Examples do not select a product.',248,parts)

    data=json.loads((OUT/'technology.json').read_text())['items']
    start=date(2026,7,1); end=date(2026,10,31)
    def tx(d): return 300+(date.fromisoformat(d)-start).days/(end-start).days*610
    parts=[text(28,66,'Dated announcements, releases, new repos and papers • details and links below',14,MUTED)]
    for d,label in [('2026-07-01','JUL'),('2026-08-01','AUG'),('2026-09-01','SEP'),('2026-10-01','OCT')]:
        x=tx(d); parts += [line(x,99,x,605,'#263d4c'),text(x,92,label,13,MUTED)]
    for i,item in enumerate(sorted(data,key=lambda v:(v['kind'],v['date']))):
        y=126+i*36; c={'Product':COLORS[1],'Code':COLORS[0],'Paper':COLORS[2]}[item['kind']]
        parts += [text(28,y+5,item['title'],16),line(295,y,tx(item['date']),y,'#263d4c'),f'<circle cx="{tx(item["date"])}" cy="{y}" r="6" fill="{c}"/>']
    for i,(label,c) in enumerate([('Code',COLORS[0]),('Product',COLORS[1]),('Paper',COLORS[2])]):
        parts += [f'<circle cx="{560+i*135}" cy="37" r="5" fill="{c}"/>',text(574+i*135,42,label,14,MUTED)]
    save('technology.svg','Recent technology • July–October 2026','Timeline of 13 items. Dates have different meanings: announcement, SDK release, repository creation, first paper submission or revision. See the linked table for each date basis.',620,parts)


if __name__=='__main__':
    main()
