import test from 'node:test';
import assert from 'node:assert/strict';
import { ChatController } from '../lab/chat-controller.ts';
import { ChatView } from '../lab/chat-view.ts';
import { ChatApi } from '../lab/chat-api.ts';
import type { ChatSession } from '../lab/types.ts';
import { deferred, stub } from './support.ts';

const storage = () => { const values = new Map<string, string>(); return { getItem:(k: string) => values.get(k) ?? null, setItem:(k: string,v: string) => { values.set(k,v); } }; };
interface ViewDouble { renders: ChatSession[]; statuses: [string, boolean?][]; render(s: ChatSession): void; status(...s: [string, boolean?]): void }
const view = (): ViewDouble => ({ renders:[], statuses:[], render(s) { this.renders.push(s); }, status(...s) { this.statuses.push(s); } });
const controller = (api: object, v: ViewDouble) => new ChatController(stub<ChatApi>(api), stub<ChatView>(v), storage());

test('refresh of pending question polls saved completion', async () => {
  const v=view(), api={history:async () => ({turns:[{status:'complete',reply:{text:'4 shots'}}],mode:'local'})};
  const chat=controller(api,v);
  chat.matchId='m1';chat.token='token';chat.session={turns:[{status:'pending'}]};
  await chat.updateMatch({match_id:'m1'});
  assert.equal(v.renders.at(-1)!.turns[0]!.reply!.text,'4 shots');
  assert.equal(v.statuses.at(-1)![1],false);
});

test('late response cannot replace a new match conversation', async () => {
  const pending=deferred(),v=view();
  const chat=controller({ask:() => pending.promise,history:async () => ({turns:[],mode:'local'})},v);
  chat.token='old';chat.session={turns:[]};
  const sending=chat.send('How is it going?');
  chat.generation++;chat.matchId='new';
  pending.resolve({});await sending;
  assert.equal(v.renders.length,1); // only the optimistic old message, no late reply
});

test('session takeover stops polling until explicit reconnect', async () => {
  const v=view(),chat=controller({history:async () => { throw Object.assign(new Error('Taken over'),{code:'session_replaced'}); }},v);
  chat.token='old';await chat.pollHistory();
  assert.equal(chat.token,null);
  assert.match(v.statuses.at(-1)![0],/Reconnect/);
});

test('failed send retries same prompt using same idempotency ID', async () => {
  const calls: unknown[][]=[],v=view();
  const api={ask:async (...args: unknown[]) => { calls.push(args);throw new Error('Network'); }};
  const chat=controller(api,v);chat.token='t';chat.session={turns:[]};
  await chat.send('How many corners?');await chat.send('How many corners?');
  assert.equal(calls[0]![2],calls[1]![2]);
});

test('track button sends only the offer ID then refreshes state', async () => {
  const calls: unknown[][]=[],v=view();
  const chat=controller({track:async (...args: unknown[]) => calls.push(args),history:async () => ({turns:[],mode:'local'})},v);
  chat.token='t';await chat.track('offer');
  assert.deepEqual(calls,[['t','offer']]);
});

test('chat API carries request UUID and no client-generated rule on Track', async () => {
  const api=new ChatApi('/api','m1');const calls: unknown[][]=[];
  api.request=stub<ChatApi['request']>(async (...args: unknown[]) => calls.push(args));
  await api.ask('token','headers','uuid');await api.track('token','offer');
  assert.deepEqual(calls,[['/matches/m1/chat/token/messages',{prompt:'headers',request_id:'uuid'}],['/matches/m1/chat/token/offers/offer/track',{}]]);
});

test('question view treats model text and offer labels as text, not markup', () => {
  class Node {
    children: Node[];textContent: string;listeners: Record<string, () => void>;
    constructor(){this.children=[];this.textContent='';this.listeners={};}
    append(...children: Node[]){this.children.push(...children);}
    replaceChildren(...children: Node[]){this.children=children;}
    addEventListener(name: string,fn: () => void){this.listeners[name]=fn;}
    set innerHTML(value: string){throw new Error('Unsafe HTML');}
  }
  const messages=new Node();
  const root={createElement:() => new Node(),getElementById:() => messages};
  const v=new ChatView(stub<Document>(root)),unsafe='<img src=x onerror=alert(1)>';
  v.render({turns:[{prompt:unsafe,reply:{text:unsafe,offers:[{id:'offer',label:unsafe,value:2}]}}],offers:[]},() => {});
  assert.equal(messages.children[0]!.textContent,unsafe);
  assert.equal(messages.children[1]!.children[0]!.textContent,unsafe);
  assert.equal(messages.children[1]!.children[1]!.children[0]!.textContent,unsafe);
});

test('lab chat opens a session only when a question is asked, not on load', async () => {
  const calls: string[]=[],v=view();
  const api={session:async (p: string) => { calls.push('session:'+p); return {session_token:'t',turns:[],offers:[],mode:'local'}; },
    ask:async () => { calls.push('ask'); }, history:async () => ({turns:[],offers:[],mode:'local'})};
  const chat=controller(api,v);chat.profile='chelsea-analytical';
  await chat.updateMatch({match_id:'m1'});
  assert.deepEqual(calls,[]);
  assert.equal(chat.token,null);
  await chat.send('How many corners?');
  assert.deepEqual(calls,['session:chelsea-analytical','ask']);
});

test('without a model the lab chat says answers are unavailable and never opens a session', async () => {
  const calls: string[]=[],v=view();
  const chat=controller({session:async () => { calls.push('session'); return {}; }},v);
  chat.unavailable=true;
  await chat.updateMatch({match_id:'m1'});
  await chat.send('How many corners?');
  assert.deepEqual(calls,[]);
  assert.deepEqual(v.statuses.at(-1),['Answers unavailable · no model is configured',true]);
});
