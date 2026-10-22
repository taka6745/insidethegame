"""`./dev azure up|down|status|plan [--yes]`: the whole stack on Azure, from and back to nothing.

Runs on the host with the standard library only. Terraform, the Azure CLI and sqlcmd run in the
toolbox image (Dockerfile here) with the developer's `az login`; images are built here with Docker.
State: .local/terraform/<stack>/terraform.tfstate (git-ignored). Secrets are never printed.
Runbook and costs: terraform/runbook.md.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STATE = REPO / ".local" / "terraform"
TOOLS = "itg-azure-tools"
# Apply order; destroy runs in reverse.
STACKS = {"etl": "etl/infra", "narrative": "narrative-engine/infra", "feed": "data-generation/infra", "app": "terraform"}
GROUPS = {"etl": "rg-itg-etl-dev", "narrative": "rg-itg-narrative-dev", "feed": "rg-itg-feed-dev", "app": "itgdemo-rg"}
# The spend guard (budget + automatic stop): applied first by `up`, kept by `down` (it costs nothing idle).
GUARD = "terraform/guard"
PREFIX = "itgdemo"  # terraform/ var.prefix default
WINDOW_SECONDS = 60  # the feed plays in real time: one Stream Analytics window per match minute
# Rough monthly cost while running (USD, Australia East list prices, before free grants).
COST = {
    "Microsoft.App/containerApps": 0, "Microsoft.EventHub/namespaces": 25, "Microsoft.ServiceBus/namespaces": 10,
    "Microsoft.StreamAnalytics/streamingjobs": 85, "Microsoft.Sql/servers/databases": 0,
    "Microsoft.DBforPostgreSQL/flexibleServers": 19, "Microsoft.ContainerRegistry/registries": 5,
    "Microsoft.DocumentDB/databaseAccounts": 1, "Microsoft.Storage/storageAccounts": 3,
    "Microsoft.CognitiveServices/accounts": 5, "Microsoft.OperationalInsights/workspaces": 3,
    "Microsoft.KeyVault/vaults": 0,
}
TAG_FILE = STATE / "image-tag.txt"  # the images of the last complete `up`
APP_COST = {"0.25": 9, "0.5": 39}  # per always-on replica at 0.25 / 0.5 vCPU; scale-to-zero apps ~0


def say(message):
    print(f"\033[1m== {message}\033[0m", flush=True)


def run(args, *, capture=False, env=None, input=None, check=True):
    result = subprocess.run(args, cwd=REPO, text=True, input=input, env={**os.environ, **(env or {})},
                            stdout=subprocess.PIPE if capture else None)
    if check and result.returncode:
        raise SystemExit(f"Failed ({result.returncode}): {args[0]} {' '.join(a for a in args[1:4])} …")
    return result.stdout if capture else result.returncode


def tool(args, *, workdir="/repo", env=None, capture=False, check=True):
    """Runs a command in the toolbox. env values are passed by name, never on the command line."""
    env = env or {}
    flags = [f for name in env for f in ("-e", name)]
    return run(["docker", "run", "--rm", "-i", "-v", f"{REPO}:/repo", "-v", f"{Path.home() / '.azure'}:/root/.azure",
                "-w", workdir, *flags, TOOLS, *args], env=env, capture=capture, check=check)


def az(*args, env=None, check=True):
    out = tool(["az", *args, "-o", "json"], env=env, capture=True, check=check)
    return json.loads(out) if out and out.strip() else None


class Stack:
    def __init__(self, name, settings):
        self.name, self.dir, self.settings = name, STACKS.get(name, GUARD), settings
        self.state = STATE / name / "terraform.tfstate"

    def tf(self, *args, capture=False):
        return tool(["terraform", *args], workdir=f"/repo/{self.dir}", capture=capture,
                    env={"TF_DATA_DIR": f"/repo/.local/terraform/{self.name}/.terraform"})

    def init(self):
        (STATE / self.name).mkdir(parents=True, exist_ok=True)
        self.tf("init", "-lockfile=readonly", "-reconfigure",
                f"-backend-config=path=/repo/.local/terraform/{self.name}/terraform.tfstate", capture=True)

    def variables(self, extra=None, upstream=None):
        s, upstream = self.settings, upstream or {}
        values = {"subscription_id": s["subscription"]}
        if self.name in ("etl", "narrative", "feed", "app"):
            values["demo_seeds"] = "false" if s.get("release") else "true"  # the judge build has demo seeds
        if self.name == "guard":
            values["alert_email"] = s["email"]
            values["budget_start"] = time.strftime("%Y-%m-01T00:00:00Z", time.gmtime())
            return [f"-var={k}={v}" for k, v in values.items()]
        if self.name in ("etl", "narrative"):
            values["budget_emails"] = json.dumps([s["email"]])
            values["budget_start"] = time.strftime("%Y-%m-01T00:00:00Z", time.gmtime())  # Not in the past.
        if self.name == "etl":
            values["window_seconds"] = WINDOW_SECONDS
        for other in {"etl": [], "narrative": ["etl"], "feed": ["etl"], "app": ["etl", "narrative", "feed"]}[self.name]:
            values[f"{other}_state_path"] = upstream.get(other) or f"/repo/.local/terraform/{other}/terraform.tfstate"
        values.update(extra or {})
        return [f"-var={k}={v}" for k, v in values.items()]

    def apply(self, **extra):
        say(f"terraform apply {self.dir}")
        self.tf("apply", "-auto-approve", *self.variables(extra))

    def plan(self, upstream):
        say(f"terraform plan {self.dir}")
        self.tf("plan", "-lock=false", *self.variables(upstream=upstream))

    def destroy(self):
        if not self.state.exists() or not json.loads(self.state.read_text()).get("resources"):
            print(f"{self.dir}: nothing in state")
            return
        say(f"terraform destroy {self.dir}")
        self.tf("destroy", "-auto-approve", *self.variables())

    def outputs(self):
        return {k: v["value"] for k, v in json.loads(self.tf("output", "-json", capture=True)).items()}


def etl_devtools(*args, check=True):
    """`python -m devtools ...` in etl/ against the ETL stack's state (Stream Analytics, SQL setup)."""
    return tool(["python3", "-m", "devtools", *args], workdir="/repo/etl", check=check,
                env={"TF_DATA_DIR": "/repo/.local/terraform/etl/.terraform"})


