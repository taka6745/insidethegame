import test from 'node:test';
import assert from 'node:assert/strict';
import { ChatController } from '../lab/chat-controller.js';
import { ChatView } from '../lab/chat-view.js';
import { ChatApi } from '../lab/chat-api.js';

const storage = () => { const values = new Map(); return { getItem:k => values.get(k), setItem:(k,v) => values.set(k,v) }; };
const deferred = () => { let resolve; const promise = new Promise(r => { resolve=r; }); return { promise, resolve }; };
const view = () => ({ renders:[], statuses:[], render(s) { this.renders.push(s); }, status(...s) { this.statuses.push(s); } });

test('refresh of pending question polls saved completion', async () => {
  const v=view(), api={history:async () => ({turns:[{status:'complete',reply:{text:'4 shots'}}],mode:'fixture'})};
  const chat=new ChatController(api,v,storage());
  chat.runId='run';chat.token='token';chat.session={turns:[{status:'pending'}]};
  await chat.updateRun({run_id:'run'});
  assert.equal(v.renders.at(-1).turns[0].reply.text,'4 shots');
  assert.equal(v.statuses.at(-1)[1],false);
});

test('late response cannot replace a new match conversation', async () => {
  const pending=deferred(),v=view();
  const chat=new ChatController({ask:() => pending.promise,history:async () => ({turns:[],mode:'fixture'})},v,storage());
  chat.token='old';chat.session={turns:[]};
  const sending=chat.send('How is it going?');
  chat.generation++;chat.runId='new';
  pending.resolve({});await sending;
  assert.equal(v.renders.length,1); // only the optimistic old message, no late reply
});

test('session takeover stops polling until explicit reconnect', async () => {
  const v=view(),chat=new ChatController({history:async () => { throw Object.assign(new Error('Taken over'),{code:'session_replaced'}); }},v,storage());
  chat.token='old';await chat.pollHistory();
  assert.equal(chat.token,null);
  assert.match(v.statuses.at(-1)[0],/Reconnect/);
});

test('failed send retries same prompt using same idempotency ID', async () => {
  const calls=[],v=view();
  const api={ask:async (...args) => { calls.push(args);throw new Error('Network'); }};
  const chat=new ChatController(api,v,storage());chat.token='t';chat.session={turns:[]};
  await chat.send('How many corners?');await chat.send('How many corners?');
  assert.equal(calls[0][2],calls[1][2]);
});

test('track button sends only the offer ID then refreshes state', async () => {
  const calls=[],v=view();
  const chat=new ChatController({track:async (...args) => calls.push(args),history:async () => ({turns:[],mode:'fixture'})},v,storage());
  chat.token='t';await chat.track('offer');
  assert.deepEqual(calls,[['t','offer']]);
});

test('chat API carries request UUID and no client-generated rule on Track', async () => {
  const api=new ChatApi();const calls=[];
  api.request=async (...args) => calls.push(args);
  await api.ask('token','headers','uuid');await api.track('token','offer');
  assert.deepEqual(calls,[['/chat/token/messages',{prompt:'headers',request_id:'uuid'}],['/chat/token/offers/offer/track',{}]]);
});

test('question view treats model text and offer labels as text, not markup', () => {
  class Node {
    constructor(){this.children=[];this.textContent='';this.listeners={};}
    append(...children){this.children.push(...children);}
    replaceChildren(...children){this.children=children;}
    addEventListener(name,fn){this.listeners[name]=fn;}
    set innerHTML(value){throw new Error('Unsafe HTML');}
  }
  const messages=new Node();
  const root={createElement:() => new Node(),getElementById:() => messages};
  const v=new ChatView(root),unsafe='<img src=x onerror=alert(1)>';
  v.render({turns:[{prompt:unsafe,reply:{text:unsafe,offers:[{id:'offer',label:unsafe,value:2}]}}],offers:[]},() => {});
  assert.equal(messages.children[0].textContent,unsafe);
  assert.equal(messages.children[1].children[0].textContent,unsafe);
  assert.equal(messages.children[1].children[1].children[0].textContent,unsafe);
});
