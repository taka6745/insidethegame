"""ETL developer commands.

    python -m devtools local-up                  start local SQL + DAB, apply migrations
    python -m devtools migrate [--azure SERVER]  apply sql/migrations (Azure uses your az login)
    python -m devtools load-local REPLAY.jsonl   insert what the cloud job would write for a replay
    python -m devtools verify REPLAY.jsonl       compare GraphQL results with the reference pipeline
    python -m devtools local-down [--wipe]
    python -m devtools azure-setup               after terraform apply: migrations + identity grants
    python -m devtools asa start|stop|status     Stream Analytics bills only while running
    python -m devtools check-notifications REPLAY.jsonl   peek Service Bus and compare with the reference
"""
import argparse
import json
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from reference import pipeline

ETL = Path(__file__).resolve().parents[1]
ENV_FILE = ETL / ".env"
DATABASE = "insidethegame"
LOCAL_GRAPHQL = "http://localhost:5000/graphql"


def local_password():
    if not ENV_FILE.exists():
        # SQL Server needs upper, lower and digits; token_urlsafe supplies them in practice, the suffix guarantees it.
        ENV_FILE.write_text(f"LOCAL_SA_PASSWORD={secrets.token_urlsafe(18)}Aa1\n")
    env = dict(line.split("=", 1) for line in ENV_FILE.read_text().splitlines() if "=" in line)
    return env["LOCAL_SA_PASSWORD"]


def sqlcmd_args(azure_server=None, database=DATABASE):
    if azure_server:
        return ["sqlcmd", "-S", f"tcp:{azure_server},1433", "-d", database,
                "--authentication-method", "ActiveDirectoryDefault"]
    return ["sqlcmd", "-S", "tcp:localhost,14330", "-U", "sa", "-P", local_password(), "-d", database, "-C"]


def sql(query, azure_server=None, database=DATABASE):
    result = subprocess.run([*sqlcmd_args(azure_server, database), "-b", "-h", "-1", "-W", "-Q",
                             f"SET NOCOUNT ON; {query}"], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"sqlcmd failed: {result.stdout}{result.stderr}")
    return result.stdout.strip()


def sql_file(path, azure_server=None):
    # -x: payload JSON is data, never sqlcmd $(variables)
    result = subprocess.run([*sqlcmd_args(azure_server), "-b", "-x", "-i", str(path)], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"{path.name} failed: {result.stdout}{result.stderr}")


def migrate(azure_server=None):
    sql("IF OBJECT_ID('dbo.schemaMigrations') IS NULL CREATE TABLE dbo.schemaMigrations "
        "(name nvarchar(200) PRIMARY KEY, appliedAt datetime2(3) NOT NULL DEFAULT sysutcdatetime())", azure_server)
    applied = set(sql("SELECT name FROM dbo.schemaMigrations", azure_server).splitlines())
    for path in sorted((ETL / "sql" / "migrations").glob("*.sql")):
        if path.name in applied:
            continue
        sql_file(path, azure_server)
        sql(f"INSERT dbo.schemaMigrations (name) VALUES ('{path.name}')", azure_server)
        print(f"applied {path.name}")
    print("migrations up to date")


def compose(*args):
    subprocess.run(["docker", "compose", "--env-file", str(ENV_FILE), *args], cwd=ETL, check=True)


def local_up():
    local_password()
    compose("up", "-d", "sql")
    for _ in range(60):
        probe = subprocess.run([*sqlcmd_args(database="master"), "-Q", "SELECT 1"], capture_output=True)
        if probe.returncode == 0:
            break
        time.sleep(2)
    else:
        raise SystemExit("SQL Server did not start; see `docker compose logs sql`")
    sql(f"IF DB_ID('{DATABASE}') IS NULL CREATE DATABASE {DATABASE}", database="master")
    migrate()
    compose("up", "-d", "dab")
    print(f"GraphQL: {LOCAL_GRAPHQL}")


def literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (int, float)):
        return repr(value)
    return "N'" + str(value).replace("'", "''") + "'"


def insert_statements(table, rows, batch=500):
    if not rows:
        return []
    columns = list(rows[0])
    statements = []
    for i in range(0, len(rows), batch):
        values = ",\n".join("(" + ", ".join(literal(r[c]) for c in columns) + ")" for r in rows[i:i + batch])
        statements.append(f"INSERT dbo.{table} ({', '.join(columns)}) VALUES\n{values};")
    return statements


