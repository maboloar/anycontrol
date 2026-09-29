"""서버 통합 테스트: 합성 소스로 카메라 없이 WebSocket 스트림과 보안 검사를 확인한다."""

import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from vision_input.pipeline import VisionProcessor
from starlette.websockets import WebSocketDisconnect

from vision_input.config import Settings
from vision_input.server.app import SyntheticSpec, create_app
from vision_input.server.protocol import unpack_preview


class RectSeg:
    """요청 박스 안쪽 80% 사각형을 마스크로 돌려주는 가짜 분할기 (모델 없이 API 흐름만 검사)."""

    name = "rect"

    def segment(self, frame, box=None, points=None):
        from vision_input.tracking.segment import SegResult

        h, w = frame.shape[:2]
        if box is None:
            x, y = points[0][0], points[0][1]
            box = (x - 30, y - 20, x + 30, y + 20)
        m = np.zeros((h, w), bool)
        bw, bh = box[2] - box[0], box[3] - box[1]
        m[int(box[1] + 0.1 * bh) : int(box[3] - 0.1 * bh), int(box[0] + 0.1 * bw) : int(box[2] - 0.1 * bw)] = True
        return SegResult([m, m.copy()], [0.9, 0.7])


@pytest.fixture()
def client():
    app = create_app(Settings(), SyntheticSpec(width=320, height=240, fps=60), serve_frontend=False,
                     segmenter=RectSeg(), processor=VisionProcessor(None))
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_ws_streams_hello_telemetry_and_frames(client):
    with client.websocket_connect("/ws") as ws:
        hello = json.loads(ws.receive_text())
        assert hello["type"] == "hello"
        frames, telemetry = [], []
        deadline = time.monotonic() + 5
        while (len(frames) < 3 or not telemetry) and time.monotonic() < deadline:
            msg = ws.receive()
            if msg.get("bytes"):
                frames.append(unpack_preview(msg["bytes"]))
            elif msg.get("text"):
                obj = json.loads(msg["text"])
                if obj["type"] == "telemetry":
                    telemetry.append(obj["data"])
        assert len(frames) >= 3
        hdr, jpeg = frames[-1]
        assert (hdr.width, hdr.height) == (320, 240)
        assert jpeg[:2] == b"\xff\xd8"  # JPEG SOI
        assert [f[0].seq for f in frames] == sorted(f[0].seq for f in frames)
        assert telemetry[-1]["source"]["kind"] == "synthetic"


def test_ws_ping_pong(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"v": 1, "type": "ping", "data": {"t": 123}}))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            msg = ws.receive()
            if msg.get("text") and json.loads(msg["text"])["type"] == "pong":
                assert json.loads(msg["text"])["data"]["client_t"] == 123
                return
        pytest.fail("no pong")


