# Feed (simulated provider)

> **In short:** stands in for an external match-data and broadcast provider. It replays recorded fixtures as live matches, several at once. Our services see only its Event Hubs stream and its HLS over HTTP. Details: [component page](../docs/components/feed.md).

```sh
pip install -r feed/requirements-test.txt && python -m pytest -q feed   # from data-generation/
FEED_TEST_DATABASE_URL=postgresql://… python -m pytest -q feed          # adds the Postgres repository tests
```

Synthetic data only; provenance stays in each MA1.
