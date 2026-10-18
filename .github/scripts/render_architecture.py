"""Render the agreed service plans as self-contained SVGs (Python standard library)."""
from pathlib import Path
from html import escape
import base64

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / '.github/diagram-assets'
INK, MUTED, BLUE, PURPLE, GREEN = '#17324d', '#5d7185', '#147ac1', '#7952b3', '#168366'
PALE, LINE, GREY = '#f4f7fb', '#d8e3ed', '#82909e'

class Diagram:
    def __init__(self, path, title, subtitle, width=1320, height=750):
        self.path, self.w, self.h = path, width, height
        self.parts = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
            f'<title id="title">{escape(title)}</title><desc id="desc">{escape(subtitle)}. Planned architecture, not deployed infrastructure.</desc>',
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10" fill="#5d7185"/></marker></defs>',
            '<style>text{font-family:Arial,Helvetica,sans-serif} .title{font-size:32px;font-weight:700} .body{font-size:16px} .small{font-size:14px}</style>',
            f'<rect width="{width}" height="{height}" fill="white"/>']
        self.text('INSIDE THE GAME',36,35,13,BLUE,True)
        self.text(title,36,83,32,INK,True)
        # Keep descriptive prose in accessible SVG metadata, not on the canvas.
    def text(self,s,x,y,size=16,color=INK,bold=False,anchor='start'):
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{700 if bold else 400}" text-anchor="{anchor}">{escape(s)}</text>')
    def rect(self,x,y,w,h,fill=PALE,stroke=LINE,dash=False):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{stroke}" stroke-width="1.5"'+(' stroke-dasharray="7 5"' if dash else '')+'/>')
    def icon(self,name,x,y,size=50):
        p=ASSETS/(name+'.png')
        if p.exists():
            data=base64.b64encode(p.read_bytes()).decode()
            self.parts.append(f'<image x="{x}" y="{y}" width="{size}" height="{size}" preserveAspectRatio="xMidYMid meet" xlink:href="data:image/png;base64,{data}"/>')
        else:
            # Simple vector symbols for product concepts, not Azure service logos.
            if name=='screen':
                self.rect(x,y+5,size,size*.7,'white',BLUE)
                self.parts.append(f'<path d="M{x+size*.42},{y+size*.2} l{size*.22},{size*.16} l-{size*.22},{size*.16} Z" fill="{BLUE}"/>')
            elif name=='code':
                self.parts.append(f'<path d="M{x+17},{y+10} L{x+4},{y+25} L{x+17},{y+40} M{x+33},{y+10} L{x+46},{y+25} L{x+33},{y+40}" fill="none" stroke="{PURPLE}" stroke-width="3"/>')
            elif name=='chart':
                for i,h in enumerate([20,32,43]):
                    self.parts.append(f'<rect x="{x+i*17}" y="{y+48-h}" width="11" height="{h}" rx="2" fill="{GREEN}"/>')
            else:
                self.rect(x+5,y,40,50,'white',BLUE)
                for yy in (14,25,36):
                    self.parts.append(f'<path d="M{x+13},{y+yy} h24" stroke="{BLUE}" stroke-width="2"/>')
    def card(self,x,y,w,h,title,notes=(),icon=None,color=BLUE,dash=False):
        self.rect(x,y,w,h,'#f7f9fc' if dash else 'white',GREY if dash else LINE,dash)
        if icon:self.icon(icon,x+(w-48)/2,y+18,48)
        ty=y+(92 if icon else 34)
        self.text(title,x+w/2,ty,19,GREY if dash else color,True,'middle')
        for i,s in enumerate(notes):self.text(s,x+w/2,ty+27+i*23,15,MUTED,anchor='middle')
    def arrow(self,points,label=None,lx=None,ly=None,dash=False,both=False):
        pts=' '.join(f'{x},{y}' for x,y in points)
        self.parts.append(f'<polyline points="{pts}" fill="none" stroke="{MUTED}" stroke-width="2" stroke-linejoin="round" marker-end="url(#arrow)"'+(' marker-start="url(#arrow)"' if both else '')+(' stroke-dasharray="7 5"' if dash else '')+'/>')
        if label:
            x=lx if lx is not None else (points[0][0]+points[-1][0])/2
            y=ly if ly is not None else (points[0][1]+points[-1][1])/2-12
            tw=len(label)*7.5+18
            self.parts.append(f'<rect x="{x-tw/2}" y="{y-16}" width="{tw}" height="23" fill="white"/>')
            self.text(label,x,y,14,MUTED,anchor='middle')
    def note(self,s,y,color=MUTED):self.text(s,36,y,16,color)
    def save(self):
        self.parts.append(f'<path d="M36,{self.h-50} H{self.w-36}" stroke="{LINE}"/>')
        self.text('PLANNED · Solid: data / calls · Dashed: messages / Phase 2',36,self.h-25,12,MUTED)
        self.parts.append('</svg>')
        p=ROOT/self.path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('\n'.join(self.parts)+'\n')