def confirm(question, yes):
    if yes:
        return
    if input(f"{question} [y/N] ").strip().lower() not in ("y", "yes"):
        raise SystemExit("Cancelled.")


def account():
    info = az("account", "show", check=False)
    if not info:
        raise SystemExit("Run `az login` first (the toolbox uses your ~/.azure).")
    return {"subscription": info["id"], "email": info["user"]["name"], "name": info["name"]}


def build_tools():
    run(["docker", "build", "-q", "-t", TOOLS, str(REPO / "terraform" / "azure")], capture=True)


def registry_login(registry):
    token = tool(["az", "acr", "login", "-n", registry.split(".")[0], "--expose-token", "--query", "accessToken",
                  "-o", "tsv"], capture=True).strip()
    run(["docker", "login", registry, "-u", "00000000-0000-0000-0000-000000000000", "--password-stdin"],
        input=token, capture=True)


IMAGES = {  # name: (context, extra build args)
    "etl-stream": ("etl", ["--target", "stream"]),
    "feed": ("data-generation", ["-f", "data-generation/feed/Dockerfile", "--target", "runtime"]),
    "user-backend": ("user-backend", ["--target", "runtime"]),
    "frontend": ("frontend", []),
    "narrative-engine": ("narrative-engine", []),
    "demo-control": ("local", ["-f", "local/demo-control.Dockerfile"]),  # on user-backend; BASE added in push
}


def push(registry, names, tag):
    registry_login(registry)
    for name in names:
        context, extra = IMAGES[name]
        if name == "demo-control":
            extra = [*extra, "--build-arg", f"BASE={registry}/user-backend:{tag}"]
        say(f"build and push {name}:{tag} (linux/amd64)")
        run(["docker", "buildx", "build", "--platform", "linux/amd64", "--provenance=false", *extra,
             "-t", f"{registry}/{name}:{tag}", "--push", context])


