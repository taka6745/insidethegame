"""Build the editable target-architecture board; render via the Excalidraw CLI."""
import base64
import json
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ELEMENTS, FILES, NODES = [], {}, {}
INK, MUTED, BLUE, PURPLE, GREEN, ORANGE, GREY = '#17324d','#64748b','#147ac1','#7952b3','#168366','#b86500','#9299a4'


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
    width = max(len(line) for line in s.split('\n')) * size * .55
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


def icon(name,x,y,size=60,group=None,gray=False):
    p=ROOT/'.github/diagram-assets'/f'{name}.png'
    if p.exists():
        if name not in FILES:
            FILES[name]={'id':name,'mimeType':'image/png','dataURL':'data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode(),'created':1,'lastRetrieved':1}
        element('image',x,y,size,size,fileId=name,status='saved',scale=[1,1],crop=None,
                groupIds=[group] if group else [],opacity=35 if gray else 100)
    else:
        # Small native vector product symbols remain individually editable.
        if name == 'fanout':
            color = GREY if gray else BLUE
            for dy in (8, 25, 42):
                element('line',x+12,y+25,26,abs(dy-25),points=[[0,0],[26,dy-25]],
                        strokeColor=color,groupIds=[group] if group else [])
                element('ellipse',x+34,y+dy-4,8,8,backgroundColor='white',
                        strokeColor=color,groupIds=[group] if group else [])
            element('ellipse',x+6,y+19,12,12,backgroundColor='white',
                    strokeColor=color,groupIds=[group] if group else [])
            return
        box(x,y+7,size,size*.68,color=GREY if gray else BLUE,group=group)
        if name=='chart':
            for i,height in enumerate((18,30,42)):
                element('rectangle',x+8+i*16,y+48-height,10,height,strokeWidth=0,
                        backgroundColor=GREY if gray else GREEN,groupIds=[group] if group else [])
        elif name=='screen':
            element('line',x+size*.42,y+20,size*.2,22,points=[[0,0],[size*.2,11],[0,22],[0,0]],strokeColor=GREY if gray else BLUE,groupIds=[group] if group else [])
        else:
            for dy in (20,30,40):
                element('line',x+12,y+dy,size-24,0,points=[[0,0],[size-24,0]],strokeColor=GREY if gray else BLUE,groupIds=[group] if group else [])


def zone(key,x,y,w,h,title,sub,color,fill):
    box(x,y,w,h,fill,color,group=key)
    text(title,x+28,y+22,32,color,group=key)
    text(sub,x+28,y+68,19,MUTED,group=key)


def node(key,x,y,w,h,title,detail='',ic='file',color=BLUE,gray=False):
    NODES[key]=(x,y,w,h)
    box(x,y,w,h,'#f7f8fa' if gray else 'white',GREY if gray else '#cbd9e7',gray,group=key)
    icon(ic,x+(w-50)/2,y+12,50,key,gray)
    title_size = min(22, (w-24) / (len(title) * .55))
    text(title,x+10,y+74,title_size,GREY if gray else color,w-20,'center',key)
    if detail:
        detail = '\n'.join(textwrap.fill(part, max(10, int((w-24) / 8)), break_long_words=False) for part in detail.split('\n'))
        text(detail,x+10,y+106,16,GREY if gray else MUTED,w-20,'center',key)


def line(points,label=None,at=None,color=MUTED,dash=False,both=False):
    x,y=points[0]
    element('arrow',x,y,max(p[0] for p in points)-min(p[0] for p in points),
            max(p[1] for p in points)-min(p[1] for p in points),
            points=[[a-x,b-y] for a,b in points],startArrowhead='arrow' if both else None,
            endArrowhead='arrow',startBinding=None,endBinding=None,lastCommittedPoint=None,
            strokeColor=color,strokeWidth=2,strokeStyle='dashed' if dash else 'solid')
    if label:
        tx,ty=at; width=len(label)*11+20
        box(tx-width/2,ty-3,width,29,'white','white')
        text(label,tx-width/2,ty,18,color,width,'center')


text('INSIDE THE GAME',80,35,23,BLUE)
text('Master architecture',80,78,48)
text('TARGET DESIGN  ·  19 OCTOBER 2026',790,94,22,MUTED)
text('Shared match intelligence. Personal questions. One live experience.',80,146,25,MUTED)

zone('grf',80,250,800,530,'GRF / data generation','Synthetic Chelsea–United match · one aligned timeline',ORANGE,'#fff7e9')
zone('etl',80,1050,800,1390,'ETL / match facts','Azure Stream Analytics · service-owned storage',ORANGE,'#fff7e9')
zone('backend',1120,250,1320,1020,'Main user backend','Python · Azure Container Apps · Microsoft Agent Framework',BLUE,'#eaf5ff')
zone('narrative',1120,1390,1320,1050,'Narrative engine','Python · Azure Container Apps · Microsoft Agent Framework',PURPLE,'#f5efff')
zone('frontend',2660,250,700,2190,'Frontend / match experience','Static assets + CDN · one live connection per viewer',GREEN,'#eef9f0')

node('sim',130,370,200,155,'GRF engine','6-minute halves','python',ORANGE)
node('adapter',390,370,200,155,'Event adapter','Opta-style JSON','code',ORANGE)
node('record',650,370,180,155,'Recording','Events + clock','file',ORANGE)
node('roster',130,590,450,150,'Match presentation','22 named players · numbered kits','users',ORANGE)
node('video',650,590,180,150,'Video render','Full frame','screen',ORANGE)
text('Wider camera · no minimap',155,747,18,MUTED)
node('hub',330,835,300,150,'Azure Event Hubs','One match · independent consumers','events')
line([(330,447),(390,447)])
line([(590,447),(650,447)])
line([(230,525),(230,560),(740,560),(740,590)])
line([(830,447),(900,447),(900,805),(480,805),(480,835)],'Replay',(770,805))
line([(480,985),(40,985),(40,1247),(130,1247)])
line([(630,910),(1040,910),(1040,1065),(1190,1065)],'Live events',(910,910),BLUE,True)
line([(830,665),(940,665),(940,205),(3430,205),(3430,1005),(3290,1005)],'Aligned footage',(2780,205),GREEN)

node('asa',130,1170,300,155,'Stream Analytics','Event time + windows','stream',ORANGE)
node('key',650,1170,180,155,'Key events','Goals · reds · penalties · VAR','file',ORANGE)
node('raw',130,1430,200,155,'Raw passthrough','IDs · revisions','file',ORANGE)
node('window',390,1430,200,155,'Stat projections','Minute + match','chart',ORANGE)
node('notify',650,1430,180,155,'Service Bus','Committed triggers','bus',ORANGE)
node('sql',130,1690,200,170,'Azure SQL','Raw + key events','sql',ORANGE)
node('cosmos',390,1690,200,170,'Cosmos DB','Standard stats','cosmos',ORANGE)
node('etl-api',650,1810,180,170,'GraphQL API','History + stats','graphql',ORANGE)
line([(430,1247),(650,1247)])
line([(230,1325),(230,1430)])
line([(350,1325),(350,1370),(490,1370),(490,1430)])
line([(740,1325),(850,1325),(850,1630),(230,1630),(230,1690)],'Key ledger',(700,1605))
line([(230,1585),(230,1690)])
line([(490,1585),(490,1690)])
line([(330,1775),(360,1775),(360,1940),(650,1940)])
line([(590,1775),(620,1775),(620,1870),(650,1870)])
line([(830,1500),(1190,1500)],'Notifications',(1010,1480),ORANGE,True)
line([(830,1895),(995,1895),(995,610),(1190,610)],'History / stats',(995,570),ORANGE)
line([(995,1785),(1190,1785)],'GraphQL',(1080,1760),ORANGE)
node('commit',390,2040,440,150,'Commit + notify','Both stores readable before publication','code',ORANGE)
line([(230,1860),(230,2000),(510,2000),(510,2040)])
line([(490,1860),(490,1990),(650,1990),(650,2040)])
line([(830,2115),(865,2115),(865,1540),(830,1540)])
text('STANDARD STATS',130,2230,20,ORANGE)
text('Goals · attempts · passes · possession\nFouls · offsides · restarts · headed actions',130,2270,22,INK)
text('ETL owns facts. Backend never opens these databases.',130,2355,20,ORANGE)

node('models',1570,360,220,150,'Foundry models','Model deployments','foundry',PURPLE)
node('profiles',1890,360,240,150,'Profiles + sessions','One active tab','users')
node('pg',2180,360,220,150,'PostgreSQL','Accounts · Match App','postgres')
node('data-client',1190,540,220,150,'Data clients','ETL / narrative APIs','graphql')
node('question',1530,540,240,150,'Question agent','Reuse stats · clarify','agent',PURPLE)
node('chat',1890,540,240,150,'Chat + action API','Answers · Track / Untrack','containers')
node('compiler',1190,770,220,150,'Rule compiler','Validated structured DSL','code',PURPLE)
node('coder',1530,770,240,150,'Goal / coding agent','Test · repair ≤ 3','agent',PURPLE)
node('executor',1890,770,240,150,'Isolated executor','Separate container · read-only helper','python',PURPLE)
node('audience-api',2180,770,220,150,'Audience API','Layers · options · meaning','users')
node('index',1190,1000,280,150,'Shared filter index','Equivalent rules share results','code',PURPLE)
node('cards',1890,1000,240,150,'Cards + pins','Pin replaces lowest priority','chart',GREEN)
node('live',2180,1000,220,150,'Live gateway','Bucket routing · fan-out','fanout')
line([(1410,615),(1530,615)],both=True)
line([(1770,615),(1890,615)],both=True)
line([(1650,540),(1650,510)])
line([(2010,540),(2010,510)])
line([(2130,435),(2180,435)],both=True)
line([(1650,690),(1650,770)],'Goal',(1690,725))
line([(1530,845),(1410,845)])
line([(1300,920),(1300,1000)])
line([(1250,690),(1155,690),(1155,1020),(1190,1020)],'Backfill',(1155,950),BLUE)
line([(1470,1075),(1890,1075)],'Changed values',(1680,1052))
line([(1410,665),(1450,665),(1450,965),(2010,965),(2010,1000)],'Standard values',(1730,945))
line([(1960,690),(1850,690),(1850,940),(1950,940),(1950,1000)],'Pins',(1870,720))
line([(1770,845),(1890,845)],'Test runs',(1830,820),both=True)
line([(1470,1125),(1800,1125),(1800,890),(1890,890)],'Code path',(1800,980),PURPLE,both=True)
line([(1330,1150),(1330,1170),(2420,1170),(2420,435),(2400,435)],'Save state',(2290,1150),BLUE,both=True)
text('Rules · values · pins',1500,1140,17,BLUE)
line([(2290,510),(2290,770)],'Preferences',(2340,720))
line([(2130,1075),(2180,1075)],both=True)
line([(2130,615),(2730,615)],'Questions / replies',(2460,590),BLUE,both=True)
line([(2400,1075),(2580,1075),(2580,1380),(2730,1380)],'Live UI',(2620,1330),BLUE)
line([(2580,1380),(2580,1710),(2730,1710)],color=BLUE)
for x,title in [(1160,'Jev semantic follows'),(1475,'Clip resolver'),(1790,'Playback-aware state'),(2105,'Web search')]:
    box(x,1190,285,50,'#f7f8fa',GREY,True)
    text(title,x+10,1205,20,GREY,265,'center')

node('listener',1190,1490,220,145,'Notification listener','Minute · key event','bus',PURPLE)
node('orchestrator',1530,1490,240,145,'Match orchestrator','Clock · triggers · debounce','containers',PURPLE)
node('n-model',1890,1490,240,155,'Foundry models','Memory: small\nAuthor: strong','foundry',PURPLE)
node('match-client',1190,1720,220,150,'Match data client','Facts · key-event ledger','graphql',PURPLE)
node('context',1530,1720,240,150,'Context builder','Active blocks + recent facts','file',PURPLE)
node('summariser',1190,1950,220,150,'Minute summariser','Neutral · shared per match','agent',PURPLE)
node('compressor',1530,1950,240,150,'Context compressor','1 min → 5 min → earlier','agent',PURPLE)
node('author',1890,1950,240,150,'Narrative author','Once per enabled bucket','agent',PURPLE)
node('buckets',2180,1950,220,150,'Audience layers','Home / away / neutral × style','users',PURPLE)
node('memory',1190,2200,380,160,'Cosmos DB / match memory','Blocks · narratives · checkpoints','cosmos',PURPLE)
node('n-api',1630,2200,220,160,'Narrative GraphQL','Neutral recap + history','graphql',PURPLE)
node('publisher',2180,2200,220,160,'Narrative publisher','Dedupe · text + stat IDs','bus',PURPLE)
line([(1410,1560),(1530,1560)])
line([(1650,1635),(1650,1720)])
line([(1300,1870),(1300,1950)])
line([(1410,1795),(1530,1795)])
line([(1410,2025),(1530,2025)])
line([(1300,2100),(1300,2200)])
line([(1650,2100),(1650,2140),(1490,2140),(1490,2200)])
line([(1530,1840),(1490,1840),(1490,2200)],both=True)
line([(1770,1795),(1830,1795),(1830,2025),(1890,2025)])
line([(2010,1645),(2010,1950)],'Models',(2050,1810),PURPLE)
text('Foundry · small models',1190,1915,17,PURPLE)
line([(2180,2025),(2130,2025)])
line([(2010,2100),(2010,2280),(2180,2280)])
line([(1570,2280),(1630,2280)])
text('Ledger wins · include prior bucket narratives',1530,1895,17,PURPLE)
line([(2290,2360),(2290,2400),(1380,2400),(1380,2360)],'Persist before publish',(1890,2377),PURPLE)
line([(2400,2280),(2520,2280),(2520,1110),(2400,1110)],'Service Bus',(2520,2150),PURPLE,True)
line([(2400,845),(2475,845),(2475,2025),(2400,2025)],'Read config',(2475,1890),PURPLE)
line([(1740,2360),(1740,2470),(1075,2470),(1075,680),(1190,680)],'Recap history',(1075,2130),PURPLE)
text('All recap versions retained · active blocks form gap-free context',1190,2160,18,PURPLE)
text('Key event / 10 min → author · half-time → compress',1190,1660,18,PURPLE)

# Graphical frontend: controls, chat, full-frame pitch, five cards, narrative feed.
node('viewer-controls',2730,370,560,135,'Audience selection','Team support × viewer style','users',GREEN)
node('ask',2730,540,560,210,'Ask about the match','Short answer · as-of minute · clarification if needed','agent',GREEN)
line([(3010,505),(3010,540)],color=GREEN)
box(2790,690,190,35,'#e8f4ff','#c5d9ef');text('Track this stat',2805,696,18,BLUE)
box(2730,830,560,350,'#dcefe0','#75a686')
text('Live match',2750,850,25,GREEN)
# A small editable football pitch, rather than a screenshot of the product.
box(2770,905,480,225,'#e5f2e6','#75a686')
element('line',3010,905,0,225,points=[[0,0],[0,225]],strokeColor='#75a686')
element('ellipse',2960,967,100,100,strokeColor='#75a686')
box(2770,970,65,95,'transparent','#75a686');box(3185,970,65,95,'transparent','#75a686')
for px,py,col in [(2860,948,BLUE),(2910,1080,BLUE),(2990,940,BLUE),(3070,1050,'#b34353'),(3140,945,'#b34353'),(3160,1090,'#b34353')]:
    element('ellipse',px,py,15,15,backgroundColor=col,strokeColor=col)
text('Forward-only · shared match clock',2760,1142,20,GREEN)
box(2730,1260,560,220,'white','#cbd9e7');text('Five live stat cards',2750,1280,25,GREEN)
for i,label in enumerate(['Goals','Shots','Passes','Possession','Your pin']):
    box(2750+i*106,1340,96,100,'#f0f7f2','#bdd9c5')
    icon('chart',2770+i*106,1350,42)
    text(label,2752+i*106,1415,15,GREEN,92,'center')
box(2730,1580,560,300,'white','#cbd9e7')
text('Insights',2750,1600,27,GREEN);text('Already framed for your bucket',2750,1645,20,MUTED)
for y,width in [(1710,440),(1750,475),(1790,320)]:
    box(2760,y,width,12,'#d9eadd','#d9eadd')
text('History on join · no client-side stat calculation',2750,1830,19,MUTED)
box(2730,2010,560,310,'#f7f8fa',GREY,True)
text('PHASE 2',2755,2035,22,GREY)
for x,title,detail in [(2755,'Clips + highlights','Timestamp playlist'),(3020,'Playback controls','Rewind-aware context')]:
    node('p2-'+str(x),x,2090,240,170,title,detail,'screen',gray=True)
text('No per-viewer narrative generation',2730,2360,22,GREEN)

text('Solid: data / queries     Dashed arrows: messages     Grey boxes: Phase 2',80,2530,22,MUTED)
text('Azure target architecture · service ownership preserved · no viewer prompts into shared narrative generation',80,2570,21,MUTED)
scene={'type':'excalidraw','version':2,'source':'InsideTheGame target architecture',
       'elements':ELEMENTS,'appState':{'viewBackgroundColor':'#ffffff','theme':'light','gridSize':None,'zoom':{'value':.5}},'files':FILES}
(ROOT/'master-plan.excalidraw').write_text(json.dumps(scene,separators=(',',':'))+'\n')
print(f'Created {len(ELEMENTS)} editable elements, {len(FILES)} embedded icon assets')