# Root overview: five owners, with live and historical data paths separated.
d=Diagram('architecture.svg','Five services. One live match.','Shared match intelligence; personal questions and stat cards. No narrative workflow per viewer.',1440,760)
xs=[36,320,604,888,1172];w=232
items=[('Data generation',['Match replay'],'python',BLUE),('ETL',['Azure SQL · GraphQL'],'stream',BLUE),('Narrative engine',['12 audience buckets'],'agent',PURPLE),('User backend',['Questions · stats'],'containers',BLUE),('Frontend',['Match experience'],'screen',GREEN)]
for x,(title,notes,ic,col) in zip(xs,items):d.card(x,245,w,205,title,notes,ic,col)
for i,label in enumerate(['Event Hubs','Facts + triggers','Narratives','Live UI']):
 d.arrow([(xs[i]+w,345),(xs[i+1],345)],label,(xs[i]+w+xs[i+1])/2,320,dash=i==2)
d.arrow([(436,245),(436,175),(1004,175),(1004,245)],'Live · Event Hubs',720,168,True)
d.arrow([(436,450),(436,510),(1004,510),(1004,450)],'History · GraphQL',720,503)
d.text('Narratives: Service Bus live · GraphQL history',36,575,16,PURPLE)
d.arrow([(950,245),(950,214),(790,214),(790,245)],'Bucket presence',870,207,True)

d.note('PHASE 2 · Jev · clips · rewind',663,GREY)
d.save()

# Data input is a replay tool, not a resurrected match simulator.
d=Diagram('data-generation/architecture.svg','Data generation','Prepare a saved synthetic match and replay its events into the demo.')
d.card(60,200,300,200,'Existing match',['Events + footage'],'file')
d.card(510,200,300,200,'Replay adapter',['Timed replay'],'python')
d.card(960,200,300,200,'Azure Event Hubs',['ETL + user backend'],'events')
d.arrow([(360,300),(510,300)],'read')
d.arrow([(810,300),(960,300)],'publish')
d.rect(60,475,1200,130)
d.icon('screen',85,510,45);d.text('Footage → frontend',155,520,21,INK,True)


d.save()

# ETL implementation boundary.
d=Diagram('etl/architecture.svg','ETL','One Stream Analytics job stores raw events, key events and per-minute statistics.')
for x,title,notes,ic in [(30,'Event Hubs',['Match events'],'events'),(290,'Stream Analytics',['Filter + aggregate'],'stream'),(550,'Azure SQL',['Events + stats'],'sql'),(810,'Data API builder',['GraphQL'],'graphql')]:
 d.card(x,200,220,190,title,notes,ic)
d.card(1070,200,220,190,'Consumers',['Narrative engine','User backend'],'containers')
for x in [250,510,770,1030]:d.arrow([(x,292),(x+40,292)])
d.card(550,470,300,155,'Service Bus',['Minutes + key events'],'bus')
d.arrow([(400,390),(400,545),(550,545)],'notify',455,533,True)
d.arrow([(850,545),(1180,545),(1180,390)],'triggers',1010,533,True)

d.save()

