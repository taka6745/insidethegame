# Engineering icons

852 editable Excalidraw library items, collected 17 October 2026.

| Pack | Items | Includes |
| --- | ---: | --- |
| Azure | 620 | Compute, containers, storage, databases, networking, AI and Foundry |
| Fabric and data | 135 | Pipelines, tables, files, Python, GraphQL, data agents and databases |
| Developer | 31 | Python, Docker, Kubernetes, Kafka, React and developer tools |
| Software | 18 | Servers, caches, databases, proxies and queues |
| Architecture | 48 | Users, events, messages, networks, documents and flow symbols |

Open **Library** in the local canvas. Project-relevant icons appear first.
The combined `engineering.excalidrawlib` also imports into hosted Excalidraw.
`catalog.json` maps names to library IDs for AI-assisted diagram creation.
Individual packs remain unchanged; `sources.json` records URLs and hashes.

Sources: [Microsoft conversions](https://github.com/amattas/microsoft-excalidraw),
[Excalidraw community libraries](https://github.com/excalidraw/excalidraw-libraries).
Azure is a community conversion of Microsoft artwork, not an official Excalidraw pack;
upstream does not include a standalone licence. Other packs come from the MIT-licensed
Excalidraw library repository; see `EXCALIDRAW-LIBRARIES-LICENSE`. Product trademarks
remain with their owners.

The local canvas uses `library-adapter.mjs` to load the built-in library from disk,
while retaining browser-specific additions and removals without filling localStorage.
After reinstalling the toolkit, run `python3 install-local.py <toolkit-package-directory>`
to restore this integration. The installer checks its bundle hook before changing it.
