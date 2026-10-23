# tools/

> **In short:** the three scripts the image uses at build and start time. Developer checks live in [`devtools/`](devtools.md).

| File | Used by | Does |
| --- | --- | --- |
| `build.sh` | `Dockerfile` | Copies `dist/match/` and `dist/shared/` under one content fingerprint (`/app/{hash}/`), rewrites `index.html` to it and links `app/current` for old tabs |
| `vendor.sh` | `npm run build` | Copies the pinned hls.js light ES module and licence into `dist/match/vendor/` |
| `nginx-setup.envsh` | nginx entrypoint | Resolves `NGINX_RESOLVER=auto`, writes the developer-console basic-auth include (empty without `DEV_ADMIN_PASSWORD`) and the owners' purge bearer headers |

`tests/build.test.ts` covers the fingerprint and fallback.