# Narrative shared memory and per-bucket authors.
d=Diagram('narrative-engine/architecture.svg','Narrative engine','Python on Azure Container Apps · Microsoft Agent Framework · Foundry model calls',1440,850)
d.card(36,180,250,180,'Match inputs',['Facts + triggers'],'graphql')
d.card(366,180,290,180,'Shared context',['Summarise → compress'],'agent',PURPLE)
d.card(736,180,290,180,'Narrative author',['Up to 12 buckets'],'foundry',PURPLE)
d.card(1106,180,298,180,'Publish',['Narratives + stat choices'],'bus')
d.arrow([(286,270),(366,270)])
d.arrow([(656,270),(736,270)])
d.arrow([(1026,270),(1106,270)])
d.rect(366,430,660,166)
d.icon('cosmos',393,470,66)
d.text('Azure Cosmos DB',490,475,23,BLUE,True)
d.text('Context · narratives · checkpoints',490,512,17,MUTED)
d.text('History → GraphQL',490,550,15,MUTED)
d.arrow([(511,360),(511,430)],both=True)
d.arrow([(881,430),(881,360)],both=True)
d.arrow([(1255,360),(1255,512),(1026,512)],'save',1145,500)
d.rect(36,635,1368,98,'#f5f1fb','#dfd4ed')
d.text('TRIGGERS',58,665,13,PURPLE,True)
d.text('1 min → summary     ·     Key event / 10 min → narrative',58,696,17,INK)

d.save()

# User backend internals with an explicit separate executor boundary.
d=Diagram('user-backend/architecture.svg','User backend','One Python app on Azure Container Apps; generated code runs in an isolated executor.',1440,1000)
d.card(36,190,255,190,'Upstream data',['Event Hubs · GraphQL'],'graphql')
d.card(376,190,290,190,'Question + coding',['Goal → code → test'],'agent',PURPLE)
d.card(766,190,290,190,'Viewer delivery',['Chat + live updates'],'containers')
d.card(1156,190,248,190,'Frontend',[],'screen')
d.arrow([(291,280),(376,280)])
d.arrow([(666,280),(766,280)],'result',716,267)
d.arrow([(1056,280),(1156,280)],both=True)
d.card(36,470,255,190,'Narrative input',['Service Bus · GraphQL'],'bus')
d.card(376,470,290,190,'Isolated executor',['Python · read-only data'],'code',PURPLE)
d.card(766,470,290,190,'Shared stat engine',['Shared calculations'],'chart',GREEN)
d.card(1156,470,248,190,'PostgreSQL',['Accounts · Match App'],'postgres')
d.arrow([(521,380),(521,470)],'test / run',574,431,both=True)
d.arrow([(666,565),(766,565)],'values',716,551)
d.arrow([(911,470),(911,380)],'cards',948,432)
d.arrow([(1278,470),(1278,420),(1020,420),(1020,380)])
d.text('→ Viewer delivery',163,643,14,BLUE,anchor='middle')


for x,title,notes in [(36,'Jev follows',[]),(506,'Clip resolver',[]),(976,'Playback state',[])]:
 d.card(x,767,428,116,title,notes,color=GREY,dash=True)
d.note('PHASE 2 ONLY',742,GREY)
d.save()

# Product interface, not a frontend framework decision.
d=Diagram('frontend/architecture.svg','Frontend','Application data comes from the user backend. Video comes from the footage source.',1320,870)
d.card(36,190,245,180,'Demo profile',['Team + fan style'],'users')
d.arrow([(281,280),(361,280)],'select')
d.rect(361,180,680,430,'white',LINE)
d.text('MATCH VIEW',385,215,14,BLUE,True)
d.rect(385,235,360,210,'#eef5fb','#bfdaee');d.icon('screen',533,298,60)
d.text('Live footage',565,413,18,BLUE,True,'middle')
d.rect(765,235,252,210,'#f5f1fb','#dfd4ed')
d.text('Agent  |  Narratives',891,273,18,PURPLE,True,'middle')
d.text('Chat',891,319,16,MUTED,anchor='middle')
d.text('Feed + history',891,349,16,MUTED,anchor='middle')

for x,title in [(385,'Default stat'),(601,'Default stat'),(817,'Custom pin')]:
 d.rect(x,474,200,102,'#f0f6f4' if title=='Custom pin' else PALE,LINE)
 d.icon('chart',x+18,497,36);d.text(title,x+72,530,16,INK,True)
d.card(1110,190,174,180,'Backend',['API + live'],'containers')
d.arrow([(1041,280),(1110,280)],both=True)
d.text('Pin → replace a default',385,642,15,MUTED)
d.rect(36,693,1248,84,'#f7f9fc',GREY,True)
d.text('PHASE 2',58,725,13,GREY,True)
d.text('Clips · pause · rewind',58,752,17,GREY)
d.save()
print('Rendered overview + five service SVGs.')
