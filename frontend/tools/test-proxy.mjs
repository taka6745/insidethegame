// Opt-in Docker check: render the shipped entrypoint template and validate nginx.
// Build first: docker build -t itg-frontend-proxy-test frontend
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';

const image = process.argv[2] || 'itg-frontend-proxy-test';
for (const settings of [
  {backend: 'backend:8000', resolver: '127.0.0.11', env: []},
  {backend: 'backend.internal.example:80', resolver: '10.0.0.10', env: [
    '-e', 'BACKEND_UPSTREAM=backend.internal.example:80',
    '-e', 'NGINX_RESOLVER=10.0.0.10',
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
  assert.ok(!config.includes('${BACKEND_UPSTREAM}'));
  assert.ok(!config.includes('${NGINX_RESOLVER}'));
}
console.log('Default and configured proxy templates passed nginx validation.');