def restart_app(resource_group, app, subscription):
    """Restarts an app's latest revision (DAB reads its schema only at start)."""
    base = (f"https://management.azure.com/subscriptions/{subscription}/resourceGroups/{resource_group}"
            f"/providers/Microsoft.App/containerApps/{app}")
    revision = az("rest", "--method", "get", "--url", f"{base}?api-version=2024-03-01",
                  "--query", "properties.latestRevisionName")
    az("rest", "--method", "post", "--url", f"{base}/revisions/{revision}/restart?api-version=2024-03-01")


MEDIA = json.loads((REPO / "terraform" / "azure" / "media.json").read_text())


def media_source(hls):
    """The main fixture uploads at full quality; the others are re-encoded once (encode_media.sh, host ffmpeg)."""
    fixture = hls.parent.name.removeprefix("grf-demo-").removesuffix("-90")
    if fixture in MEDIA["full_quality"]:
        return fixture, hls
    low = hls.parent.with_name(hls.parent.name + "-low") / "hls"
    q = MEDIA["secondary"]
    run([str(REPO / "terraform" / "azure" / "encode_media.sh"), str(hls), str(low),
         q["video_bitrate"], q["maxrate"], q["bufsize"]])
    return fixture, low


def seed_feed(feed):
    """Recordings and packaged HLS into the feed's storage with azcopy (many files at once; unchanged ones skip).
    A fixture's playlist goes last."""
    account_name = feed["storage_account"]
    key = tool(["az", "storage", "account", "keys", "list", "-n", account_name, "--query", "[0].value", "-o", "tsv"],
               capture=True).strip()
    env = {"AZURE_STORAGE_ACCOUNT": account_name, "AZURE_STORAGE_KEY": key}
    for path in sorted((REPO / "data-generation" / "recordings").glob("*.json")):
        if ".opta-" not in path.name:
            say(f"upload recording {path.name}")
            tool(["az", "storage", "blob", "upload", "--overwrite", "-c", "recordings", "-n", path.name,
                  "-f", f"/repo/{path.relative_to(REPO)}", "--only-show-errors"], env=env, capture=True)
    expiry = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(time.time() + 6 * 3600))
    sas = tool(["az", "storage", "container", "generate-sas", "-n", "media", "--permissions", "acwlr",
                "--expiry", expiry, "--https-only", "-o", "tsv"], env=env, capture=True).strip()
    base = f"https://{account_name}.blob.core.windows.net/media"
    for hls in sorted((REPO / ".local").glob("grf-demo-*-90/hls")):
        if not (hls / "match.m3u8").is_file():
            continue
        fixture, source = media_source(hls)
        local = sum(1 for _ in source.glob("*.ts"))
        say(f"upload media {fixture} ({local} segments, {'full' if source == hls else 'secondary'} quality)")
        started = time.time()
        # The SAS goes by environment, never on a command line.
        urls = {"SRC": f"/repo/{source.relative_to(REPO)}", "DEST": f"{base}/{fixture}/hls?{sas}",
                "PLAYLIST": f"{base}/{fixture}/hls/match.m3u8?{sas}"}
        tool(["sh", "-ec", 'azcopy sync "$SRC" "$DEST" --exclude-pattern "*.m3u8" --delete-destination false '
              '--log-level ERROR --output-level quiet; azcopy copy "$SRC/match.m3u8" "$PLAYLIST" '
              '--log-level ERROR --output-level quiet'], env=urls, capture=True)
        remote = int(tool(["az", "storage", "blob", "list", "-c", "media", "--prefix", f"{fixture}/hls/",
                           "--num-results", "*", "--query", "length([?ends_with(name, '.ts')])", "-o", "tsv"],
                          env=env, capture=True).strip())
        print(f"media {fixture}: {remote}/{local} segments in Azure ({time.time() - started:.0f} s)")
        if remote < local:
            raise SystemExit(f"media {fixture}: only {remote} of {local} segments uploaded")


