#!/usr/bin/env python3
"""Export Innovation Studio projects using a saved browser 'Copy as cURL' request.

Usage: python3 fetch_projects.py request.txt --detail-curl-file details.txt
       --output-dir ./projects-export
No third-party packages required. The cURL command is parsed, never executed.
"""

import argparse
import copy
import csv
import json
import re
import shlex
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

ENDPOINT = "https://innovationstudio.microsoft.com/api/graphql/"


def ansi_unquote(match):
    """Decode shell $'...' quoting before passing the command to shlex."""
    value = match.group(1)
    escapes = {"a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b",
               "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v",
               "\\": "\\", "'": "'", '"': '"'}

    def decode(escape):
        code = escape.group(1)
        if code in escapes:
            return escapes[code]
        if code.startswith(("x", "u", "U")):
            return chr(int(code[1:], 16))
        if code[0] in "01234567":
            return chr(int(code, 8))
        return "\\" + code

    value = re.sub(r"\\(x[0-9a-fA-F]{1,2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|[0-7]{1,3}|.)",
                   decode, value, flags=re.S)
    return shlex.quote(value)


def read_request(path, operation="getProjectSearchInfiniteScroll"):
    command = path.read_text(encoding="utf-8")
    command = re.sub(r"\$'((?:\\.|[^'\\])*)'", ansi_unquote, command, flags=re.S)
    tokens = shlex.split(command.replace("\\\n", " "))
    headers, payload, url = {}, None, None
    keep_headers = {"accept", "authorization", "content-type", "origin", "referer",
                    "x-ms-locale", "cookie"}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"--url", "-H", "--header", "-b", "--cookie", "-d",
                     "--data", "--data-raw", "--data-binary"}:
            i += 1
            if i >= len(tokens):
                raise ValueError("Incomplete cURL option.")
            value = tokens[i]
            if token == "--url":
                url = value
            elif token in {"-H", "--header"}:
                name, separator, content = value.partition(":")
                if separator and name.lower() in keep_headers:
                    headers[name.lower()] = content.strip()
            elif token in {"-b", "--cookie"}:
                if "=" not in value:
                    raise ValueError("Use a copied Cookie value, not a cookie-file argument.")
                headers["cookie"] = value
            else:
                if value.startswith("@"):
                    raise ValueError("The cURL request must contain its JSON payload inline.")
                payload = json.loads(value)
        elif token.startswith("https://") and url is None:
            url = token
        i += 1
    if url != ENDPOINT:
        raise ValueError("Expected the Innovation Studio GraphQL endpoint; refusing another destination.")
    if not isinstance(payload, dict) or not isinstance(payload.get("variables"), dict):
        raise ValueError("No valid GraphQL JSON request found in the cURL file.")
    if payload.get("operationName") != operation:
        raise ValueError(f"Expected the {operation} request.")
    if not isinstance(payload.get("query"), str):
        raise ValueError("The request does not contain a GraphQL query.")
    headers["content-type"] = "application/json"
    return headers, payload


def fetch_graphql(headers, payload):
    # Disable redirects so copied authentication can never be sent to another host.
    from urllib.request import HTTPRedirectHandler, build_opener

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, response_headers, newurl):
            return None

    opener = build_opener(NoRedirect())
    for attempt in range(5):
        request = Request(ENDPOINT, data=json.dumps(payload).encode("utf-8"),
                          headers=headers, method="POST")
        delay = min(2 ** attempt, 30)
        try:
            with opener.open(request, timeout=45) as response:
                result = json.load(response)
        except HTTPError as error:
            if error.code in (401, 403):
                raise RuntimeError("Authentication failed. Copy a fresh cURL request from the browser.") from None
            if error.code != 429 and not 500 <= error.code < 600:
                raise RuntimeError(f"GraphQL request failed with HTTP {error.code}.") from None
            retry_after = error.headers.get("Retry-After", "")
            if retry_after.isdigit():
                delay = min(int(retry_after), 120)
            reason = f"HTTP {error.code}"
        except (URLError, TimeoutError, OSError):
            reason = "connection failure"
        except (ValueError, UnicodeError):
            raise RuntimeError("The server returned invalid JSON; copy a fresh browser request.") from None
        else:
            if not isinstance(result, dict):
                raise RuntimeError("Unexpected GraphQL response format.")
            if result.get("errors"):
                # Avoid printing response bodies, which can include account information.
                raise RuntimeError("GraphQL returned errors. Check that your copied session is current.")
            if not isinstance(result.get("data"), dict):
                raise RuntimeError("The response is missing GraphQL data.")
            return result["data"]
        if attempt == 4:
            raise RuntimeError(f"Request failed after five attempts ({reason}).")
        print(f"Retrying after {reason} in {delay}s…", file=sys.stderr)
        time.sleep(delay)


def fetch_page(headers, payload):
    search = fetch_graphql(headers, payload).get("projectSearch")
    if not isinstance(search, dict) or not isinstance(search.get("result"), list):
        raise RuntimeError("The response is missing data.projectSearch.result.")
    if not isinstance(search.get("pageInfo"), dict):
        raise RuntimeError("The response is missing pagination information.")
    return search


