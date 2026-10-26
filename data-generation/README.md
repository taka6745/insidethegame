# Data generation

Synthetic football, rendered with Google Research Football and streamed as an external provider would: events into Event Hubs, played video over HLS. Teams are fictional; every recording and message is labelled synthetic. None is a real fixture or Stats Perform data.

![Recordings become live events and played video](architecture.svg)

| Part | Owns |
| --- | --- |
| [Renderer](grf_demo/) | Scripted matches, aligned events/video and recorded provenance |
| [Recordings](recordings/) | Synthetic fixtures with aligned video and events |
| [Feed](feed/) | Runs, event publication, HLS, its own Postgres and purge tombstones |
| [Infrastructure](infra/) | Internal feed app, PostgreSQL and Blob Storage |

## Run it

From the root, use `ACCEPT_EULA=Y ./dev up backend` after consenting to the emulator licences ([local setup](../local/README.md#run-it)). `./dev logs feed` shows feed activity.

From `data-generation/`:

```sh
pip install -r feed/requirements-test.txt
python -m pytest -q
```

Set `FEED_TEST_DATABASE_URL` for real Postgres tests and `FEED_TEST_BLOB_CONNECTION_STRING` for Azurite tests. Rendering checks need GRF and OpenCV. To create footage, use [prepare-grf-source.sh](prepare-grf-source.sh) then [generate-grf.sh](generate-grf.sh); native GRF, NumPy, OpenCV and FFmpeg are required. Keep generated media in ignored `.local/`.

## Event contract

[local/README.md Contracts §1–2](../local/README.md#1-identity-and-snapshots) defines identity and ordering; [§6–7](../local/README.md#6-live-media-hls) defines HLS and feed control. [Telemetry rules](grf_demo/telemetry.py) derive events from contacts, referee decisions and tracking; [Opta conversion](grf_demo/opta.py) maps types and qualifiers.

- Each run gets a fresh `matchId`; consumers deduplicate at-least-once delivery.
- Events resolve before publication; an HLS segment appears only after its end passes the run clock.
- Purge writes a permanent tombstone. A restart resumes saved progress.
- Only the feed reads recordings and original media; downstream services use Event Hubs and HLS.

## Decisions and limits

Scripted tactics create multi-minute patterns; simulated football is not statistically equivalent to real football. No substitutions, injuries, VAR or xG. New fixtures need roster and league entries plus a recording.

## Provenance

[Google Research Football, pinned source](https://github.com/google-research/football/tree/3d9e754720a95621bba6475c4d3b0d56fe919014): Google LLC, Apache-2.0; Gameplay Football engine, Unlicense. [Local patches](docs/grf/) add telemetry and rendering. Those licences grant no rights to real match footage or team branding.