def up(settings, yes):
    confirm(f"Deploy InsideTheGame to subscription '{settings['name']}'? It bills until `./dev azure down`.", yes)
    tag = time.strftime("v%Y%m%d%H%M%S")
    # A rerun (e.g. after a failure) keeps the apps of the last complete up until the new images exist,
    # instead of destroying and recreating them (a new identity would lose its database grants).
    previous = TAG_FILE.read_text().strip() if TAG_FILE.exists() else None
    guard = Stack("guard", settings)  # budgets, last resort and the Stream Analytics schedule, before anything bills
    guard.init()
    guard.apply()
    schedule = {f"stream_{k}_action_group_id": v for k, v in
                ((k, guard.outputs()[f"stream_{k}_action_group_id"]) for k in ("start", "stop"))}
    stacks = {name: Stack(name, settings) for name in STACKS}
    for stack in stacks.values():
        stack.init()
    stop_stream_jobs(leftovers()[0])  # a rerun: query and migration changes need the job stopped; started last

    etl = stacks["etl"]
    etl.apply(**schedule, **({"admin_image_tag": previous} if previous else {}))
    out = etl.outputs()
    # Schema before the new SPADL post-processor and purge API start (they also retry until it exists).
    say("ETL azure-setup: migrations, Azure triggers")
    etl_devtools("azure-setup")
    backend_url = f"http://{PREFIX}-backend.internal.{out['container_app_domain']}"
    push(out["registry_login_server"], ["etl-stream", "feed", "user-backend", "demo-control", "frontend"], tag)
    etl.apply(admin_image_tag=tag, **schedule)
    say("ETL azure-setup: identity grants for the new apps")
    etl_devtools("azure-setup")
    restart_app(out["resource_group"], out["dab_app_name"], settings["subscription"])

    narrative = stacks["narrative"]
    narrative.apply(**({"engine_image_tag": previous, "user_backend_url": backend_url} if previous else {}))
    registry = narrative.outputs()["registry_name"] + ".azurecr.io"
    push(registry, ["narrative-engine"], tag)
    narrative.apply(engine_image_tag=tag, user_backend_url=backend_url)

    feed = stacks["feed"]
    feed.apply(**({"image_tag": previous} if previous else {}))
    seed_feed(feed.outputs())
    feed.apply(image_tag=tag)

    app = stacks["app"]
    app.apply(image_tag=tag)
    result = app.outputs()
    password = STATE / "dev-admin-password.txt"
    if result.get("dev_admin_password"):
        password.touch(mode=0o600)
        password.chmod(0o600)  # before the secret is written
        password.write_text(result["dev_admin_password"] + "\n")

    say("Stream Analytics: start (bills while running)")
    etl_devtools("asa", "start")  # a no-op when already running
    TAG_FILE.write_text(tag + "\n")
    say("Up")
    print(f"Viewer:     {result['public_url']}")
    print(f"Developer:  {result['public_url']}/dev/  (user `dev`, password in {password.relative_to(REPO)})")
    print("Start a match from /dev/ (Matches). Stop everything with `./dev azure down`.")


PROJECT_TAGS = ("insidethegame", "InsideTheGame")


def leftovers():
    """Our resource groups (by name AND project tag, in apply order) and resources carrying our tag."""
    tags = {g["name"]: (g.get("tags") or {}).get("project") for g in az("group", "list") or []}
    foreign = [g for g in GROUPS.values() if g in tags and tags[g] not in PROJECT_TAGS]
    if foreign:
        raise SystemExit(f"Resource group(s) {foreign} exist without our project tag; not touching them.")
    mine = [g for g in GROUPS.values() if g in tags]
    tagged = az("resource", "list", "--query",
                "[?tags.project=='insidethegame' || tags.project=='InsideTheGame'].{name:name,type:type}") or []
    return mine, tagged


def stop_stream_jobs(groups):
    """Stops every Stream Analytics job in our groups (it bills while running), with or without state."""
    for group in groups:
        for job in az("resource", "list", "-g", group, "--resource-type", "Microsoft.StreamAnalytics/streamingjobs",
                      "--query", "[].id") or []:
            say(f"stop Stream Analytics {job.rsplit('/', 1)[1]}")
            az("rest", "--method", "post", "--url", f"https://management.azure.com{job}/stop?api-version=2020-03-01",
               check=False)


def in_our_group(resource_id):
    return "/resourceGroups/" in resource_id and \
        resource_id.split("/resourceGroups/")[1].split("/")[0].lower() in {g.lower() for g in GROUPS.values()}


