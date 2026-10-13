# Inside the Game project export

Fetch all projects for the Inside the Game Developer Hackathon and enrich them with repository URLs from each project detail response.

## Run

Python 3 is required; no extra packages are needed.

Save the project-list and project-detail requests from browser DevTools using **Copy as cURL** into `search-request.txt` and `detail-request.txt` locally. Then run:

```bash
python3 fetch_projects.py search-request.txt \
  --detail-curl-file detail-request.txt \
  --output-dir projects-export
```

The script starts from the first page, follows cursors, deduplicates project IDs, retries temporary request failures, and checks the final count. Detail requests use four workers by default (`--workers 1` runs them sequentially).

`repoUrl` prefers `externalRepoUrl`, falling back to `codeRepoUrl`. Both original fields and all distinct URLs in `repoUrls` are retained. Blank repository values mean no URL was listed in these fields; they do not mean a repository does not exist.

## Included snapshot

Fetched on 13 October 2026 for hackathon `34887`: 121 projects, with listed repositories for 22 projects and no listed repository for 99.

- `projects.json`: full project-list fields and repository metadata.
- `projects.csv`: tabular export including repository columns.

Copied cURL files contain session credentials and are excluded from version control. When authentication expires, copy a fresh request. Repository URLs were read from Innovation Studio; repository contents and accessibility were not checked.
