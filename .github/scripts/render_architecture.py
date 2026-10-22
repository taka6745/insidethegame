"""Render the agreed service plans as self-contained SVGs (Python standard library)."""
from pathlib import Path
from html import escape
import base64

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / '.github/diagram-assets'
INK, MUTED, BLUE, PURPLE, GREEN = '#17324d', '#5d7185', '#147ac1', '#7952b3', '#168366'
PALE, LINE, GREY = '#f4f7fb', '#d8e3ed', '#82909e'

class Diagram:
    def __init__(self, path, title, subtitle, width=1320, height=750, legend='PLANNED · Solid: data / calls · Dashed: messages / Phase 2'):
        self.path, self.w, self.h, self.legend = path, width, height, legend
        kind = 'Planned design, not deployed infrastructure' if legend.startswith('PLANNED') else 'What exists now, with its status'
        self.parts = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
            f'<title id="title">{escape(title)}</title><desc id="desc">{escape(subtitle)}. {kind}.</desc>',
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
    def card(self,x,y,w,h,title,notes=(),icon=None,color=BLUE,dash=False,status=None):
        self.rect(x,y,w,h,'#f7f9fc' if dash else 'white',GREY if dash else LINE,dash)
        if icon:self.icon(icon,x+(w-48)/2,y+18,48)
        ty=y+(92 if icon else 34)
        self.text(title,x+w/2,ty,19,GREY if dash else color,True,'middle')
        for i,s in enumerate(notes):self.text(s,x+w/2,ty+27+i*23,15,MUTED,anchor='middle')
        # Status badge: green = deployed to Azure dev, blue = tested locally only.
        if status:self.text(status,x+w/2,y+h-14,12,GREEN if status.startswith('Deployed') else BLUE,True,'middle')
    def arrow(self,points,label=None,lx=None,ly=None,dash=False,both=False):
        pts=' '.join(f'{x},{y}' for x,y in points)
        self.parts.append(f'<polyline points="{pts}" fill="none" stroke="{MUTED}" stroke-width="2" stroke-linejoin="round" marker-end="url(#arrow)"'+(' marker-start="url(#arrow)"' if both else '')+(' stroke-dasharray="7 5"' if dash else '')+'/>')
        if label:
            x=lx if lx is not None else (points[0][0]+points[-1][0])/2
            y=ly if ly is not None else (points[0][1]+points[-1][1])/2-12
            tw=len(label)*7.5+18
            self.parts.append(f'<rect x="{x-tw/2}" y="{y-16}" width="{tw}" height="23" fill="white"/>')
            self.text(label,x,y,14,MUTED,anchor='middle')
    def tag(self,s,cx,cy):
        # Small amber chip: the demo-only seed adapter on this service (DEMO_SEEDS=1).
        tw=len(s)*6.6+20
        self.parts.append(f'<rect x="{cx-tw/2}" y="{cy-11}" width="{tw}" height="22" rx="11" fill="#fff1d6" stroke="#e7b65c"/>')
        self.text(s,cx,cy+4,12,'#9a6500',True,'middle')
    def note(self,s,y,color=MUTED):self.text(s,36,y,16,color)
    def save(self):
        self.parts.append(f'<path d="M36,{self.h-50} H{self.w-36}" stroke="{LINE}"/>')
        self.text(self.legend,36,self.h-25,12,MUTED)
        self.parts.append('</svg>')
        p=ROOT/self.path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('\n'.join(self.parts)+'\n')

