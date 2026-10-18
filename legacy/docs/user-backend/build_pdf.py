from pathlib import Path
import math
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, Color
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth

ROOT=Path(__file__).resolve().parents[2]; OUT=ROOT/'output/pdf/inside-the-game-backend-guide.pdf'; ASSET=ROOT/'docs/user-backend/pdf-assets'
OUT.parent.mkdir(parents=True, exist_ok=True)
W,H=842,595
C=canvas.Canvas(str(OUT),pagesize=(W,H),pageCompression=1)
C.setTitle('Inside the Game | User backend - visual build guide')
C.setAuthor('InsideTheGame')
INK='#152B46'; MUTED='#64758A'; BLUE='#1479CF'; PURPLE='#7754C7'; GREEN='#13896C'; LINE='#DCE5EE'; PALE='#F3F7FB'; GREY='#8C97A5'

def rect(x,y,w,h,fill='white',stroke=None,r=10,dash=False):
 C.saveState();C.setFillColor(HexColor(fill));C.setStrokeColor(HexColor(stroke or fill));C.setLineWidth(1)
 if dash:C.setDash(4,3)
 C.roundRect(x,H-y-h,w,h,r,stroke=bool(stroke),fill=1);C.restoreState()
def txt(s,x,y,size=12,color=INK,bold=False,align='left'):
 C.setFillColor(HexColor(color));C.setFont('Helvetica-Bold' if bold else 'Helvetica',size)
 if align=='center':C.drawCentredString(x,H-y-size,s)
 elif align=='right':C.drawRightString(x,H-y-size,s)
 else:C.drawString(x,H-y-size,s)
def para(s,x,y,w,size=11,color=MUTED,leading=None,bold=False):
 font='Helvetica-Bold' if bold else 'Helvetica';leading=leading or size*1.4
 yy=y
 for part in s.split('\n'):
  line=''
  for word in part.split():
   trial=(line+' '+word).strip()
   if stringWidth(trial,font,size)>w and line:
    txt(line,x,yy,size,color,bold);yy+=leading;line=word
   else:line=trial
  if line:txt(line,x,yy,size,color,bold);yy+=leading
 return yy

def icon(name,cx,cy,size=42):
 p=ASSET/(name+'.png');im=ImageReader(str(p));iw,ih=im.getSize();s=size/max(iw,ih)
 C.drawImage(im,cx-iw*s/2,H-cy-ih*s/2,width=iw*s,height=ih*s,mask='auto')
def arrow(points,color=BLUE,both=False,dash=False,width=1.6,head=True):
 C.saveState();C.setStrokeColor(HexColor(color));C.setFillColor(HexColor(color));C.setLineWidth(width)
 if dash:C.setDash(4,3)
 p=C.beginPath();p.moveTo(points[0][0],H-points[0][1])
 for x,y in points[1:]:p.lineTo(x,H-y)
 C.drawPath(p)
 C.setDash()
 def ah(a,b):
  dx=b[0]-a[0];dy=b[1]-a[1];l=math.hypot(dx,dy);ux=dx/l;uy=dy/l
  path=C.beginPath();path.moveTo(b[0],H-b[1]);path.lineTo(b[0]-6*ux+3*uy,H-(b[1]-6*uy-3*ux));path.lineTo(b[0]-6*ux-3*uy,H-(b[1]-6*uy+3*ux));path.close();C.drawPath(path,fill=1,stroke=0)
 if head:ah(points[-2],points[-1])
 if both:ah(points[1],points[0])
 C.restoreState()
def circle(x,y,r,fill,stroke=None):
 C.setFillColor(HexColor(fill));C.setStrokeColor(HexColor(stroke or fill));C.circle(x,H-y,r,stroke=bool(stroke),fill=1)
def badge(s,x,y,fill='#E8F3FD',color=BLUE):
 w=stringWidth(s,'Helvetica-Bold',9)+18;rect(x,y,w,20,fill,r=6);txt(s,x+9,y+5,9,color,True)