def collect_projects(headers, payload, page_size, delay):
    variables = payload["variables"]
    variables["after"] = None  # The supplied cURL starts midway through the list.
    variables["first"] = page_size
    variables["searchText"] = "*"
    variables["searchField"] = ""
    projects, seen_ids, seen_cursors = [], set(), set()
    page_number, total = 0, None
    while True:
        search = fetch_page(headers, payload)
        page_number += 1
        page_info = search["pageInfo"]
        total = page_info.get("totalRowCount")
        for project in search["result"]:
            if not isinstance(project, dict) or project.get("id") is None:
                raise RuntimeError("A project is missing its ID; export stopped.")
            project_id = str(project["id"])
            if project_id not in seen_ids:
                seen_ids.add(project_id)
                projects.append(project)
        print(f"Page {page_number}: {len(projects)} unique projects" +
              (f" / {total}" if total is not None else ""), file=sys.stderr)
        if page_info.get("hasNextPage") is False:
            break
        if page_info.get("hasNextPage") is not True:
            raise RuntimeError("Invalid hasNextPage value; cannot confirm a complete export.")
        cursor = page_info.get("endCursor")
        if cursor is None or cursor == "" or cursor in seen_cursors:
            raise RuntimeError("Pagination stopped advancing; export is incomplete.")
        if not search["result"]:
            raise RuntimeError("An empty page still claims more results; export is incomplete.")
        seen_cursors.add(cursor)
        variables["after"] = cursor
        time.sleep(delay)
    if total is not None and len(projects) != int(total):
        raise RuntimeError(f"Collected {len(projects)} unique projects, but the server reports {total}. "
                           "The list may have changed during export; run again.")
    return projects


def enrich_repositories(projects, headers, detail_payload, workers, delay):
    """Use the supplied detail query for each project, preserving list order."""
    fields = ["externalRepoUrl", "codeRepoUrl", "sourceCode", "linkRepoState", "adoRepoTitle"]

    def enrich(project):
        payload = copy.deepcopy(detail_payload)
        payload["variables"]["id"] = str(project["id"])
        payload["variables"]["hackathonId"] = str(project["hackathonId"])
        details = fetch_graphql(headers, payload).get("project")
        if not isinstance(details, dict) or str(details.get("id")) != str(project["id"]):
            raise RuntimeError(f"Missing or mismatched details for project {project['id']}.")
        if str(details.get("hackathonId")) != str(project["hackathonId"]):
            raise RuntimeError(f"Hackathon mismatch for project {project['id']}.")
        enriched = dict(project)
        enriched.update({field: details.get(field) for field in fields})
        urls = []
        for field in ("externalRepoUrl", "codeRepoUrl"):
            value = details.get(field)
            if isinstance(value, str) and value.strip() and value.strip() not in urls:
                urls.append(value.strip())
        enriched["repoUrl"] = urls[0] if urls else None
        enriched["repoUrls"] = urls
        time.sleep(delay)
        return enriched

    enriched_projects = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for enriched in pool.map(enrich, projects):
            enriched_projects.append(enriched)
            count = len(enriched_projects)
            if count % 10 == 0 or count == len(projects):
                print(f"Repository details: {count} / {len(projects)}", file=sys.stderr)
    with_repo = sum(bool(project["repoUrl"]) for project in enriched_projects)
    print(f"{with_repo} projects have a listed repository; "
          f"{len(projects) - with_repo} have none.", file=sys.stderr)
    return enriched_projects


def write_exports(projects, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "projects.json"
    csv_path = output_dir / "projects.csv"
    json_path.write_text(json.dumps(projects, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    columns = ["id", "title", "repoUrl", "repoUrls", "externalRepoUrl", "codeRepoUrl",
               "sourceCode", "linkRepoState", "adoRepoTitle",
               "tagline", "description", "hackathonId", "hackathonName",
               "createdAt", "keywords", "memberCount", "commentCount",
               "isProjectOpenForOthersToJoin", "projectMembers", "coverImage", "videoData"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for project in projects:
            row = {}
            for column in columns:
                value = project.get(column)
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                # Prevent spreadsheet software interpreting project text as formulas.
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    value = "'" + value
                row[column] = value
            writer.writerow(row)
    return json_path, csv_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("curl_file", type=Path, help="Text file containing the copied cURL command")
    parser.add_argument("--detail-curl-file", type=Path,
                        help="Project-detail cURL file; enables repository enrichment")
    parser.add_argument("--workers", type=int, default=4,
                        help="Concurrent project-detail requests, 1–8 (default: 4)")
    parser.add_argument("--output-dir", type=Path, default=Path("projects-export"))
    parser.add_argument("--page-size", type=int, default=9, help="Projects per request (default: 9)")
    parser.add_argument("--delay", type=float, default=0.3, help="Seconds between pages (default: 0.3)")
    args = parser.parse_args()
    if args.page_size < 1 or args.delay < 0:
        parser.error("Page size must be positive and delay must be non-negative.")
    if not 1 <= args.workers <= 8:
        parser.error("Workers must be between 1 and 8.")
    try:
        headers, payload = read_request(args.curl_file)
        if args.detail_curl_file:
            detail_headers, detail_payload = read_request(
                args.detail_curl_file, "getProjectDetailsWithQuestions")
            # Use the newer detail request's session for the search as well.
            headers = detail_headers
        projects = collect_projects(headers, payload, args.page_size, args.delay)
        if args.detail_curl_file:
            projects = enrich_repositories(projects, detail_headers, detail_payload,
                                          args.workers, args.delay)
        json_path, csv_path = write_exports(projects, args.output_dir)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Export failed: {error}", file=sys.stderr)
        return 1
    print(f"Exported {len(projects)} projects to {json_path} and {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