def test_foreign_origin_rejected_for_http_and_ws(client):
    r = client.get("/api/health", headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_text()


def test_dev_origin_allowed(client):
    r = client.get("/api/health", headers={"origin": "http://localhost:5173"})
    assert r.status_code == 200


def test_foreign_host_rejected(client):
    r = client.get("/api/health", headers={"host": "attacker.example"})
    assert r.status_code == 400


def test_switch_source(client):
    r = client.put("/api/source", json={"kind": "synthetic", "width": 160, "height": 120, "fps": 30})
    assert r.status_code == 200
    with client.websocket_connect("/ws") as ws:
        ws.receive_text()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            msg = ws.receive()
            if msg.get("bytes"):
                hdr, _ = unpack_preview(msg["bytes"])
                if (hdr.width, hdr.height) == (160, 120):
                    return
        pytest.fail("source did not switch")


def test_invalid_source_spec_rejected(client):
    assert client.put("/api/source", json={"kind": "camera", "index": 99}).status_code == 422


# ---------------------------------------------------------------- objects API
def _wait_frame(client):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        r = client.post("/api/objects", json={"box": [0.3, 0.3, 0.7, 0.7]})
        if r.status_code != 409:
            return r
        time.sleep(0.05)
    pytest.fail("no frame")


def test_add_list_neutral_candidate_delete(client):
    r = _wait_frame(client)
    assert r.status_code == 201, r.text
    obj = r.json()
    assert obj["state"] == "tracking" and obj["candidates"] == 2 and len(obj["contour"]) >= 3
    x1, y1, x2, y2 = obj["box"]
    assert 0.3 <= x1 < x2 <= 0.7 and 0.3 <= y1 < y2 <= 0.7
    assert obj["axes"]["x"] == 0.0 and obj["axes"]["depth"] == 0.0
    oid = obj["id"]
    assert [o["id"] for o in client.get("/api/objects").json()] == [oid]
    assert client.post(f"/api/objects/{oid}/neutral").status_code == 200
    r2 = client.post(f"/api/objects/{oid}/candidate", json={"index": 1})
    assert r2.status_code == 200 and r2.json()["candidate_index"] == 1
    new_id = r2.json()["id"]
    assert client.patch(f"/api/objects/{new_id}", json={"name": "지갑"}).json()["name"] == "지갑"
    assert client.delete(f"/api/objects/{new_id}").status_code == 204
    assert client.get("/api/objects").json() == []
    assert client.delete(f"/api/objects/{new_id}").status_code == 404


def test_add_by_point_and_state_message(client):
    _wait_frame(client)  # 박스로 하나
    r = client.post("/api/objects", json={"point": [0.5, 0.5]})
    assert r.status_code == 201
    with client.websocket_connect("/ws") as ws:
        ws.receive_text()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            msg = ws.receive()
            if msg.get("text"):
                o = json.loads(msg["text"])
                if o["type"] == "state" and len(o["data"]["objects"]) == 2:
                    assert o["data"]["size"] == [320, 240]
                    return
        pytest.fail("no state with objects")


@pytest.mark.parametrize("body", [{}, {"box": [0.1, 0.1, 0.2, 0.2], "point": [0.5, 0.5]},
                                  {"box": [0, 0, 2, 1]}, {"point": [0.5]}])
def test_add_validation(client, body):
    assert client.post("/api/objects", json=body).status_code == 422


def test_tiny_selection_rejected_with_message(client):
    _wait_frame(client)
    r = client.post("/api/objects", json={"box": [0.5, 0.5, 0.505, 0.505]})
    assert r.status_code == 422 and "작" in r.json()["detail"]


@pytest.mark.parametrize("path", ["/etc/passwd", "../../../../etc/hosts", "backend/pyproject.toml", "nope.mov"])
def test_file_source_confined_to_project_videos(client, path):
    r = client.put("/api/source", json={"kind": "file", "path": path})
    assert r.status_code == 400


@pytest.mark.parametrize('operation', ['add', 'candidate'])
def test_async_registration_rejects_results_after_source_change(operation):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from .test_source_controls import wait_until

    entered, release = threading.Event(), threading.Event()
    class DelayedSeg(RectSeg):
        delay = False
        def segment(self, *args, **kwargs):
            if self.delay:
                entered.set()
                assert release.wait(5)
            return super().segment(*args, **kwargs)

    seg, processor = DelayedSeg(), VisionProcessor(None)
    app = create_app(initial_source=SyntheticSpec(width=320, height=240), processor=processor,
                     segmenter=seg, serve_frontend=False)
    with TestClient(app) as c, ThreadPoolExecutor(1) as pool:
        oid = _wait_frame(c).json()['id']
        seg.delay = True
        url, body = ('/api/objects', {'box': [.3, .3, .7, .7]}) if operation == 'add' else (
            f'/api/objects/{oid}/candidate', {'index': 1})
        request = pool.submit(c.post, url, json=body)
        try:
            assert entered.wait(3)
            assert c.put('/api/source', json={'kind': 'synthetic', 'width': 160, 'height': 120}).status_code == 200
            wait_until(lambda: processor.frame_size == (160, 120))
        finally:
            release.set()
        result = request.result(3)
        assert result.status_code == 409, result.text
        assert c.get('/api/objects').json() == []


def test_profile_path_name_is_validated_before_saving(client, monkeypatch):
    # 경로에서 받은 이름도 본문의 Profile과 동일한 최대 길이를 지켜야 한다.
    from vision_input.mapping.store import ProfileStore
    from unittest.mock import Mock
    save = Mock()
    monkeypatch.setattr(ProfileStore, 'save', save)
    result = client.put('/api/profiles/' + 'x' * 41, json={'name': 'valid', 'mappings': []})
    assert result.status_code == 400
    save.assert_not_called()
