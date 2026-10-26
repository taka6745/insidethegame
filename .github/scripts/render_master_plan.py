"""Build the complete editable product architecture and its GitHub-safe SVGs."""
import base64
import functools
import json
import subprocess
from pathlib import Path
from diagram_icons import inline_export_icons

ROOT = Path(__file__).resolve().parents[2]
ELEMENTS, FILES, NODES, ZONES, LABELS = [], {}, {}, [], {}
FONT = next((f for f in ('/System/Library/Fonts/Helvetica.ttc','/System/Library/Fonts/Supplemental/Arial.ttf',
                         '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf') if Path(f).exists()), None)


@functools.cache
def _font(size):
    from PIL import ImageFont
    return ImageFont.truetype(FONT, size)


def measure(s, size):
    """Rendered width of Excalidraw's Helvetica text; an estimate when no metric font is installed."""
    return _font(size).getlength(s) if FONT else len(s) * size * .5
INK, MUTED, BLUE, PURPLE, GREEN, ORANGE, GREY = '#17324d','#64748b','#147ac1','#7952b3','#168366','#b86500','#9299a4'
ROSE = '#b8325a'


def element(kind, x, y, w, h, **fields):
    n = len(ELEMENTS) + 1
    item = dict(id=f'master-{n}', type=kind, x=x, y=y, width=w, height=h,
                angle=0, strokeColor=INK, backgroundColor='transparent', fillStyle='solid',
                strokeWidth=1.5, strokeStyle='solid', roughness=0, opacity=100,
                groupIds=[], frameId=None, roundness=None, seed=n, version=1,
                versionNonce=n, isDeleted=False, boundElements=[], updated=1, link=None, locked=False)
    item.update(fields)
    ELEMENTS.append(item)
    return item


def text(s,x,y,size=22,color=INK,w=None,align='left',group=None):
    if align == 'center' and w and '\n' in s:
        # One element per line keeps every line centred in any renderer.
        for i, part in enumerate(s.split('\n')):
            item = text(part,x,y+i*size*1.25,size,color,w,align,group)
        return item
    width = max(measure(line, size) for line in s.split('\n'))
    if align == 'center' and w:
        x += max(0, (w - width) / 2)
    return element('text',x,y,width,size*1.25*len(s.split('\n')),text=s,originalText=s,
                   fontSize=size,fontFamily=2,textAlign='left',verticalAlign='top',
                   containerId=None,autoResize=True,lineHeight=1.25,strokeColor=color,
                   groupIds=[group] if group else [])


def box(x,y,w,h,fill='white',color='#d4dfeb',dash=False,group=None):
    return element('rectangle',x,y,w,h,backgroundColor=fill,strokeColor=color,
                   strokeStyle='dashed' if dash else 'solid',roundness={'type':3},
                   groupIds=[group] if group else [])


# Native glyphs drawn inside the icon frame (coordinates for a 50 px icon).
GLYPHS = {
    'code': [[(19,15),(12,24),(19,33)],[(31,15),(38,24),(31,33)],[(28,14),(22,34)]],
    'grid': [[(14,14),(23,14),(23,22),(14,22),(14,14)],[(27,14),(36,14),(36,22),(27,22),(27,14)],
             [(14,26),(23,26),(23,34),(14,34),(14,26)],[(27,26),(36,26),(36,34),(27,34),(27,26)]],
    'flag': [[(18,12),(18,37)],[(18,13),(35,19),(18,25)]],
    'check': [[(15,24),(22,31),(36,16)]],
    'layers': [[(12,12),(30,12),(30,20),(12,20),(12,12)],[(16,19),(34,19),(34,27),(16,27),(16,19)],
               [(20,26),(38,26),(38,34),(20,34),(20,26)]],
    'sliders': [[(12,15),(38,15)],[(12,24),(38,24)],[(12,33),(38,33)]],
    'bolt': [[(29,11),(19,26),(28,26),(21,38)]],
    'send': [[(13,14),(38,24),(13,34),(18,24),(13,14)]],
    'client': [[(31,13),(38,13),(38,35),(31,35)],[(12,24),(31,24)],[(25,18),(31,24),(25,30)]],
    'kit': [[(16,13),(21,11),(29,11),(34,13),(39,19),(34,22),(34,37),(16,37),(16,22),(11,19),(16,13)]],
    'clock': [[(36, 24), (33, 32), (25, 35), (17, 32), (14, 24), (17, 16), (25, 13), (33, 16), (36, 24)],[(25,16),(25,24),(31,28)]],
    'chat': [[(12,13),(38,13),(38,29),(24,29),(17,35),(18,29),(12,29),(12,13)]],
    'record': [],
}
DOTS = {'sliders': [(19,15),(31,24),(23,33)], 'record': [(25,24)]}


