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
    parts = [text(28, 64, 'Business logic • the arrows describe a hypothesis, not measured uplift', 14, MUTED)]
    for x,y,w,h,c,title,sub in [
        (28,110,210,120,COLORS[0],'Fan relevance','Understand · care'),
        (315,110,245,120,COLORS[1],'Audience demand','Watch · return · explore'),
        (670,85,300,50,COLORS[2],'Media rights',''),
        (670,150,300,50,COLORS[3],'Partner reach',''),
        (670,215,300,50,COLORS[4],'PL+ subscriptions','')]:
        parts += [box(x,y,w,h,c),text(x+w/2,y+32 if h==50 else y+48,title,21,c,'middle',700)]
        if sub: parts.append(text(x+w/2,y+79,sub,15,MUTED,'middle'))
    parts += [line(238,170,305,170,arrow=True)]
    for y in [110,175,240]: parts += [line(560,170,600,170),line(600,170,600,y),line(600,y,660,y,arrow=True)]
    save('business.svg','Why the League would care','Fan relevance may increase watching and return visits, supporting media rights, partner reach and PL+ subscriptions.',292,parts)

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
