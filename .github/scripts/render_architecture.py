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
items=[('Data generation',['Match replay'],'python',BLUE),('ETL',['Stats + history · GraphQL'],'stream',BLUE),('Narrative engine',['12 audience buckets'],'agent',PURPLE),('User backend',['Questions · stats'],'containers',BLUE),('Frontend',['Match experience'],'screen',GREEN)]
for x,(title,notes,ic,col) in zip(xs,items):d.card(x,245,w,205,title,notes,ic,col)
for i,label in enumerate(['Event Hubs','Facts + triggers','Narratives','Live UI']):
 d.arrow([(xs[i]+w,345),(xs[i+1],345)],label,(xs[i]+w+xs[i+1])/2,320,dash=i==2)
d.arrow([(436,245),(436,175),(1004,175),(1004,245)],'Live · Event Hubs',720,168,True)
d.arrow([(436,450),(436,510),(1004,510),(1004,450)],'Stats + history · GraphQL',720,503)
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

# ETL owns standard statistics and history; consumers see only its API.
d=Diagram('etl/architecture.svg','ETL owns match facts','Standard stats in Cosmos DB; historical events in Azure SQL; consumers query ETL GraphQL.',1440,850)
d.card(30,320,220,180,'Event Hubs',['Match events'],'events')
d.card(310,320,240,180,'Stream Analytics',['Compute + store'],'stream')
d.card(620,180,240,180,'Cosmos DB',['Standard stats'],'cosmos')
d.card(620,520,240,180,'Azure SQL',['Event history'],'sql')
d.card(940,320,220,180,'ETL GraphQL',['Stats + event queries'],'graphql')
d.card(1210,320,200,180,'Consumers',['Agents + cards'],'containers')
d.arrow([(250,410),(310,410)])
d.arrow([(550,375),(585,375),(585,270),(620,270)])
d.arrow([(550,445),(585,445),(585,610),(620,610)])
d.arrow([(860,270),(900,270),(900,375),(940,375)])
d.arrow([(860,610),(900,610),(900,445),(940,445)])
d.arrow([(1160,410),(1210,410)])
d.icon('bus',330,610,45)
d.text('Service Bus',400,635,20,BLUE,True)
d.arrow([(430,500),(430,590)],'Triggers',475,555,dash=True)
d.note('Backend selects and delivers standard stats. ETL calculates them.',755)
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

# Detailed backend boundary follows the reference board. Standard and custom stats stay separate.
d=Diagram('user-backend/architecture.svg','Main user backend','ETL owns standard stats in Cosmos DB and historical events in SQL. GraphQL is the only database access path for the backend.',1680,1420)
# Service boundaries.
d.rect(24,145,270,900,'#fff4e5','#f4a34f')
d.text('ETL service',44,179,22,'#b86500',True)
d.rect(330,145,1050,990,'#e8f4ff',BLUE)
d.icon('containers',350,164,32)
d.text('User backend · Container Apps',395,188,22,BLUE,True)
d.rect(1420,335,236,690,'#effaf1','#69ad7d')
d.text('Frontend',1440,370,22,GREEN,True)
# Upstream stores are accessed only through ETL GraphQL.
d.card(44,210,230,145,'Cosmos DB',['Standard stats'],'cosmos')
d.card(44,410,230,145,'ETL GraphQL',[],'graphql')
d.card(44,620,230,145,'Azure SQL',['Event history'],'sql')
d.card(44,850,230,145,'Event Hubs',['Custom live events'],'events')
d.arrow([(159,355),(159,410)])
d.arrow([(159,620),(159,555)])
# Main API, identity and agent components.
d.rect(600,385,275,395,'#f7f1ff','#cbb9e9')
d.text('Microsoft Agent Framework',737,402,12,PURPLE,True,'middle')
d.card(355,410,205,145,'GraphQL helper',['Read-only queries'],'graphql')
d.card(615,410,245,145,'Question agent',['Existing stats first'],'agent',PURPLE)
d.card(925,410,230,145,'Chat + actions',[],'containers')
d.card(640,230,195,145,'Foundry models',[],'foundry',PURPLE)
d.card(925,230,200,145,'Profiles + sessions',[],'users')
d.card(1150,230,210,145,'PostgreSQL',['Accounts · Match App'],'postgres')
d.card(1430,410,216,145,'Agent chat',[],'screen',GREEN)
d.arrow([(355,480),(274,480)],'Query',314,465,both=True)
d.arrow([(615,480),(560,480)])
d.arrow([(925,480),(860,480)])
d.arrow([(820,410),(820,375)])
d.arrow([(1040,410),(1040,375)])
d.arrow([(1125,300),(1150,300)],both=True)
d.arrow([(1155,480),(1430,480)],'Questions + replies',1290,466,both=True)
# User-defined calculations are a separate lane from standard stats.
d.card(355,620,205,145,'Isolated executor',['Separate container'],'python',PURPLE)
d.card(615,620,245,145,'Coding + tests',['Custom requests only'],'agent',PURPLE)
d.card(355,850,205,145,'Custom calculations',['Shared per match'],'code',PURPLE)
d.arrow([(737,555),(737,620)],'Goal',775,594)
d.arrow([(615,690),(560,690)],both=True)
d.arrow([(457,620),(457,555)],'Data',490,594)
d.arrow([(457,850),(457,765)],'Run',490,814)
d.arrow([(274,925),(355,925)])
d.arrow([(737,765),(737,810),(530,850)],'Validated function',660,838)
# Standard values bypass the executor and custom calculation engine.
d.card(925,850,230,145,'Cards + pins',['Select · rank · replace'],'chart',GREEN)
d.card(1185,850,175,145,'Live delivery',['One per viewer'],'bus')
d.card(1430,850,216,145,'Match view',['Stats + narratives'],'chart',GREEN)
d.arrow([(560,535),(585,535),(585,795),(1040,795),(1040,850)],'ETL stat values',850,788)
d.arrow([(1040,555),(1040,850)],'Pin / unpin',1084,655)
d.arrow([(560,925),(925,925)],'Custom values',740,912)
d.arrow([(1155,925),(1185,925)])
d.arrow([(1360,925),(1430,925)])
# Shared narratives stay outside the user backend.
d.rect(615,1170,745,140,'#f5f0ff','#b6a0df')
d.icon('agent',640,1210,55)
d.text('Narrative engine',720,1213,23,PURPLE,True)
d.text('Bucket narratives · ranked stat IDs',720,1250,17,MUTED)
d.text('Service Bus live · GraphQL history',720,1280,15,MUTED)
d.arrow([(1040,1170),(1040,995)],'Stat IDs',1075,1150)
d.arrow([(1270,1170),(1270,995)],'Narratives',1310,1150)
# Future features, visually secondary.
for x,title in [(355,'Playback state'),(555,'Clip resolver'),(755,'Jev follows')]:
 d.card(x,1040,175,70,title,(),color=GREY,dash=True)