# Root overview: what runs now. Green: applied on Azure 22 Oct for the Azure test (acceptance pending);
# blue: tested in the local Docker stack only. The amber tag marks the demo-only seed adapter (DEMO_SEEDS).
NOW='NOW · Solid: data / calls · Dashed: messages · Green: applied on Azure 22 Oct (acceptance pending) · Blue: tested locally · Amber tag: DEMO_SEEDS adapter (judge build only)'
AZ='Deployed 22 Oct · tested locally'
d=Diagram('architecture.svg','Five services. Three live matches.','A simulated provider streams events and HLS; one ETL pipeline computes the facts; one shared narrative pass per audience; a personal companion per viewer; a demo operator starts, seeds and cancels the three-match demo',1680,1190,NOW)
d.card(36,150,230,180,'Match feed',['Simulated provider','Events + played HLS'],'python',status=AZ)
d.tag('held / resumed runs',151,138)
d.card(316,150,210,180,'Event Hubs',['match-events','key = matchId'],'events',status=AZ)
d.rect(566,112,558,240,'#fff8ee','#f4a34f')
d.text('ETL · one pipeline (etl/)',1110,138,15,'#b86500',True,'end')
d.card(580,152,170,180,'Stream Analytics',['Stats rules'],'stream',status='Deployed · local stand-in')
d.card(760,152,170,180,'Azure SQL',['History · stats'],'sql',status=AZ.split(' ·')[0])
d.card(940,152,170,180,'Data API builder',['GraphQL'],'graphql',status=AZ.split(' ·')[0])
d.tag('seed export / restore',845,352)
d.card(1170,150,210,180,'Service Bus',['notifications','narratives · clips'],'bus',status=AZ)
d.card(1420,150,224,180,'Narrative engine',['gpt-6.1-sol · Decision-1','Agent Framework · Cosmos'],'foundry',PURPLE,status=AZ)
d.tag('seed export / restore',1532,138)
d.card(36,560,200,190,'Edge proxy',['Cloudflare Worker','msft-hackathon.','koda-software.com','→ Azure frontend'],None,INK,status='Deployed 22 Oct')
d.card(296,560,284,190,'Frontend',['Start demo · viewer · follow view','Clips: sting · slow motion'],'screen',GREEN,status=AZ)
d.card(640,560,440,190,'User backend',['Questions · replays · follows · cross-game','gpt-6.1-sol questions · follow offers'],'containers',status=AZ)
d.tag('seed export / restore',860,548)
d.arrow([(266,240),(316,240)])
d.arrow([(526,240),(580,240)])
d.arrow([(750,240),(760,240)])
d.arrow([(930,240),(940,240)])
d.arrow([(665,152),(665,92),(1275,92),(1275,150)],'match-notifications',970,86,dash=True)
d.arrow([(1380,240),(1420,240)],dash=True)
d.arrow([(151,330),(151,450),(400,450),(400,560)],'Played HLS',276,438)
d.arrow([(421,330),(421,500),(740,500),(740,560)],'Live events, direct',580,488)
d.arrow([(990,352),(990,560)],'Stats · GraphQL',990,455)
d.arrow([(1060,352),(1060,410),(1470,410),(1470,330)],'Facts · GraphQL',1265,398)
d.arrow([(1080,610),(1530,610),(1530,330)],'Audience + follow targets',1300,598)
d.arrow([(1600,330),(1600,700),(1080,700)],'Narratives · clips · Service Bus',1330,688,dash=True)
d.arrow([(236,655),(296,655)])
d.arrow([(580,655),(640,655)],both=True)
d.text('REST + WS',610,640,13,MUTED,anchor='middle')
# Demo operator: start, cancel, readiness; restores seeds through each owner's demo-only adapter.
d.rect(36,820,1608,230,'#fffaf0','#e7b65c')
d.text('DEMO BUILD (judge URL) · Start demo always runs three matches; main game Arsenal–Liverpool opens first',1622,850,15,'#9a6500',True,'end')
d.card(296,875,284,160,'Demo control',['/demo-api/ start · cancel · status','one replica · scales to zero'],None,INK,status='Deployed 22 Oct')
d.arrow([(438,750),(438,875)],'/demo-api/',438,792)
d.card(36,875,200,160,'Seeds',['20′ · HT · 60′ · 85′','Azure Files · .local'],None,INK,status='Recorded locally')
d.arrow([(296,955),(236,955)],both=True)
d.card(640,875,440,160,'Restore, then continue live',['Feed holds runs · ETL, engine, backend restore','the snapshot · runs released, main game first'],None,INK,status='Built 22 Oct · unit + local stack')
d.arrow([(580,955),(640,955)])
d.card(1140,875,504,160,'Clips and cross-game',['Decision-1 picks clip moments · preview cards','Follow or ask about another live match'],None,PURPLE,status='Built 22 Oct · unit + local stack')
d.text('Every run is its own matchId and is purged per match. Nothing reaches a viewer before the feed has streamed it; a seed holds nothing past its start point.',36,1090,16,INK,True)
d.text('Locally: Microsoft emulators, SQL Server + DAB, a Python stand-in for Stream Analytics and a local model. Azure: ./dev azure up (Foundry gpt-6.1-sol + Microsoft-Decision-1, spend guard).',36,1118,15,MUTED)
d.save()