def line(x,y,w,color=LINE):arrow([(x,y),(x+w,y)],color,width=1,head=False)
def glyph(kind,cx,cy,size=40,color=BLUE):
 C.saveState();C.setStrokeColor(HexColor(color));C.setFillColor(HexColor(color));C.setLineWidth(2)
 if kind=='check':
  C.circle(cx,H-cy,size/2,stroke=1,fill=0);arrow([(cx-size*.24,cy),(cx-size*.06,cy+size*.17),(cx+size*.27,cy-size*.2)],color,width=2.5,head=False)
 elif kind=='chart':
  for i,h in enumerate([.35,.65,.95]):rect(cx-size*.42+i*size*.3,cy+size*.4-size*h,size*.18,size*h,color,r=2)
 elif kind=='route':
  for dy in [-14,0,14]:arrow([(cx-20,cy),(cx,cy),(cx+18,cy+dy)],color,width=1.6)
 elif kind=='code':
  arrow([(cx-8,cy-15),(cx-23,cy),(cx-8,cy+15)],color,width=2.5,head=False);arrow([(cx+8,cy-15),(cx+23,cy),(cx+8,cy+15)],color,width=2.5,head=False)
 elif kind=='play':
  C.roundRect(cx-size/2,H-cy-size*.34,size,size*.68,5,fill=0,stroke=1)
  p=C.beginPath();p.moveTo(cx-5,H-cy+8);p.lineTo(cx+9,H-cy);p.lineTo(cx-5,H-cy-8);p.close();C.drawPath(p,fill=1,stroke=0)
 elif kind=='clock':
  C.circle(cx,H-cy,size/2,fill=0,stroke=1);arrow([(cx,cy-size*.3),(cx,cy),(cx+size*.25,cy)],color,width=2,head=False)
 elif kind=='link':
  C.roundRect(cx-24,H-cy-7,28,14,7,fill=0,stroke=1);C.roundRect(cx-3,H-cy-7,28,14,7,fill=0,stroke=1)
 elif kind=='lock':
  C.roundRect(cx-17,H-cy-18,34,27,5,fill=0,stroke=1);C.arc(cx-11,H-cy+1,cx+11,H-cy+27,startAng=0,extent=180);C.circle(cx,H-cy-3,2,fill=1,stroke=0)
 elif kind=='pitch':
  C.roundRect(cx-size*.65,H-cy-size*.4,size*1.3,size*.8,4,fill=0,stroke=1);C.line(cx,H-cy-size*.4,cx,H-cy+size*.4);C.circle(cx,H-cy,7,fill=0,stroke=1)
 C.restoreState()

def header(n,kicker,title,sub):
 rect(0,0,W,H,'#FFFFFF',r=0)
 txt('INSIDE THE GAME',36,24,10,BLUE,True);txt(kicker.upper(),806,24,9,MUTED,True,'right')
 txt(title,36,51,28,INK,True);txt(sub,36,91,12,MUTED)
 line(36,555,770)
 txt('USER BACKEND  /  Planning guide  /  18 Oct 2026',36,567,8,MUTED)
 txt(f'{n} / 4',806,567,8,MUTED,align='right')

def page1():
 header(1,'System overview','One match. One shared backend.','GraphQL brings the match in. The backend turns it into each viewer\'s experience.')
 rect(36,148,146,230,PALE)
 glyph('pitch',109,194,41,GREEN);txt('Match pipeline',109,225,12,INK,True,'center');txt('Events + computed stats',109,244,9.5,MUTED,align='center')
 line(56,268,106)
 icon('agent',109,302,38);txt('Narrative engine',109,328,12,INK,True,'center');txt('Bucket versions + stat choices',109,349,8.8,MUTED,align='center')
 icon('graphql',242,250,49);txt('GraphQL',242,284,12,INK,True,'center');txt('History + live',242,302,10,MUTED,align='center')
 arrow([(183,251),(207,251)],PURPLE);arrow([(271,251),(305,251)],PURPLE,both=True)
 rect(310,148,284,230,'#EEF6FD','#BDD8EF')
 icon('containers',338,176,30);txt('Python backend',363,160,16,INK,True);txt('Azure Container Apps*',363,184,10,MUTED)
 line(328,210,248,'#C9DDED')
 icon('agent',371,252,40);icon('python',523,252,40)
 txt('Question + coding',371,282,10.5,INK,True,'center');txt('agents',371,297,10.5,INK,True,'center')
 txt('Stats engine',523,282,11,INK,True,'center');txt('Shared calculations',523,300,9.5,MUTED,align='center')
 arrow([(409,253),(483,253)],BLUE,both=True)
 rect(328,325,248,36,'#FFFFFF');icon('users',348,343,23);txt('Profiles, sessions and routing',369,336,10.5,INK,True)
 rect(653,157,153,214,'#FFFFFF','#BBCDDD')
 for i in range(3):circle(667+i*10,170,2.3,'#B6C6D5')
 txt('Frontend',730,190,14,INK,True,'center');glyph('play',730,230,42)
 rect(665,267,61,27,'#E9F3FC');rect(731,267,63,27,'#F0EBFA');txt('Agent',695,275,9,BLUE,True,'center');txt('Narratives',762,275,9,PURPLE,True,'center')
 for i in range(3):rect(665+i*44,308,39,37,PALE);glyph('chart',684+i*44,326,17,BLUE)
 arrow([(648,238),(599,238)],INK);txt('Actions',622,218,8.5,MUTED,align='center')
 arrow([(599,294),(648,294)],BLUE);txt('Live updates',623,309,8,MUTED,align='center')
 rect(310,423,284,109,'#F8FAFC',LINE);icon('postgres',337,452,34);txt('Azure PostgreSQL server*',365,436,12,INK,True)
 rect(328,477,111,37,'#EAF2FC');txt('Accounts DB',383,482,10,INK,True,'center');txt('Demo profiles',383,497,8.5,MUTED,align='center')
 rect(450,477,125,37,'#EAF2FC');txt('Match App DB',512,482,10,INK,True,'center');txt('Chats, pins, functions',512,497,8.5,MUTED,align='center')
 arrow([(452,383),(452,418)],BLUE,both=True)
 rect(653,423,153,109,'#F8FAFC',LINE);glyph('lock',678,448,30,PURPLE);txt('Isolated executor',731,474,11,INK,True,'center');txt('Generated Python',731,493,10,MUTED,align='center')
 arrow([(594,345),(622,345),(622,408),(730,408),(730,418)],PURPLE)
 txt('Neutral engine stays independent',36,407,11,INK,True)
 para('Questions never create personal narrative workflows. Deduplication stays upstream.',36,429,248,11)
 para('* Hosting and database defaults selected for the plan. Agent Framework + Foundry are locked in.',36,492,248,9,MUTED)
 C.showPage()