d.text('PHASE 2',1185,1080,14,GREY,True)
d.note('Standard stats: fetch → select → deliver. Custom requests: query history → test → run.',1350)
d.save()

# Proposed custom-rule ownership and execution lifecycle, separate from standard ETL stats.
d=Diagram('user-backend/docs/custom-calculations.svg','Where custom rules live and run','Proposed design: Match App stores rules, results and subscriptions. Registration activates a worker; history seeds the result and live events update it.',1680,1040)
d.rect(300,150,1080,770,'#e8f4ff',BLUE)
d.icon('containers',320,170,34)
d.text('USER BACKEND SYSTEM',370,195,20,BLUE,True)
d.card(330,255,235,150,'Agent + validation',['Define or reuse rule'],'agent',PURPLE)
d.rect(620,215,735,220,'#f5f8fc','#b4cce0')
d.text('Match App · PostgreSQL',640,242,19,BLUE,True)
d.card(640,260,215,150,'Rules',['ID · rule · version'],'postgres')
d.card(880,260,215,150,'Results',['Value · cursor · version'],'postgres')
d.card(1120,260,215,150,'Subscriptions',['Viewer → calculation ID'],'postgres')
d.arrow([(565,330),(640,330)],'Save',600,316)
d.card(625,590,280,175,'Calculation worker',['Filter → update value','Many rules per worker'],'code',PURPLE)
d.card(1110,590,225,175,'Live delivery',['Existing connection'],'bus')
d.arrow([(447,405),(447,510),(595,510),(595,635),(625,635)],'Activate rule ID',520,497)
d.arrow([(747,590),(747,435)],'Load rule',793,510)
d.arrow([(905,620),(987,620),(987,435)],'Save result',1030,510)
d.arrow([(1227,435),(1227,590)],'Find viewers',1270,510)
d.arrow([(905,715),(1110,715)],'Value changed',1008,700)
# External data providers. The backend owns the custom logic, not the source events.
d.rect(24,360,240,465,'#fff4e5','#f4a34f')
d.text('ETL / match feed',44,392,21,'#b86500',True)
d.card(44,420,200,145,'ETL GraphQL',['Historical events'],'graphql')
d.card(44,640,200,145,'Event Hubs',['Shared live consumer'],'events')
d.arrow([(244,490),(282,490),(282,575),(625,575),(625,610)],'Initial history',430,563)
d.arrow([(244,715),(625,715)],'Relevant live events',430,700)
d.card(1430,590,225,175,'Frontend',['Pinned value: 7'],'screen',GREEN)
d.arrow([(1335,680),(1430,680)])
d.rect(330,805,1020,85,'white','#c8dceb')
d.text('Mbappé header → 6 becomes 7 → save → notify subscribers',355,840,21,INK,True)
d.text('Other players’ events leave this counter unchanged.',355,870,16,MUTED)
d.note('History scan: first activation / rebuild. Live update: each relevant event. No LLM in the update loop.',965)
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
print('Rendered overview, five service SVGs and custom-calculation detail.')