def icon(name,x,y,size=60,group=None,gray=False,tint=BLUE):
    p=ROOT/'.github/diagram-assets'/f'{name}.png'
    if p.exists():
        if name not in FILES:
            FILES[name]={'id':name,'mimeType':'image/png','dataURL':'data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode(),'created':1,'lastRetrieved':1}
        element('image',x,y,size,size,fileId=name,status='saved',scale=[1,1],crop=None,
                groupIds=[group] if group else [],opacity=35 if gray else 100)
    else:
        # Small native vector product symbols remain individually editable.
        if name == 'fanout':
            color = GREY if gray else tint
            for dy in (8, 25, 42):
                element('line',x+12,y+25,26,abs(dy-25),points=[[0,0],[26,dy-25]],
                        strokeColor=color,groupIds=[group] if group else [])
                element('ellipse',x+34,y+dy-4,8,8,backgroundColor='white',
                        strokeColor=color,groupIds=[group] if group else [])
            element('ellipse',x+6,y+19,12,12,backgroundColor='white',
                    strokeColor=color,groupIds=[group] if group else [])
            return
        if name != 'chart':
            box(x,y+7,size,size*.68,color=GREY if gray else tint,group=group)
        color = GREY if gray else tint
        glyph = GLYPHS.get(name)
        if glyph is not None:
            for points in glyph:
                pts = [(x+a*size/50, y+b*size/50) for a,b in points]
                element('line',pts[0][0],pts[0][1],1,1,points=[[a-pts[0][0],b-pts[0][1]] for a,b in pts],
                        strokeColor=color,strokeWidth=2,groupIds=[group] if group else [])
            for cx,cy in DOTS.get(name, ()):
                element('ellipse',x+cx*size/50-4,y+cy*size/50-4,8,8,backgroundColor=color,
                        strokeColor=color,groupIds=[group] if group else [])
        elif name=='chart':
            for i,height in enumerate((18,30,42)):
                element('rectangle',x+8+i*16,y+48-height,10,height,strokeWidth=0,strokeColor=GREY if gray else tint,
                        backgroundColor=GREY if gray else tint,groupIds=[group] if group else [])
        elif name=='screen':
            element('line',x+size*.42,y+size*.3,size*.2,size*.36,points=[[0,0],[size*.2,size*.18],[0,size*.36],[0,0]],strokeColor=GREY if gray else tint,groupIds=[group] if group else [])
        else:
            for dy in (20,30,40):
                element('line',x+12,y+dy,size-24,0,points=[[0,0],[size-24,0]],strokeColor=GREY if gray else tint,groupIds=[group] if group else [])


def zone(key,x,y,w,h,title,sub,color,fill):
    ZONES.append((x,y,w,h,fill))
    box(x,y,w,h,fill,color,group=key)
    text(title,x+28,y+22,32,color,group=key)
    text(sub,x+28,y+68,19,MUTED,group=key)


def node(key,x,y,w,h,title,detail='',ic='file',color=BLUE,gray=False):
    NODES[key]=(x,y,w,h)
    box(x,y,w,h,'#f7f8fa' if gray else 'white',GREY if gray else '#cbd9e7',gray,group=key)
    icon(ic,x+(w-50)/2,y+8,50,key,gray,color)
    title_size = 21 if measure(title, 21) <= w - 20 else (w - 20) * 21 / measure(title, 21)
    text(title,x+10,y+66,title_size,GREY if gray else color,w-20,'center',key)
    if detail:
        detail = '\n'.join(wrap(detail, w - 24))
        text(detail,x+10,y+96,16,GREY if gray else MUTED,w-20,'center',key)


def wrap(detail, limit, size=16):
    """Wrap to a pixel width on ' · ' separators first, so no line starts or ends with one."""
    def greedy(tokens, sep):
        lines, current = [], ''
        for token in tokens:
            joined = f'{current}{sep}{token}' if current else token
            if current and measure(joined, size) > limit:
                lines.append(current)
                current = token
            else:
                current = joined
        return lines + [current]
    return [word_line for part in detail.split('\n') for line in greedy(part.split(' · '), ' · ')
            for word_line in (greedy(line.split(' '), ' ') if measure(line, size) > limit else [line])]


def line(points,label=None,at=None,color=MUTED,dash=False,both=False,badge=None):
    x,y=points[0]
    arrow = element('arrow',x,y,max(p[0] for p in points)-min(p[0] for p in points),
            max(p[1] for p in points)-min(p[1] for p in points),
            points=[[a-x,b-y] for a,b in points],startArrowhead='arrow' if both else None,
            endArrowhead='arrow',startBinding=None,endBinding=None,lastCommittedPoint=None,
            strokeColor=color,strokeWidth=2,strokeStyle='dashed' if dash else 'solid')
    if label:
        tx,ty=at
        # Centre the label on a nearby horizontal run of its own line.
        ty = next((a[1] - 13 for a, b in zip(points, points[1:])
                   if a[1] == b[1] and min(a[0],b[0]) <= tx <= max(a[0],b[0]) and abs(ty - a[1]) <= 30), ty)
        pad = 30 if badge else 0  # room for a product icon before the text
        width=measure(label,18)+24+pad
        LABELS[arrow['id']] = [box(tx-width/2,ty-3,width,29,'white','white'),
                               text(label,tx-width/2+pad,ty,18,color,width-pad,'center')]
        if badge:
            icon(badge,tx-width/2+8,ty-1,24)
            LABELS[arrow['id']].append(ELEMENTS[-1])


text('INSIDE THE GAME',80,35,23,BLUE)
text('Master architecture',80,78,48)
text('PRODUCT ARCHITECTURE',790,94,22,MUTED)
text('Shared match intelligence. Personal questions. One live experience.',80,146,25,MUTED)

zone('grf',80,250,800,530,'GRF / data generation','Synthetic footage + event feed · one aligned timeline',ROSE,'#fdf0f3')
zone('etl',80,1050,800,1390,'ETL / match facts','Service-owned storage',ORANGE,'#fff7e9')
zone('backend',1120,250,1320,1020,'Main user backend','Python · Azure Container Apps · Microsoft Agent Framework',BLUE,'#eaf5ff')
zone('narrative',1120,1370,1320,1070,'Narrative engine','Python · Azure Container Apps · Microsoft Agent Framework',PURPLE,'#f5efff')
zone('frontend',2660,250,700,2190,'Frontend / match experience','Cloudflare Worker → nginx / Azure Container Apps',GREEN,'#eef9f0')

node('roster',130,370,450,155,'Match presentation','22 named players · numbered kits\nWider camera · no minimap','kit',ROSE)
node('video',650,370,180,155,'Video + HLS','2 s segments','screen',ROSE)
node('sim',130,590,200,150,'GRF engine','45-minute halves','python',ROSE)
node('adapter',390,590,200,150,'Event adapter','Opta-style JSON','code',ROSE)
node('record',650,590,180,150,'Recording','Events + clock','record',ROSE)
node('hub',330,835,300,160,'Azure Event Hubs','Shared stream · independent consumers','events',INK)
line([(580,447),(650,447)])
line([(330,665),(390,665)])
line([(590,665),(650,665)])
line([(230,590),(230,557),(740,557),(740,525)])
line([(740,740),(740,805),(480,805),(480,835)],'Replay',(610,805),ROSE,True)
line([(400,995),(400,1170)],color=INK,dash=True)
line([(630,910),(1040,910),(1040,1065),(1190,1065)],'Own consumer group',(910,910),INK,True)
line([(830,447),(940,447),(940,205),(3430,205),(3430,1005),(3290,1005)],'HLS segments · CDN',(2780,205),ROSE)

node('asa',130,1170,300,155,'Stream Analytics','Event time + windows','stream',ORANGE)
node('key',650,1170,180,155,'Key events','Goals · reds · penalties · VAR','flag',ORANGE)
node('raw',130,1430,200,155,'Raw passthrough','IDs · revisions','file',ORANGE)
node('window',390,1430,200,155,'Stat projections','Minute + match','chart',ORANGE)
node('sql',130,1690,200,170,'Azure SQL','History · key events · SPADL','sql',ORANGE)
node('stats',390,1690,200,170,'Azure SQL','Standard stats','sql',ORANGE)
node('etl-api',650,1690,180,170,'GraphQL API','History + stats','graphql',ORANGE)
node('spadl',650,1430,180,155,'SPADL processor','Final actions + watermark','python',ORANGE)
node('commit',130,2040,460,150,'Readiness + notifications','Readers wait for SQL + SPADL watermarks','check',ORANGE)
line([(430,1247),(650,1247)])
line([(230,1325),(230,1430)])
line([(350,1325),(350,1370),(490,1370),(490,1430)])
line([(740,1325),(850,1325),(850,1630),(300,1630),(300,1690)],'Key ledger',(850,1380))
line([(200,1690),(200,1660),(690,1660),(690,1585)],'MA3 rows',(420,1660))
line([(790,1585),(790,1610),(330,1610),(330,1750)],'Final SPADL',(520,1610))
line([(230,1585),(230,1690)])
line([(490,1585),(490,1690)])
line([(590,1775),(650,1775)])
line([(280,1860),(280,1910),(740,1910),(740,1860)])
line([(180,1860),(180,2040)])
line([(490,1860),(490,2040)])
line([(590,2115),(1040,2115),(1040,1540),(1190,1540)],'Service Bus',(735,2115),ORANGE,True,badge='bus')
line([(995,1795),(995,610),(1190,610)],color=ORANGE)
line([(830,1795),(1190,1795)],color=ORANGE)
text('STANDARD STATS',130,2230,20,ORANGE)
text('Goals · attempts · passes · possession\nFouls · offsides · restarts · headed actions',130,2270,22,INK)
text('ETL owns facts. Backend never opens these databases.',130,2355,21,ORANGE)

node('models',1530,360,240,150,'Foundry models','Question · goal · replay · follow','foundry')
node('profiles',1890,360,220,150,'Profiles + sessions','Per viewer + match','users')
node('pg',2180,360,220,150,'PostgreSQL','Accounts · Match App','postgres')
node('data-client',1190,540,220,150,'Read-only data clients','ETL facts · narrative history','client')
node('question',1530,540,240,150,'Question router','Stats · evidence · replay tools','agent')
node('chat',1890,540,240,150,'Chat + action API','Answers · Track · audience','chat')
node('compiler',1190,770,220,150,'Rule compiler','Goal → typed rule DSL','code')
node('coder',1530,770,240,150,'Goal agent','Typed goal · bounded repairs','agent')
node('executor',1890,770,240,150,'Rule validation','Bounded DSL · deterministic checks','python')
node('audience-api',2180,770,220,150,'Configuration API','Audiences · prompts · policy · roles','sliders')
node('index',1190,1000,280,150,'Event ingest + snapshot','Ordered events · gap recovery\nmin(ETL, SPADL, received)','grid')
node('rule-execution',1530,1000,240,150,'Rule execution','Final SPADL · shared rules\nCount / sum / composites','code')
node('cards',1890,1000,220,150,'Cards + pins','Ranked defaults · pins','chart')
node('live',2180,1000,220,150,'Live delivery','Bucket/topic routing\nREST + WebSocket','fanout')
line([(1410,615),(1530,615)],both=True)
line([(1770,615),(1890,615)],both=True)
line([(1650,510),(1650,540)])
line([(1770,470),(1830,470),(1830,790),(1770,790)])
line([(2010,540),(2010,510)])
line([(2110,435),(2180,435)],both=True)
line([(1650,690),(1650,770)],both=True)
line([(1530,845),(1410,845)],both=True)
line([(1300,920),(1300,945),(1650,945),(1650,1000)])
line([(1190,670),(1155,670),(1155,1020),(1190,1020)])
line([(1770,1075),(1890,1075)],'Values',(1830,1062))
line([(1470,1040),(1490,1040),(1490,1158),(2290,1158),(2290,1150)],'Snapshot gate',(1720,1158))
line([(1410,650),(1450,650),(1450,980),(1570,980),(1570,1000)],'Final SPADL',(1450,870))
line([(1410,665),(1470,665),(1470,965),(2250,965),(2250,1000)],'Snapshot: stats + backlog',(1635,945))
line([(2000,965),(2000,1000)])  # stats branch to the cards
# Filled dots mark deliberate branches.
for bx,by,bc in [(2155,1020,MUTED),(2000,965,MUTED),(995,1795,ORANGE),(2610,1280,BLUE),(2610,1380,BLUE),(3430,1005,ROSE)]:
    element('ellipse',bx-6,by-6,12,12,backgroundColor=bc,strokeColor=bc)
line([(1390,690),(1390,735),(1910,735),(1910,770)],'Read-only',(1560,735))
line([(2130,670),(2155,670),(2155,1050),(2110,1050)],'Pins · bucket',(2155,715))
line([(2155,1020),(2180,1020)])  # bucket branch to gateway routing
line([(1770,845),(1890,845)],'Validate',(1830,832),both=True)
line([(1770,1125),(1800,1125),(1800,890),(1890,890)],'Validated rule',(1800,1000),both=True)
line([(2290,510),(2290,770)],'Catalogue · enabled flags',(2290,665),both=True)
line([(2110,1110),(2180,1110)],both=True)
line([(2130,625),(2730,625)],'Questions',(2550,612),GREEN,both=True)
line([(2730,470),(2640,470),(2640,585),(2130,585)],'Audience choice',(2540,572),GREEN)
line([(2400,1075),(2610,1075),(2610,1380),(2730,1380)],'Live UI',(2610,1180),BLUE)
line([(2610,1380),(2610,1710),(2730,1710)],color=BLUE)
line([(2610,1280),(2900,1280),(2900,1235)],'Clock',(2780,1280),BLUE)
box(1190,1170,560,75,'white','#cbd9e7')
text('Replay tools → code cuts published HLS',1210,1181,20,BLUE)
text('Observed evidence · clip playlists · cross-match reels',1210,1215,16,MUTED)
box(1800,1170,600,75,'white','#cbd9e7')
text('Follow planner → viewer confirms → shared topic',1820,1181,20,BLUE)
text('Postgres: sessions · questions · follows · calculations · config',1820,1215,16,MUTED)
line([(940,447),(940,1210),(1190,1210)],'Published HLS',(940,1000),ROSE)

node('listener',1190,1490,220,160,'Trigger listener','Service Bus · minute · key event','bolt',PURPLE)
node('orchestrator',1530,1490,240,160,'Match orchestrator','Per match · clock · periods','clock',PURPLE)
node('claim-checks',1890,1490,240,160,'Microsoft-Decision-1','Analyst + author checks\nRepair or drop unsupported text','check',PURPLE)
node('follow-topics',2180,1490,220,160,'Follow topics','Backend-owned config\nDeduplicated + confirmed','client',PURPLE)
node('topic-author',2180,1720,220,150,'Follow decisions','Gap + novelty checks\nDecision-1 → topic author','agent',PURPLE)
node('n-model',1890,1720,240,150,'Analyst + storylines','ETL trend evidence\nDecision-1 claim checks','foundry',PURPLE)
node('match-client',1190,1720,220,150,'Match data client','Facts · key-event ledger','client',PURPLE)
node('context',1530,1720,240,150,'Context builder','Facts · ledger · summaries\nPrior narratives','layers',PURPLE)
node('summariser',1190,1950,220,150,'Minute summariser','Neutral · shared per match','agent',PURPLE)
node('compressor',1530,1950,240,150,'Context compressor','1 → 5 min → earlier','agent',PURPLE)
node('author',1890,1950,240,150,'Narrative author','Per enabled team × style × length','agent',PURPLE)
node('buckets',2180,1950,220,150,'Enabled targets','Read-only catalogue · ETag cache','client',PURPLE)
node('memory',1490,2200,380,160,'Cosmos DB / match memory','Summaries · storylines · narratives\nCheckpoints · persist before publish','cosmos',PURPLE)
node('n-api',1190,2200,220,160,'Narrative GraphQL','Recaps · bucket backlog','graphql',PURPLE)
node('publisher',2180,2200,220,160,'Bucket + topic publisher','Narratives · MomentClip · FollowClip','send',PURPLE)
line([(1410,1560),(1530,1560)])
line([(1650,1650),(1650,1720)],'Key events · story turns',(1650,1665))
line([(1530,1610),(1460,1610),(1460,2000),(1410,2000)],'Minute',(1460,1680))
line([(1300,1870),(1300,1950)])
line([(1410,1795),(1530,1795)])
line([(1410,2060),(1530,2060)])
line([(1300,2100),(1300,2150),(1560,2150),(1560,2200)])
line([(1650,2100),(1650,2200)],both=True)
line([(1810,2200),(1810,1840),(1770,1840)])
line([(1770,1760),(1860,1760),(1860,2025),(1890,2025)])
line([(2010,1870),(2010,1950)])
line([(1770,1795),(1890,1795)],'Trends + context',(1830,1782))
line([(2180,2025),(2130,2025)])
line([(2010,2100),(2010,2160),(2250,2160),(2250,2200)])
line([(1490,2280),(1410,2280)])
line([(2180,2280),(1870,2280)],'Persist before publish',(2025,2267))
line([(2400,2280),(2560,2280),(2560,1110),(2400,1110)],'Service Bus',(2560,2150),PURPLE,True,badge='bus')
line([(2400,845),(2470,845),(2470,2025),(2400,2025)],'Read config',(2470,1318),BLUE)
line([(1190,2300),(1075,2300),(1075,640),(1190,640)],'Recaps · backlog',(1088,1330),PURPLE)

line([(2010,1650),(2010,1720)],color=PURPLE,both=True)
line([(2130,1570),(2150,1570),(2150,2010),(2130,2010)],color=PURPLE,both=True)
line([(2290,1650),(2290,1720)],color=PURPLE)
line([(2400,1795),(2510,1795),(2510,2240),(2400,2240)],'Follow updates + clips',(2510,2070),PURPLE)
line([(2400,1205),(2525,1205),(2525,1530),(2400,1530)],'Confirmed topics',(2525,1340),BLUE)
line([(1770,1760),(1810,1760),(1810,1695),(2290,1695),(2290,1720)],'Events + storylines',(2110,1695),PURPLE)
line([(1650,1490),(1650,1470),(2590,1470),(2590,2320),(2400,2320)],'Shared MomentClip',(2350,1470),PURPLE,dash=True)
text('Shared analysis per match · author per bucket · questions never trigger this workflow',1170,2400,19,PURPLE)
# Graphical frontend: controls, chat, full-frame pitch, five cards, narrative feed.
box(2730,370,560,135,'white','#cbd9e7');text('Audience selection',2750,385,25,GREEN)
box(2750,435,520,45,'#f0f7f2','#bdd9c5')
text('Enabled audience bucket                         ▾',2770,446,20,GREEN)
box(2730,590,560,210,'white','#cbd9e7');text('Ask about the match',2750,610,25,GREEN)
text('Short answer · as-of minute · clarification if needed',2750,652,19,MUTED)
box(2930,688,340,34,'#e8f4ff','#c5d9ef');text('Riverton Rovers headed passes since 20′?',2945,695,16,BLUE)
box(2750,740,190,35,'#e8f4ff','#c5d9ef');text('Track this stat',2765,746,18,BLUE)
box(2730,885,560,350,'#dcefe0','#75a686')
text('Match video',2750,905,25,GREEN)
box(3180,905,90,30,'#b34353','#b34353');text('LIVE',3180,909,18,'white',90,'center')
# Broadcast-camera frame (perspective pitch), matching the wide GRF render.
box(2770,960,480,195,'#cfe6d5','#75a686')
element('line',2800,1140,1,1,points=[[0,0],[80,-160],[340,-160],[420,0],[0,0]],strokeColor='#75a686',strokeWidth=2)
element('line',3010,980,0,160,points=[[0,0],[0,160]],strokeColor='#75a686')
element('ellipse',2950,1040,120,40,strokeColor='#75a686')
for px,py,col in [(2890,1095,BLUE),(2950,1015,BLUE),(2990,1105,BLUE),(3060,1030,'#b34353'),(3110,1090,'#b34353'),(3150,1005,'#b34353')]:
    element('ellipse',px,py,13,13,backgroundColor=col,strokeColor=col)
text('HLS live · data held to the picture',2760,1197,19,GREEN)
box(2730,1320,560,220,'white','#cbd9e7');text('Five live stat cards',2750,1340,25,GREEN)
for i,label in enumerate(['Goals','Attempts','Passes','Possession','Your pin']):
    box(2750+i*106,1400,96,100,'#f0f7f2','#bdd9c5')
    icon('chart',2770+i*106,1410,42,tint=GREEN)
    text(label,2752+i*106,1475,15,GREEN,92,'center')
box(2730,1625,560,300,'white','#cbd9e7')
text('Insights',2750,1645,25,GREEN);text('Already framed for your bucket',2750,1690,19,MUTED)
for y,width in [(1755,440),(1795,475),(1835,320)]:
    box(2760,y,width,12,'#d9eadd','#d9eadd')
text('History on join · no client-side stat calculation',2750,1875,19,MUTED)
box(2730,2010,560,310,'white','#cbd9e7')
text('Replay',2750,2030,25,GREEN)
for x,title,detail in [(2755,'Clip playlist','In chat · show more'),(3020,'Expanded replay','Live in corner PiP')]:
    node('replay-'+str(x),x,2090,240,170,title,detail,'screen',GREEN)
line([(3430,1005),(3430,2165),(3290,2165)],color=ROSE)  # VOD replays reuse live segments
text('No per-viewer narrative generation',2730,2360,21,GREEN)

# Legend with drawn samples.
line([(80,2521),(170,2521)])
text('Data direction',185,2508,21,MUTED)
line([(560,2521),(650,2521)],dash=True)
text('Event Hubs / Service Bus message',665,2508,21,MUTED)
line([(1080,2521),(1170,2521)],both=True)
text('Two-way exchange',1185,2508,21,MUTED)
element('ellipse',1774,2515,12,12,backgroundColor=MUTED,strokeColor=MUTED)
text('Branch · a gap marks a crossing, not a join',1800,2508,21,MUTED)
# Colour swatches: arrows take the sending service's colour.
text('Colour = sender:',80,2560,21,MUTED)
sx = 80 + measure('Colour = sender:', 21) + 30
for color,name in [(ROSE,'GRF'),(ORANGE,'ETL'),(BLUE,'Backend'),(PURPLE,'Narrative'),(GREEN,'Frontend'),(INK,'Shared stream'),(MUTED,'Within a service')]:
    element('line',sx,2573,50,0,points=[[0,0],[50,0]],strokeColor=color,strokeWidth=4)
    text(name,sx+62,2560,21,color)
    sx += 62 + measure(name, 21) + 40
text('Standard stats: ETL · audience configuration: backend · narrative framing: engine · all reads bounded to observed events',80,2615,21,MUTED)

def hop_crossings():
    """Gap one connector at each crossing; the other is drawn over the gap.

    Gaps go into the longer segment, then crossings are flipped wherever two gaps
    would sit close together on one segment and read as a dashed line.
    """
    arrows = [e for e in ELEMENTS if e['type'] == 'arrow']
    def segments(a):
        pts = [(a['x']+px, a['y']+py) for px,py in a['points']]
        return [(a, k, p1, p2) for k, (p1, p2) in enumerate(zip(pts, pts[1:]))]
    found = []
    for a in arrows:
        for b in arrows:
            for h in segments(a):
                if a is b or h[2][1] != h[3][1]:
                    continue
                for v in segments(b):
                    x, y = v[2][0], h[2][1]
                    if v[2][0] == v[3][0] and min(h[2][0],h[3][0])+3 < x < max(h[2][0],h[3][0])-3 \
                            and min(v[2][1],v[3][1])+3 < y < max(v[2][1],v[3][1])-3:
                        longer_h = abs(h[3][0]-h[2][0]) >= abs(v[3][1]-v[2][1])
                        found.append([x, y, h, v, h if longer_h else v])
    for _ in range(4):
        for item in found:
            near = [o for o in found if o is not item and o[4][:2] == item[4][:2]
                    and abs(o[0]-item[0]) + abs(o[1]-item[1]) < 70]
            if near:
                item[4] = item[3] if item[4] is item[2] else item[2]
    crossings = [(x, y, cut[0], (v if cut is h else h)[0]) for x, y, h, v, cut in found]
    # Raise connectors until every kept line is drawn after the line it crosses.
    for _ in range(len(arrows)):
        late = [keep for _, _, cut, keep in crossings if ELEMENTS.index(keep) < ELEMENTS.index(cut)]
        if not late:
            break
        for item in [late[0], *LABELS.get(late[0]['id'], [])]:
            ELEMENTS.remove(item)
            ELEMENTS.append(item)
    for x, y, cut, keep in crossings:
        fill = next((f for zx,zy,zw,zh,f in ZONES if zx<x<zx+zw and zy<y<zy+zh), 'white')
        gap = element('rectangle',x-9,y-9,18,18,backgroundColor=fill,strokeColor=fill,strokeWidth=1)
        ELEMENTS.pop()
        gap['id'] = f'gap-{x}-{y}'
        ELEMENTS.insert(ELEMENTS.index(cut) + 1, gap)


hop_crossings()
scene={'type':'excalidraw','version':2,'source':'InsideTheGame product architecture',
       'elements':ELEMENTS,'appState':{'viewBackgroundColor':'#ffffff','theme':'light','gridSize':None,'zoom':{'value':.5}},'files':FILES}
(ROOT/'master-plan.excalidraw').write_text(json.dumps(scene,separators=(',',':'))+'\n')
print(f'Created {len(ELEMENTS)} editable elements, {len(FILES)} embedded icon assets')
subprocess.run(['npx', '--yes', '--registry=https://registry.npmjs.org',
                'mcp-excalidraw-server@2.1.2', 'render', str(ROOT/'master-plan.excalidraw'),
                '--format', 'svg', '--no-embed-fonts', '--out', str(ROOT/'master-plan.svg')], check=True)
inline_export_icons(ROOT/'master-plan.svg')
(ROOT/'architecture.svg').write_bytes((ROOT/'master-plan.svg').read_bytes())
