"""Dev helpers for the Azure environment. Never prints secrets.

    python -m narrative_engine.devtools.azure env                          # write Azure settings into .env
    python -m narrative_engine.devtools.azure build --tag v1 [--local]     # build in ACR, or with local Docker and push
    python -m narrative_engine.devtools.azure check-narratives --match-id demo   # read the narrative-check subscription
    python -m narrative_engine.devtools.azure report --match-id demo       # summaries, compressions, narratives -> HTML
    python -m narrative_engine.devtools.azure send-presence --match-id demo --counts '{"home:casual": 2}' --minutes 20
"""
import argparse
import asyncio
import json
import os
import subprocess
from collections import Counter
from pathlib import Path

from narrative_engine.agents.llm import ENV_FILE, load_env

HERE = Path(__file__).resolve().parents[2]
INFRA, ETL_INFRA = HERE / "infra", HERE.parent / "etl" / "infra"


def output(chdir, name):
    return subprocess.run(["terraform", f"-chdir={chdir}", "output", "-raw", name], check=True, capture_output=True,
                          text=True).stdout.strip()


def write_env():
    settings = {
        "ETL_GRAPHQL_URL": output(ETL_INFRA, "graphql_url"),
        "SERVICEBUS_NOTIFICATIONS": output(ETL_INFRA, "servicebus_listen_connection_string"),
        "SERVICEBUS_NARRATIVES": output(INFRA, "narratives_send_connection_string"),
        "SERVICEBUS_NARRATIVES_LISTEN": output(INFRA, "narratives_listen_connection_string"),
        "SERVICEBUS_PRESENCE": output(INFRA, "presence_listen_connection_string"),
        "SERVICEBUS_PRESENCE_SEND": output(INFRA, "presence_send_connection_string"),
        "COSMOS_ENDPOINT": output(INFRA, "cosmos_endpoint"),
    }
    lines = [l for l in (ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else [])
             if l.split("=", 1)[0] not in settings]
    ENV_FILE.write_text("\n".join(lines + [f"{k}={v}" for k, v in settings.items()]) + "\n", encoding="utf-8")
    print(f"wrote {', '.join(settings)} to {ENV_FILE}")


def build(tag, local=False):
    """Copy only what the image needs into a temporary context, then build it: in ACR (ACR Tasks,
    not allowed on trial subscriptions) or with local Docker and push."""
    import shutil
    import tempfile

    registry = output(INFRA, "registry_name")
    with tempfile.TemporaryDirectory() as context:
        context = Path(context)
        for name in ("Dockerfile", ".dockerignore", "requirements.txt"):
            shutil.copy(HERE / name, context / name)
        shutil.copytree(HERE / "narrative_engine", context / "narrative_engine",
                        ignore=shutil.ignore_patterns("__pycache__"))
        print("context:", sorted(str(p.relative_to(context)) for p in context.rglob("*") if p.is_file()))
        az = shutil.which("az") or shutil.which("az.cmd")
        image = f"{registry}.azurecr.io/narrative-engine:{tag}"
        if local:
            subprocess.run([az, "acr", "login", "--name", registry], check=True)
            subprocess.run(["docker", "build", "--platform", "linux/amd64", "-t", image, str(context)], check=True)
            subprocess.run(["docker", "push", image], check=True)
        else:
            subprocess.run([az, "acr", "build", "--registry", registry, "--image", f"narrative-engine:{tag}",
                            str(context)], check=True)
    print(f"built {registry}.azurecr.io/narrative-engine:{tag}; deploy with "
          f"terraform -chdir=infra apply -var engine_image_tag={tag}")