def page2():
 header(2,'Custom statistics','Ask once. Build, test, then pin.','The question agent defines the goal. A specialist coding agent writes the function.')
 rect(36,124,770,45,'#F0F6FC');txt('VIEWER',51,138,9,BLUE,True);txt('"How many headers has Chelsea made since minute 20?"',116,135,15,INK,True)
 steps=[('agent','Understand','Meaning + available data'),('python','Write function','Python / regex / filters'),('check','Check result','Test against the goal'),('graphql','Calculate','History, then live events'),('chart','Offer to pin','A running stat card')]
 for i,(ic,title,caption) in enumerate(steps):
  x=36+i*158
  rect(x,197,138,132,PALE)
  badge(str(i+1),x+10,207)
  if ic in ['agent','python','graphql']:icon(ic,x+69,248,39)
  else:glyph(ic,x+69,248,35,GREEN if ic=='check' else BLUE)
  txt(title,x+69,279,12,INK,True,'center')
  # short controlled captions
  para(caption,x+13,300,112,9.5,MUTED,12)
  if i<4:arrow([(x+142,260),(x+153,260)],BLUE)
 arrow([(421,335),(421,356),(263,356),(263,335)],PURPLE)
 txt('Up to 3 repairs, then explain failure',342,365,10,PURPLE,align='center')
 rect(36,408,354,121,'#F5F2FB','#DED3EE');glyph('lock',66,439,28,PURPLE);txt('Controlled execution',91,421,13,INK,True)
 para('Fixed libraries + read-only GraphQL.\nValidate before use; no ongoing semantic checks.\nEquivalent requests share one match-scoped function.',53,460,320,10.5,leading=16)
 txt('PINNING REPLACES THE LOWEST DEFAULT',431,411,9,BLUE,True)
 for i,name in enumerate(['Goals','Cards','Possession']):
  x=431+i*127;rect(x,434,115,33,PALE,LINE);txt(name,x+57.5,444,10,MUTED,align='center')
 for i,name in enumerate(['Goals','Cards','Headers*']):
  x=431+i*127;rect(x,487,115,33,'#E2F3ED' if i==2 else PALE,GREEN if i==2 else LINE);txt(name,x+57.5,497,10,GREEN if i==2 else MUTED,i==2,'center')
 arrow([(742,471),(742,483)],GREEN)
 txt('* Illustrative 3-slot layout. Pinning is a separate viewer choice.',431,532,8.5,MUTED)
 C.showPage()