def down(settings, yes):
    confirm(f"Destroy every InsideTheGame resource in '{settings['name']}'? Data is lost.", yes)
    groups, _ = leftovers()
    stop_stream_jobs(groups)
    failed = []
    for name in reversed(list(STACKS)):
        stack = Stack(name, settings)
        if stack.state.exists():
            try:
                stack.init()
                stack.destroy()
            except SystemExit as error:  # keep going: the resource-group sweep below removes the rest
                print(f"{stack.dir}: destroy failed ({error}); deleting its resource group instead")
                failed.append(name)
    groups, _ = leftovers()
    for group in reversed(groups):  # safety net; dependants (apps in the ETL's environment) first
        # A group's budgets outlive the group and would block the next up.
        for budget in az("rest", "--method", "get", "--url", f"https://management.azure.com/subscriptions/"
                         f"{settings['subscription']}/resourceGroups/{group}/providers/Microsoft.Consumption/budgets"
                         "?api-version=2023-05-01", "--query", "value[].id", check=False) or []:
            print(f"delete budget {budget.rsplit('/', 1)[1]}")
            az("rest", "--method", "delete", "--url", f"https://management.azure.com{budget}?api-version=2023-05-01",
               check=False)
        say(f"delete resource group {group}")
        tool(["az", "group", "delete", "-n", group, "--yes"])
    say("purge soft-deleted resources (ours only)")
    for deleted in az("cognitiveservices", "account", "list-deleted") or []:
        if in_our_group(deleted["id"]):
            location, group = deleted["location"], deleted["id"].split("/resourceGroups/")[1].split("/")[0]
            print(f"purge Foundry account {deleted['name']}")
            tool(["az", "cognitiveservices", "account", "purge", "-n", deleted["name"], "-g", group, "-l", location])
    for deleted in az("keyvault", "list-deleted", "--resource-type", "vault") or []:
        if in_our_group((deleted.get("properties") or {}).get("vaultId", "")):
            print(f"purge Key Vault {deleted['name']}")
            tool(["az", "keyvault", "purge", "-n", deleted["name"]])
    restorable = [a for a in az("cosmosdb", "restorable-database-account", "list", check=False) or []
                  if a.get("accountName", "").startswith("itg-") and a.get("deletionTime")]
    if restorable:
        print(f"{len(restorable)} deleted Cosmos DB account(s) in the free restore window (not billed; "
              "names are random per deploy, so nothing blocks the next up)")
    (STATE / "dev-admin-password.txt").unlink(missing_ok=True)
    TAG_FILE.unlink(missing_ok=True)
    for name in failed:  # its resources went with the group; stale state would make the next up fail
        (STATE / name / "terraform.tfstate").unlink(missing_ok=True)
    groups, tagged = leftovers()
    if groups or tagged:
        raise SystemExit(f"Still present: groups {groups}, resources {[r['name'] for r in tagged]}")
    say("Down: 0 InsideTheGame resources remain")


def status(settings):
    groups, _ = leftovers()
    if not groups:
        print("Nothing deployed.")
        return
    total = 0
    for group in groups:
        say(group)
        for r in az("resource", "list", "-g", group, "--query", "[].{name:name,type:type,id:id}") or []:
            state, cost = "", COST.get(r["type"])
            if r["type"] == "Microsoft.App/containerApps":
                app = az("resource", "show", "--ids", r["id"], "--query",
                         "{s:properties.runningStatus,min:properties.template.scale.minReplicas,"
                         "cpu:properties.template.containers[0].resources.cpu}")
                state = f"{app['s']}, min {app['min']} replica(s)"
                stopped = app["s"] == "Stopped"
                cost = 0 if stopped else APP_COST.get(str(app["cpu"]), 39) * (app["min"] or 0)
            elif r["type"] == "Microsoft.StreamAnalytics/streamingjobs":
                state = az("resource", "show", "--ids", r["id"], "--query", "properties.jobState")
                # Bills in every state but these (Starting, Running, Degraded, Scaling, Restarting, Stopping).
                cost = 0 if state in ("Created", "Stopped", "Failed", "Deleting") else cost
            elif r["type"] == "Microsoft.DBforPostgreSQL/flexibleServers":
                state = az("resource", "show", "--ids", r["id"], "--query", "properties.state")
                cost = cost if state == "Ready" else 4  # stopped: storage only
            total += cost or 0
            print(f"  {r['type'].split('/', 1)[1]:<38} {r['name']:<36} {str(state or ''):<28} "
                  f"{'' if cost is None else f'~${cost}/mo'}")
    print(f"\nEstimated while running as now: ~${total}/month (~${total / 30:.2f}/day) plus usage: "
          "model tokens, egress beyond 100 GB, SQL beyond the free offer. Details: terraform/runbook.md")