# The feed simulates an external data and broadcast provider, and owns the demo runs (start points, held runs).
d=Diagram('data-generation/architecture.svg','Data generation and feed','Tactically scripted GRF recordings; the feed replays three runs at once as an external provider would, and holds or resumes runs for demo seeds.',1320,900,NOW)
d.card(60,150,300,180,'Recordings + HLS',['Rendered GRF matches','Synthetic, labelled'],'file',status='Checked in · media ignored')
d.card(510,150,300,180,'Feed',['One run per matchId','Rebased to wall time'],'python',status=AZ)
d.tag('held / resumed runs',660,138)
d.card(960,150,300,180,'Azure Event Hubs',['MA1 · MA3 · POS · v2'],'events',status=AZ)
d.arrow([(360,240),(510,240)],'read')
d.arrow([(810,240),(960,240)],'publish')
d.card(60,420,300,170,'Tactical scripts',['Press · block · flank','Directness · fatigue'],None,INK,status='Per fixture · re-rendered 22 Oct')
d.arrow([(210,420),(210,330)],'render',245,380)
d.card(510,420,300,170,'Demo settings',['Fixtures · stagger · cap 3','Start points · main game'],None,INK,status='Feed Postgres · 002, 005')
d.arrow([(660,330),(660,420)],both=True)
d.card(960,420,300,170,'Demo control',['/demo/start · release','Cancel → purge'],None,INK,status='Deployed 22 Oct')
d.arrow([(960,505),(810,505)],'start · release',885,493)
d.rect(60,650,1200,120)
d.icon('screen',85,680,45);d.text('Played HLS segments → nginx /media/hls/{matchId}/ → viewer',155,690,21,INK,True)
d.text('Our services see only Event Hubs and HLS over HTTP. A held run sends nothing at or past its point, HLS included.',155,725,16,MUTED)
d.save()

# One ETL pipeline: Stream Analytics into Azure SQL, served by Data API builder.
d=Diagram('etl/architecture.svg','ETL owns match facts','Stream Analytics writes events, key events and stats to Azure SQL; Data API builder serves GraphQL; Service Bus carries notifications.',1440,850,NOW)
d.card(30,200,220,180,'Event Hubs',['Match events'],'events',status=AZ)
d.card(310,200,240,180,'Stream Analytics',['Rules per match'],'stream',status='Deployed · local etl-stream')
d.card(620,200,260,180,'Azure SQL',['History · stats · trends'],'sql',status=AZ)
d.tag('seed export / restore',750,188)
d.card(950,200,220,180,'Data API builder',['GraphQL'],'graphql',status=AZ)
d.card(1220,200,190,180,'Consumers',['Engine · backend'],'containers')
d.arrow([(250,290),(310,290)])
d.arrow([(550,290),(620,290)])
d.arrow([(880,290),(950,290)])
d.arrow([(1170,290),(1220,290)])
d.card(30,480,220,180,'Stream schedule',['Starts on events','Stops 30 min idle'],None,INK,status='Spend guard · deployed')
d.arrow([(250,570),(280,570),(280,350),(310,350)],'start / stop',280,450)
d.card(310,480,240,180,'Service Bus',['match-notifications'],'bus',status=AZ)
d.arrow([(470,380),(470,480)],'Triggers',510,435,dash=True)
d.card(620,480,260,180,'SPADL post-processor',['MA3 → SPADL actions','Container App · Python'],'python',status=AZ)
d.arrow([(705,380),(705,480)],'MA3 rows',705,435)
d.arrow([(795,480),(795,380)],'Final actions',800,452)
d.card(950,480,220,180,'Demo seeds',['export · restore','DEMO_SEEDS only'],None,'#9a6500',status='Unit + local stack')
d.arrow([(950,600),(915,600),(915,350),(880,350)],both=True)
d.card(1220,480,190,180,'Demo control',['Restores seeds','ETL first'],None,INK,status='Deployed 22 Oct')
d.arrow([(1220,570),(1170,570)])
d.note('The backend selects and delivers standard stats; ETL calculates them, on SPADL actions.',720)
d.note('Tested locally (SQL Server + DAB containers, etl-stream with the same rules); applied on Azure 22 Oct for the Azure test.',748)
d.note('A restored seed fed only what follows writes the same rows as one uninterrupted run.',772)
d.save()