def page3():
 header(3,'Personalisation','Twelve views of shared intelligence.','The narrative engine supplies the wording, target bucket and ranked default stat changes.')
 icon('users',65,159,40);txt('Demo profile',99,139,14,INK,True);txt('Supported team + fan style',99,160,11,MUTED)
 badge('ONE LIVE MATCH',639,145)
 # Matrix uses actual bucket dimensions, not separate agents.
 labels=['Analytical','Simple','Casual','Experienced']
 x0=146;cw=107;rh=54;y0=236
 for j,s in enumerate(labels):txt(s,x0+j*cw+47,206,10.5,INK,True,'center')
 for i,(name,col,bg) in enumerate([('Team A',BLUE,'#EAF3FC'),('Team B',PURPLE,'#F1ECFA'),('Neutral',MUTED,'#F0F3F7')]):
  txt(name,51,y0+i*rh+15,11,col,True)
  for j in range(4):
   x=x0+j*cw;rect(x,y0+i*rh,94,43,bg)
   # Story glyph: one short heading and two lines.
   rect(x+13,y0+i*rh+11,39,4,col,r=1)
   rect(x+13,y0+i*rh+21,67,3,'#BAC8D5',r=1)
   rect(x+13,y0+i*rh+29,55,3,'#BAC8D5',r=1)
 # One selected bucket highlight.
 C.saveState();C.setStrokeColor(HexColor(GREEN));C.setLineWidth(2);C.roundRect(x0+2*cw,H-y0-43,94,43,10,fill=0,stroke=1);C.restoreState()
 arrow([(563,257),(606,257)],GREEN)
 rect(616,207,190,190,'#F5FAF8','#CBE4DA');txt('Viewer feed',711,223,14,INK,True,'center')
 for k in range(3):
  rect(631,257+k*38,160,29,'#FFFFFF','#DDEAE4');rect(643,267+k*38,110-k*17,4,'#B4CFC2',r=1);rect(643,276+k*38,83,3,'#D2E1D9',r=1)
 txt('Existing bucket variants',711,375,9.5,GREEN,align='center')
 txt('UP TO 12 VERSIONS - ONLY RELEVANT BUCKETS',146,409,9,BLUE,True)
 para('An insight may have four versions for one team, or versions for all twelve buckets. The user backend routes them without rewriting.',146,430,425,11)
 rect(36,489,770,43,'#F4F7FB')
 icon('agent',60,510,25);txt('"New stats"',83,500,11,INK,True);txt('Bucket + priority order',83,514,9,MUTED)
 arrow([(240,510),(279,510)],BLUE)
 txt('goals, cards, ...',296,497,12,INK,True);txt('Approved stat pool',296,514,9,MUTED)
 arrow([(436,510),(478,510)],BLUE)
 glyph('chart',504,510,24);txt('Fetch values; preserve pins',530,501,12,INK,True)
 para('Joining mid-match loads the backlog and current bucket selection.',616,427,190,11)
 C.showPage()

def phase_card(x,y,w,title,kind,body):
 rect(x,y,w,99,'#F8F9FA','#BCC4CE',dash=True)
 glyph(kind,x+29,y+31,28,GREY);txt(title,x+62,y+18,12,'#586777',True);para(body,x+16,y+57,w-32,10.5,'#6D7986',14)

def page4():
 header(4,'Build sequence + later','Build the live experience first.','A small implementation sequence, with the second version kept visibly separate.')
 badge('PHASE 1',36,125,fill='#E3F3ED',color=GREEN)
 phases=[('containers','Connect','Python API, GraphQL\nand demo profiles'),('agent','Answer','Agent Framework +\nFoundry models'),('python','Calculate','Executor, test harness\nand shared stat state'),('chart','Deliver','Live cards, narratives\nand session recovery')]
 for i,(ic,title,body) in enumerate(phases):
  x=36+i*196;rect(x,160,182,146,'#F1F8F5','#D8EAE2')
  if ic=='chart':glyph(ic,x+30,190,29,GREEN)
  else:icon(ic,x+30,190,31)
  txt(f'{i+1}. {title}',x+54,181,14,INK,True)
  para(body,x+17,222,150,11,INK,16)
  if i<3:arrow([(x+184,232),(x+192,232)],GREEN)
 txt('One profile = one active tab. New tabs take over. Work survives a viewer disconnect.',36,321,11,MUTED)
 badge('PHASE 2',36,365,fill='#ECEFF3',color='#697788')
 phase_card(36,399,244,'Semantic subscriptions','link','Jev checks incoming narratives. Show a matching insight linked to the request.')
 phase_card(299,399,244,'Highlights + replay','play','Return ordered sources and time ranges. The frontend plays the segments.')
 phase_card(562,399,244,'Follow playback time','clock','Rewind narratives, stat values and bucket selections. Avoid future spoilers.')
 txt('To finalise: sandbox technology, model deployments, live transport and API contracts.',36,516,10,MUTED)
 # Small, readable provenance line with clickable sources.
 txt('Basis: agreed architecture, 18 Oct 2026.',36,537,8,MUTED)
 sources=[('Azure', 'https://learn.microsoft.com/en-us/azure/container-apps/overview'),('GraphQL','https://graphql.org/learn/subscriptions/'),('Jev','https://docs.typesafe.ai/introduction'),('Icon library','https://github.com/amattas/microsoft-excalidraw')]
 x=543
 for label,url in sources:
  ww=stringWidth(label,'Helvetica',8);txt(label,x,537,8,BLUE);C.linkURL(url,(x,H-549,x+ww,H-535),relative=0);x+=ww+17
 C.showPage()

page1();page2();page3();page4();C.save();print(OUT)
