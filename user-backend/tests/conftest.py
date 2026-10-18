import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from backend.app import create_app
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
    with psycopg.connect(match) as conn:
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def client(store):
    with TestClient(create_app(store, enable_dev_feed=True)) as client:
        yield client


@pytest.fixture
def token(client):
    response = client.post("/sessions", json={"profile_id": "chelsea-analytical"})
    assert response.status_code == 201
    return response.json()["session_token"]