# Narrative shared memory, per-bucket authors, Decision-1 checks and clip messages.
d=Diagram('narrative-engine/architecture.svg','Narrative engine','Python on Azure Container Apps · Microsoft Agent Framework · Foundry gpt-6.1-sol and Microsoft-Decision-1',1440,1000,NOW)
d.card(36,180,250,192,'Match inputs',['Facts + triggers'],'graphql',status=AZ)
d.card(366,180,290,192,'Shared context',['Summarise → compress'],'agent',PURPLE,status='gpt-6.1-sol (writer)')
d.card(736,180,290,192,'Analyst + author',['Storylines · enabled buckets'],'foundry',PURPLE,status='gpt-6.1-sol (writer)')
d.card(1106,180,298,192,'Publish',['Narratives · stat picks','MomentClip · FollowClip'],'bus',status=AZ)
d.arrow([(286,270),(366,270)])
d.arrow([(656,270),(736,270)])
d.arrow([(1026,270),(1106,270)])
d.rect(366,430,660,166)
d.icon('cosmos',393,470,66)
d.text('Azure Cosmos DB',490,475,23,BLUE,True)
d.text('Context · narratives · storylines · follows',490,512,17,MUTED)
d.text('History → GraphQL',490,550,15,MUTED)
d.arrow([(511,372),(511,430)],both=True)
d.arrow([(881,430),(881,372)],both=True)
d.arrow([(1255,372),(1255,512),(1026,512)],'save',1145,500)
d.card(36,640,290,160,'Demo seeds',['ASGI layer · export · restore','DEMO_SEEDS only'],None,'#9a6500',status='Unit + local stack')
d.arrow([(326,720),(346,720),(346,513),(366,513)])
d.card(1106,640,298,160,'Microsoft-Decision-1',['Claim checks · follow triggers','Clip Score'],None,PURPLE,status=AZ)
d.arrow([(1340,640),(1340,372)],'verdicts',1340,500,both=True)
d.rect(36,840,1368,98,'#f5f1fb','#dfd4ed')
d.text('TRIGGERS · Audience and follow targets read from the backend API',58,870,13,PURPLE,True)
d.text('1 min → summary   ·   Key event / 10 min → narrative (+ MomentClip)   ·   Each update → Decision-1 → follow narratives + FollowClip',58,901,17,INK)
d.save()