async def check_narratives(match_id, wait):
    """Drain the narrative-check subscription; summarise this match's narratives."""
    from azure.servicebus.aio import ServiceBusClient

    load_env()
    found, other = [], 0
    async with ServiceBusClient.from_connection_string(os.environ["SERVICEBUS_NARRATIVES_LISTEN"]) as client:
        async with client.get_subscription_receiver("narratives", "narrative-check") as receiver:
            while batch := await receiver.receive_messages(max_message_count=100, max_wait_time=wait):
                for m in batch:
                    doc = json.loads(b"".join(m.body))
                    if doc["matchId"] == match_id:
                        found.append((m.message_id, m.application_properties, doc))
                    else:
                        other += 1
                    await receiver.complete_message(m)
    docs = [d for _, _, d in found]
    print(f"{len(found)} narratives for {match_id} ({other} for other matches)")
    print("steps:", dict(Counter(d["trigger"]["type"] for d in docs)))
    print("buckets:", dict(Counter(d["userType"] for d in docs)))
    print("message ids match narrative ids:", all(mid == d["id"] for mid, _, d in found))
    for d in sorted(docs, key=lambda d: d["seq"]):
        if d["userType"] == "neutral:casual":
            print(f"  {d['seq']:>2} {d['matchTime']['label']:>6} {d['trigger']['type']:<9} {d['text'][:110]}")


async def report(match_id, open_browser):
    """Write .local/report-<matchId>.html from Cosmos DB."""
    import webbrowser

    from narrative_engine.devtools.report import render
    from narrative_engine.store.cosmos import CosmosStore

    load_env()
    store = CosmosStore(os.environ["COSMOS_ENDPOINT"])
    try:
        blocks, narratives = await store.all_blocks(match_id), await store.narratives(match_id)
    finally:
        await store.aclose()
    if not blocks and not narratives:
        raise SystemExit(f"nothing stored for {match_id}")
    path = HERE / ".local" / f"report-{match_id}.html"
    path.parent.mkdir(exist_ok=True)
    path.write_text(render(match_id, blocks, narratives), encoding="utf-8")
    print(f"{len(blocks)} blocks, {len(narratives)} narratives -> {path}")
    if open_browser:
        webbrowser.open(path.as_uri())


async def send_presence(match_id, counts, minutes, every=60):
    """Act as the user backend: full-state presence now and every `every` seconds."""
    from datetime import datetime, timezone

    from azure.servicebus import ServiceBusMessage
    from azure.servicebus.aio import ServiceBusClient

    load_env()
    loop = asyncio.get_running_loop()
    end = loop.time() + minutes * 60
    async with ServiceBusClient.from_connection_string(os.environ["SERVICEBUS_PRESENCE_SEND"]) as client:
        async with client.get_topic_sender("presence") as sender:
            while loop.time() < end:
                body = {"matchId": match_id, "activeUserTypes": counts,
                        "sentAt": datetime.now(timezone.utc).isoformat()}
                await sender.send_messages(ServiceBusMessage(json.dumps(body), content_type="application/json"))
                print(f"presence sent {body['sentAt']}", flush=True)
                await asyncio.sleep(every)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("env")
    build_cmd = sub.add_parser("build")
    build_cmd.add_argument("--tag", required=True)
    build_cmd.add_argument("--local", action="store_true", help="local Docker build and push")
    check = sub.add_parser("check-narratives")
    check.add_argument("--match-id", required=True)
    check.add_argument("--wait", type=float, default=10)
    report_cmd = sub.add_parser("report")
    report_cmd.add_argument("--match-id", required=True)
    report_cmd.add_argument("--no-open", action="store_true", help="don't open it in the browser")
    presence = sub.add_parser("send-presence")
    presence.add_argument("--match-id", required=True)
    presence.add_argument("--counts", required=True, help='JSON, e.g. {"home:casual": 2}')
    presence.add_argument("--minutes", type=float, default=20)
    args = parser.parse_args()
    if args.command == "env":
        write_env()
    elif args.command == "build":
        build(args.tag, args.local)
    elif args.command == "report":
        asyncio.run(report(args.match_id, not args.no_open))
    elif args.command == "send-presence":
        asyncio.run(send_presence(args.match_id, json.loads(args.counts), args.minutes))
    else:
        asyncio.run(check_narratives(args.match_id, args.wait))


if __name__ == "__main__":
    main()
