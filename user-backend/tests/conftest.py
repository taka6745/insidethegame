import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from backend.store import Store


@pytest.fixture
def store():
    accounts = os.environ.get("ACCOUNTS_DATABASE_URL")
    match = os.environ.get("MATCH_APP_DATABASE_URL")
    if not accounts or not match:
        pytest.fail("Run ./dev test backend for real-Postgres API tests")
    schema = "test_backend_" + uuid.uuid4().hex
    store = Store(accounts, match, schema)
    yield store
    store.close()
    with psycopg.connect(match) as conn:
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def client(store):
    from harness import build
    app, _, _ = build(store)
    with TestClient(app) as client:
        yield client
