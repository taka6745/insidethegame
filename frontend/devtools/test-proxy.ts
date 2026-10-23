// Opt-in Docker check: render the shipped entrypoint template and validate nginx.
// Build first: docker build -t itg-frontend-proxy-test frontend; run: node frontend/tools/test-proxy.ts
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';

const image = process.argv[2] || 'itg-frontend-proxy-test';
for (const settings of [
  {backend: 'backend:8000', resolver: '127.0.0.11', media: 'feed:8000', admin: '0', env: []},
  {backend: 'backend.internal.example:80', resolver: '10.0.0.10', media: 'media.internal.example:80', admin: '1', env: [
    '-e', 'BACKEND_UPSTREAM=backend.internal.example:80',
    '-e', 'NGINX_RESOLVER=10.0.0.10',
    '-e', 'MEDIA_ORIGIN=media.internal.example:80',
    '-e', 'ENABLE_DEV_ADMIN=1',
  ]},
]) {
  const config = execFileSync('docker', [
    'run', '--rm', '--network', 'none', ...settings.env, image, 'nginx', '-T',
  ], {encoding: 'utf8', timeout: 60000});
  assert.ok(config.includes(`server ${settings.backend} resolve;`));
  assert.ok(config.includes(`resolver ${settings.resolver} valid=5s ipv6=off;`));
  assert.ok(config.includes(`proxy_set_header Host ${settings.backend};`));
  assert.ok(config.includes('add_header Cache-Control $cache_policy always;'));
  assert.ok(config.includes('proxy_set_header X-Forwarded-Host $host;'));
  assert.ok(config.includes('proxy_set_header Connection $connection_upgrade;'));
  assert.ok(config.includes('map $http_upgrade $connection_upgrade'));
  assert.ok(config.includes(`server ${settings.media} resolve;`));
  assert.ok(config.includes(`map "${settings.admin}" $dev_admin`));
  assert.ok(config.includes('server etl-stream:8000 resolve;'));
  assert.ok(config.includes('server narrative-live:8000 resolve;'));
  assert.ok(!/\$\{[A-Z_]+\}/.test(config), 'every deployment input is substituted');
}
// Azure: the environment's DNS from resolv.conf, and basic auth on the developer consoles only.
const azure = execFileSync('docker', [
  'run', '--rm', '--network', 'none', '-e', 'NGINX_RESOLVER=auto', '-e', 'ENABLE_DEV_ADMIN=1',
  '-e', 'DEV_ADMIN_PASSWORD=test-only', '-e', 'ETL_ADMIN_TOKEN=t-etl', '-e', 'ENGINE_ADMIN_TOKEN=t-engine', image, 'nginx', '-T',
], {encoding: 'utf8', timeout: 60000});
assert.ok(!azure.includes('resolver auto'), 'auto resolves to a nameserver');
assert.equal(azure.match(/include \/etc\/nginx\/dev-admin-auth\.conf;/g)?.length, 8);
assert.ok(azure.includes('auth_basic "InsideTheGame developer consoles";'));
assert.ok(!azure.includes('test-only'), 'the password never appears in the rendered config');
// Each owner's purge gets its bearer token from nginx, replacing the browser's basic-auth header.
assert.ok(azure.includes('proxy_set_header Authorization "Bearer t-etl";'));
assert.ok(azure.includes('proxy_set_header Authorization "Bearer t-engine";'));
const local = execFileSync('docker', ['run', '--rm', '--network', 'none', image, 'nginx', '-T'], {encoding: 'utf8', timeout: 60000});
assert.ok(!local.includes('auth_basic "'), 'no auth without DEV_ADMIN_PASSWORD');
// Locally no owner has a token: the purge, lab, config and feed routes all drop the browser's header.
assert.equal(local.match(/proxy_set_header Authorization "";/g)?.length, 6, 'no token locally; header dropped');
assert.equal(azure.match(/proxy_set_header Authorization "";/g)?.length, 4, 'basic auth never reaches an upstream');
assert.equal(local.match(/if \(\$dev_admin != "1"\) \{ return 404; \}/g)?.length, 8, 'every developer route is gated');
console.log('Default and configured proxy templates passed nginx validation.');