def read_replay(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def load_local(replay, window):
    outputs = pipeline.stream_outputs(read_replay(replay), window)
    script = ETL / ".local" / "load-local.sql"
    script.parent.mkdir(exist_ok=True)
    statements = [s for table in ("matches", "rawEvents", "keyEvents", "minuteStats")
                  for s in insert_statements(table, outputs[table])]
    script.write_text("SET NOCOUNT ON;\n" + "\nGO\n".join(statements) + "\nGO\n", encoding="utf-8")
    sql_file(script)
    print({table: len(outputs[table]) for table in ("matches", "rawEvents", "keyEvents", "minuteStats")})
    # Stand-in for Service Bus until it is deployed, ordered as they would arrive.
    notifications = ETL / ".local" / "notifications.jsonl"
    ordered = sorted(outputs["notifications"], key=lambda n: pipeline.parse_time(n.get("windowEnd") or n["eventTime"]))
    notifications.write_text("".join(json.dumps(pipeline.notification_body(n)) + "\n" for n in ordered),
                             encoding="utf-8")
    print(f"wrote {len(ordered)} notifications to {notifications}")


def graphql(url, query, variables):
    request = urllib.request.Request(url, json.dumps({"query": query, "variables": variables}).encode(),
                                     {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:  # GraphQL validation errors arrive as HTTP 400
        body = json.load(error)
    if "errors" in body:
        raise SystemExit(json.dumps(body["errors"], indent=2))
    return body["data"]


def fetch_all(url, entity, fields, match_id):
    query = f"""query ($matchId: String!, $after: String) {{
      {entity}(filter: {{ matchId: {{ eq: $matchId }} }}, first: 1000, after: $after) {{
        items {{ {fields} }} hasNextPage endCursor }} }}"""
    items, after = [], None
    while True:
        page = graphql(url, query, {"matchId": match_id, "after": after})[entity]
        items += page["items"]
        if not page["hasNextPage"]:
            return items
        after = page["endCursor"]


def verify(replay, window, url):
    messages = read_replay(replay)
    match_id = messages[0]["matchId"]
    outputs = pipeline.stream_outputs(messages, window)
    expected = pipeline.stats_as_of(outputs["minuteStats"], outputs["matches"])
    columns = list(expected[0])
    actual = fetch_all(url, "matchStatsAsOfs", " ".join(columns), match_id)
    key = lambda r: (r["periodId"], r["timeMin"], r["contestantId"])
    actual_by_key = {key(r): r for r in actual}
    problems = []
    if len(actual) != len(expected):
        problems.append(f"matchStatsAsOf rows: expected {len(expected)}, got {len(actual)}")
    for e in expected:
        a = actual_by_key.get(key(e))
        if a is None:
            problems.append(f"missing {key(e)}")
            continue
        for c in columns:
            ev, av = e[c], a[c]
            if ev != av:
                problems.append(f"{key(e)} {c}: expected {ev}, got {av}")
    key_events = fetch_all(url, "keyEvents", "id keyType detail", match_id)
    expected_keys = sorted((k["id"], k["keyType"], k["detail"]) for k in outputs["keyEvents"])
    if sorted((k["id"], k["keyType"], k["detail"]) for k in key_events) != expected_keys:
        problems.append(f"keyEvents differ: expected {expected_keys}")
    raw = fetch_all(url, "rawEvents", "id", match_id)
    if len(raw) != len(outputs["rawEvents"]):
        problems.append(f"rawEvents: expected {len(outputs['rawEvents'])}, got {len(raw)}")
    final = [r for r in actual if key(r)[:2] == max(key(x)[:2] for x in actual)]
    print("final:", {r["position"]: r["goals"] for r in final}, f"| {len(actual)} stat rows, "
          f"{len(key_events)} key events, {len(raw)} raw events")
    if problems:
        print("\n".join(problems[:40]))
        raise SystemExit(f"{len(problems)} mismatches")
    print("verify: OK")


def terraform_outputs():
    result = subprocess.run(["terraform", "output", "-json"], cwd=ETL / "infra", capture_output=True, text=True, check=True)
    return {k: v["value"] for k, v in json.loads(result.stdout).items()}


def az(*args):
    return subprocess.run([shutil.which("az") or "az", *args], capture_output=True, text=True, check=True).stdout


def azure_setup():
    out = terraform_outputs()
    migrate(out["sql_server"])
    # Managed identities connect as database users named after their resource.
    for name, roles in ((out["stream_analytics_job"], ("db_datareader", "db_datawriter")),
                        (out["dab_identity_name"], ("db_datareader",))):
        grants = " ".join(f"ALTER ROLE {role} ADD MEMBER [{name}];" for role in roles)
        sql(f"IF USER_ID('{name}') IS NULL CREATE USER [{name}] FROM EXTERNAL PROVIDER; {grants}", out["sql_server"])
        print(f"granted {', '.join(roles)} to {name}")


def asa(action):
    out = terraform_outputs()
    job = (f"/subscriptions/{az('account', 'show', '--query', 'id', '-o', 'tsv').strip()}/resourceGroups/"
           f"{out['resource_group']}/providers/Microsoft.StreamAnalytics/streamingjobs/{out['stream_analytics_job']}")
    api = "?api-version=2020-03-01"
    if action == "start":
        az("rest", "--method", "post", "--url", f"https://management.azure.com{job}/start{api}",
           "--body", json.dumps({"outputStartMode": "JobStartTime"}))
    elif action == "stop":
        az("rest", "--method", "post", "--url", f"https://management.azure.com{job}/stop{api}")
    state = az("rest", "--method", "get", "--url", f"https://management.azure.com{job}{api}",
               "--query", "properties.jobState", "-o", "tsv").strip()
    print(f"{out['stream_analytics_job']}: {state}")


def check_notifications(replay, window, subscription="narrative-engine"):
    """Peek (without consuming) the subscription and compare messages for this replay's match."""
    from azure.servicebus import ServiceBusClient

    connection = subprocess.run(["terraform", "output", "-raw", "servicebus_listen_connection_string"],
                                cwd=ETL / "infra", capture_output=True, text=True, check=True).stdout
    messages = read_replay(replay)
    match_id = messages[0]["matchId"]
    expected = {pipeline.message_id_for(n): n for n in pipeline.stream_outputs(messages, window)["notifications"]}
    actual, sequence = {}, 0
    with ServiceBusClient.from_connection_string(connection) as client:
        with client.get_subscription_receiver("match-notifications", subscription) as receiver:
            while batch := receiver.peek_messages(max_message_count=250, sequence_number=sequence):
                for m in batch:
                    body = json.loads(b"".join(m.body))
                    if body.get("matchId") == match_id:
                        actual[m.message_id] = (body, (m.application_properties or {}).get(b"notificationType"))
                sequence = batch[-1].sequence_number + 1
    problems = [f"missing {i}" for i in expected if i not in actual]
    problems += [f"unexpected {i}" for i in actual if i not in expected]
    for i, (body, prop) in actual.items():
        if i not in expected:
            continue
        want = pipeline.notification_body(expected[i])
        if set(body) != set(pipeline.NOTIFICATION_KEYS) or prop != body["messageType"].encode():
            problems.append(f"{i}: keys {list(body)} / property {prop}")
        for k in pipeline.NOTIFICATION_KEYS:
            got, exp = body.get(k), want[k]
            if k in ("eventTime", "windowEnd") and got and exp:
                got, exp = pipeline.parse_time(got[:23] + "Z"), pipeline.parse_time(exp)
            if got != exp:
                problems.append(f"{i} {k}: expected {exp!r}, got {got!r}")
    kinds = {}
    for body, _ in actual.values():
        kinds[body["messageType"]] = kinds.get(body["messageType"], 0) + 1
    print(f"{len(actual)} messages for {match_id} (expected {len(expected)}): {kinds}")
    if problems:
        print("\n".join(problems[:40]))
        raise SystemExit(f"{len(problems)} notification problems")
    print("notifications: OK")


def main():
    parser = argparse.ArgumentParser(prog="python -m devtools", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("local-up")
    down = sub.add_parser("local-down")
    down.add_argument("--wipe", action="store_true", help="also delete the local database volume")
    m = sub.add_parser("migrate")
    m.add_argument("--azure", metavar="SERVER", help="Azure SQL server host name")
    sub.add_parser("azure-setup")
    a = sub.add_parser("asa")
    a.add_argument("action", choices=["start", "stop", "status"])
    for name in ("load-local", "verify", "check-notifications"):
        p = sub.add_parser(name)
        p.add_argument("replay", type=Path)
        p.add_argument("--window", type=int, default=6, help="tumbling window seconds (60 / replay speed)")
        if name == "verify":
            p.add_argument("--graphql", default=LOCAL_GRAPHQL)
    args = parser.parse_args()

    if args.command == "local-up":
        local_up()
    elif args.command == "local-down":
        compose("down", *(["-v"] if args.wipe else []))
    elif args.command == "migrate":
        migrate(args.azure)
    elif args.command == "azure-setup":
        azure_setup()
    elif args.command == "asa":
        asa(args.action)
    elif args.command == "check-notifications":
        check_notifications(args.replay, args.window)
    elif args.command == "load-local":
        load_local(args.replay, args.window)
    else:
        verify(args.replay, args.window, args.graphql)


if __name__ == "__main__":
    sys.exit(main())
