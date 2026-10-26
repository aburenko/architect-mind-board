import json

import pytest
from fastapi.testclient import TestClient

import app as server

HEADERS = {"X-Mindboard": "1"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATABASE", tmp_path / "boards.sqlite3")
    with TestClient(server.app) as test_client:
        yield test_client


def collection(text="A quiet reading room"):
    return {
        "mindboard-index-v1": json.dumps({"cur": "b1", "list": [{"id": "b1", "name": "Library"}]}),
        "mindboard-board-b1": json.dumps({"name": "Library", "notes": [{"id": "n1", "text": text}],
                                         "cats": [], "links": [], "view": {"x": 12, "y": 5, "z": 1}}),
    }


def test_page_and_health(client):
    assert client.get("/").status_code == 200
    assert "openMindBoardStorage" in client.get("/storage.js").text
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/app.py").status_code == 404
    assert client.get("/data/mindboard.sqlite3").status_code == 404


def test_save_survives_restart(client):
    assert client.get("/api/state").json() == {"revision": 0, "storage": {}}
    storage = collection()
    response = client.put("/api/state", json={"revision": 0, "storage": storage}, headers=HEADERS)
    assert response.json() == {"revision": 1}
    with TestClient(server.app) as restarted:
        assert restarted.get("/api/state").json() == {"revision": 1, "storage": storage}


def test_stale_device_cannot_overwrite(client):
    client.put("/api/state", json={"revision": 0, "storage": collection()}, headers=HEADERS)
    response = client.put("/api/state", json={"revision": 0, "storage": collection("stale")}, headers=HEADERS)
    assert response.status_code == 409
    assert client.get("/api/state").json()["storage"] == collection()


def test_delete_and_rename_boards(client):
    storage = collection()
    index = {"cur": "b2", "list": [{"id": "b1", "name": "Library"}, {"id": "b2", "name": "Second"}]}
    storage["mindboard-index-v1"] = json.dumps(index)
    storage["mindboard-board-b2"] = json.dumps({"notes": [], "name": "Second"})
    assert client.put("/api/state", json={"revision": 0, "storage": storage}, headers=HEADERS).status_code == 200
    del storage["mindboard-board-b1"]
    index["list"] = [{"id": "b2", "name": "Renamed"}]
    storage["mindboard-index-v1"] = json.dumps(index)
    assert client.put("/api/state", json={"revision": 1, "storage": storage}, headers=HEADERS).status_code == 200
    assert client.get("/api/state").json() == {"revision": 2, "storage": storage}


@pytest.mark.parametrize("storage", [{}, {"mindboard-index-v1": "null"},
                                    {"mindboard-index-v1": '{"cur":"x","list":[]}'}])
def test_invalid_collection_is_rejected(client, storage):
    assert client.put("/api/state", json={"revision": 0, "storage": storage}, headers=HEADERS).status_code == 422
    assert client.get("/api/state").json()["revision"] == 0


def test_cross_origin_and_missing_header_rejected(client):
    body = {"revision": 0, "storage": collection()}
    assert client.put("/api/state", json=body).status_code == 403
    assert client.put("/api/state", json=body, headers={**HEADERS, "Origin": "https://evil.example"}).status_code == 403
    assert client.put("/api/state", json=body, headers={**HEADERS, "Origin": "http://testserver"}).status_code == 200


def test_oversized_request_rejected(client):
    response = client.put("/api/state", content=b"x" * (server.MAX_BODY + 1),
                          headers={**HEADERS, "Content-Type": "application/json"})
    assert response.status_code == 413