PLACEHOLDERS = {  # Outputs a not-yet-applied upstream would have; `plan` only.
    "etl": {"resource_group": "rg-itg-etl-dev", "graphql_url": "https://placeholder/graphql",
            "servicebus_namespace": "placeholder-sbns.servicebus.windows.net",
            "servicebus_namespace_id": "/subscriptions/{s}/resourceGroups/rg-itg-etl-dev/providers/Microsoft.ServiceBus/namespaces/placeholder-sbns",
            "container_app_environment_id": "/subscriptions/{s}/resourceGroups/rg-itg-etl-dev/providers/Microsoft.App/managedEnvironments/placeholder-cae",
            "container_app_domain": "placeholder.australiaeast.azurecontainerapps.io",
            "registry_login_server": "placeholder.azurecr.io", "registry_username": "placeholder",
            "registry_password": "placeholder", "servicebus_listen_connection_string": "Endpoint=sb://placeholder/",
            "eventhub_send_connection_string": "Endpoint=sb://placeholder/",
            "eventhub_listen_connection_string": "Endpoint=sb://placeholder/",
            "admin_host": "itg-etl-dev-admin.internal.placeholder", "admin_token": "placeholder"},
    "narrative": {"engine_app_name": "itg-narrative-dev-engine",
                  "foundry_account_id": "/subscriptions/{s}/resourceGroups/rg-itg-narrative-dev/providers/Microsoft.CognitiveServices/accounts/placeholder",
                  "foundry_endpoint": "https://placeholder.openai.azure.com/openai/v1", "foundry_key": "placeholder",
                  "narratives_listen_connection_string": "Endpoint=sb://placeholder/", "admin_token": "placeholder"},
    "feed": {"hls_origin_host": "itg-feed-dev-app.internal.placeholder",
             "hls_base_url": "http://itg-feed-dev-app.internal.placeholder/hls"},
}


def plan(settings):
    """Plans every stack against the subscription without applying. Upstream stacks that are not applied
    yet are stood in for by placeholder outputs, so downstream plans show what would be created."""
    placeholder_dir = STATE / "placeholders"
    placeholder_dir.mkdir(parents=True, exist_ok=True)
    guard = Stack("guard", settings)
    guard.init()
    guard.plan({})
    upstream = {}
    for name in STACKS:
        stack = Stack(name, settings)
        stack.init()
        stack.plan(upstream)
        if not stack.state.exists() and name in PLACEHOLDERS:
            outputs = {k: {"value": v.replace("{s}", settings["subscription"]), "type": "string"}
                       for k, v in PLACEHOLDERS[name].items()}
            (placeholder_dir / f"{name}.tfstate").write_text(json.dumps(
                {"version": 4, "terraform_version": "1.13.4", "serial": 1, "lineage": "placeholder",
                 "outputs": outputs, "resources": []}))
            upstream[name] = f"/repo/.local/terraform/placeholders/{name}.tfstate"
            print(f"(downstream plans use placeholder outputs for {name}: it is not applied)")


def main():
    parser = argparse.ArgumentParser(prog="./dev azure", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["up", "down", "status", "plan"])
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    parser.add_argument("--release", action="store_true", help="production release: no demo seed routes")
    args = parser.parse_args()
    build_tools()
    settings = {**account(), "release": args.release}
    if args.command == "up":
        up(settings, args.yes)
    elif args.command == "down":
        down(settings, args.yes)
    elif args.command == "status":
        status(settings)
    else:
        plan(settings)


if __name__ == "__main__":
    sys.exit(main())