# Detailed backend boundary follows the reference board. Standard and custom stats stay separate.
d=Diagram('user-backend/architecture.svg','Main user backend','ETL owns standard stats and historical events in Azure SQL. GraphQL (Data API builder) is the backend’s only path to them.',1680,1420,'DESIGN + BUILT · Solid: data / calls · Isolated executor for arbitrary code still planned')
# Service boundaries.
d.rect(24,145,270,655,'#fff4e5','#f4a34f')
d.text('ETL service',44,179,22,'#b86500',True)
d.rect(330,145,1050,990,'#e8f4ff',BLUE)
d.icon('containers',350,164,32)
d.text('User backend · Container Apps',395,188,22,BLUE,True)
d.rect(1420,335,236,690,'#effaf1','#69ad7d')
d.text('Frontend',1440,370,22,GREEN,True)
# Upstream stores are accessed only through ETL GraphQL.
d.card(44,210,230,145,'Azure SQL',['Standard stats'],'sql')
d.card(44,410,230,145,'ETL GraphQL',[],'graphql')
d.card(44,620,230,145,'Azure SQL',['Event history'],'sql')
d.text('Shared event stream',44,830,18,BLUE,True)
d.card(44,850,230,145,'Event Hubs',['Direct match events'],'events')
d.arrow([(159,355),(159,410)])
d.arrow([(159,620),(159,555)])
# Main API, identity and agent components.
d.rect(600,385,275,395,'#f7f1ff','#cbb9e9')
d.text('Microsoft Agent Framework',737,402,12,PURPLE,True,'middle')
d.card(355,410,205,145,'GraphQL helper',['Read-only queries'],'graphql')
d.card(615,410,245,145,'Question agent',['Existing stats first'],'agent',PURPLE)
d.card(925,410,230,145,'Chat + actions',[],'containers')
d.card(630,230,215,145,'Foundry models',['gpt-6.1-sol · Decision-1'],'foundry',PURPLE)
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
d.text('Bucket narratives · ranked stat IDs · moment and follow clips',720,1250,17,MUTED)
d.text('Service Bus live · GraphQL history',720,1280,15,MUTED)
d.arrow([(1040,1170),(1040,995)],'Stat IDs',1075,1150)
d.arrow([(1270,1170),(1270,995)],'Narratives',1310,1150)
# Future features, visually secondary.
# Built 22 Oct (unit-tested, local stack): follows with clips, cross-match reach, the demo-only seed adapter.
for x,title in [(355,'Follows + clips'),(555,'Cross-match'),(755,'Demo seeds')]:
 d.card(x,1040,175,70,title,(),color='#9a6500' if title=='Demo seeds' else BLUE)
d.text('BUILT 22 OCT',1075,1080,14,BLUE,True)
d.note('Standard stats: fetch → select → deliver. Custom requests: query history → test → run. Demo seeds exist only with DEMO_SEEDS=1.',1350)
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
d=Diagram('frontend/architecture.svg','Frontend','Application data comes from the user backend; demo start, cancel and progress from demo control. Video is the feed’s played HLS.',1320,870,'NOW · Solid: calls · Green: built and tested (unit, headless) · Demo control applied on Azure 22 Oct')
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
d.card(1110,430,174,180,'Demo control',['/demo-api/','start · cancel','status'],None,INK,status='Deployed 22 Oct')
d.arrow([(1041,520),(1110,520)],both=True)
d.rect(36,693,1248,84,'#eef9f0','#69ad7d')
d.text('BUILT 22 OCT · unit + headless tests',58,725,13,GREEN,True)
d.text('Start demo + start progress · main game · follow view · clip preview cards · sting + slow motion · other-match marking',58,752,17,INK)
d.save()
print('Rendered overview, five service SVGs and custom-calculation detail.')

# Explicit ownership: the backend never authors or reframes a shared narrative.
d=Diagram('user-backend/docs/narrative-framing.svg','Bucketed before it reaches the backend','Backend stores audience definitions and exposes an API. The narrative engine frames; the backend routes supplied versions without model calls.',1440,750)
d.rect(36,150,900,460,'#f5f0ff','#b6a0df')
d.rect(975,150,245,460,'#e8f4ff',BLUE)
d.text('NARRATIVE ENGINE',58,184,18,PURPLE,True)
d.card(60,250,240,160,'Neutral insight',['Shared match facts'],'agent',PURPLE)
d.card(380,250,240,160,'Bucket framing',['All available buckets'],'foundry',PURPLE)
d.card(700,250,210,160,'Publish',['Bucket ID + text'],'bus')
d.card(990,445,215,140,'Audience database',['Layers · options · meaning'],'postgres')
d.arrow([(300,330),(380,330)])
d.arrow([(620,330),(700,330)])
d.arrow([(990,515),(500,515),(500,410)],'GET audience-config',750,500)
d.card(1000,250,200,160,'User backend',['Route unchanged'],'containers')
d.card(1250,250,155,160,'Viewer',['Their bucket'],'screen',GREEN)
d.arrow([(910,330),(1000,330)],'Service Bus',955,310)
d.arrow([(1200,330),(1250,330)])
d.text('Shared versions, not a narrative workflow per viewer.',60,650,20,INK,True)
d.save()
