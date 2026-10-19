"""깊이 모델 비교(개발자 실험): 순수 계산, 내려받기 검증, /api/dev 엔드포인트. 실제 모델·네트워크는 쓰지 않는다."""
import hashlib
import io
import time
import numpy as np
import pytest
from fastapi.testclient import TestClient
from vision_input import depth_model as dm
from vision_input.config import Settings
from vision_input.pipeline import VisionProcessor
from vision_input.server.app import SyntheticSpec, create_app
from .test_server import RectSeg, _wait_frame

W, H = 160, 120


def _plane(a, b, c, w=W, h=H):
    gy, gx = np.mgrid[0:h, 0:w].astype(np.float64)
    return a * (gx + .5) / w + b * (gy + .5) / h + c


def test_fit_depth_plane_recovers_a_tilted_plane_despite_outliers():
    rng = np.random.default_rng(1)
    depth = _plane(0.1, 0.6, 0.2) + rng.normal(0, 0.002, (H, W))
    depth[:20, :40] = 0.95                               # 책상 위 물체 같은 이상치
    floor = np.ones((H, W), bool)
    fit = dm.fit_depth_plane(depth.astype(np.float32), floor)
    assert fit is not None
    assert fit["A"] == pytest.approx(0.1, abs=0.03) and fit["B"] == pytest.approx(0.6, abs=0.03)
    assert fit["inlier_frac"] > 0.9


def test_fit_depth_plane_needs_enough_points():
    assert dm.fit_depth_plane(np.zeros((H, W), np.float32), np.zeros((H, W), bool)) is None


def test_compare_planes_reports_matching_roll_and_detects_a_mismatch():
    valid = np.ones((H, W), bool)
    fit = {"A": 0.3, "B": 1.0, "C": 0.0}                 # 오른쪽으로 갈수록 가까움 → 롤
    same = dm.compare_planes(fit, _plane(0.3, 1.0, 0.5) * 7, valid, (W, H))   # 스케일·이동은 무관해야 한다
    assert same["corr"] == pytest.approx(1.0, abs=1e-3) and same["angle_deg"] < 0.5
    assert same["roll_depth_deg"] == pytest.approx(same["roll_touch_deg"], abs=0.5)
    other = dm.compare_planes(fit, _plane(-0.3, 1.0, 0.0), valid, (W, H))     # 롤 방향이 반대
    assert other["angle_deg"] > 20 and other["roll_depth_deg"] * other["roll_touch_deg"] < 0


# ---- 내려받기
@pytest.fixture()
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ANYCONTROL_DEPTH_DIR", str(tmp_path))
    return tmp_path


def _wait(dl):
    for _ in range(200):
        if not dl.running:
            return
        time.sleep(0.01)
    raise AssertionError("download did not finish")


def test_is_available_needs_every_file(cache):
    assert not dm.is_available()
    for f in dm.FILES:
        (cache / f).parent.mkdir(parents=True, exist_ok=True)
        (cache / f).write_bytes(b"x")
    assert dm.is_available()


def _fake_urlopen(monkeypatch, payload=b"weights"):
    import urllib.request
    calls = []

    def opener(url, timeout=None, context=None):
        calls.append(url)
        return io.BytesIO(payload if url.endswith("weight.bin") else b"{}")
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    return calls


def test_download_verifies_sha256_and_removes_partial_files(cache, monkeypatch):
    _fake_urlopen(monkeypatch, b"tampered")
    dl = dm.Downloader()
    assert dl.start() is True
    _wait(dl)
    assert "SHA-256" in (dl.error or "")
    assert not dm.is_available()
    assert not list(cache.rglob("*.part"))               # 받다 만 파일을 남기지 않는다
    assert not (cache / dm.FILES[-1]).exists()


def test_download_succeeds_when_the_hash_matches_and_is_not_repeated(cache, monkeypatch):
    payload = b"good-weights"
    monkeypatch.setattr(dm, "WEIGHT_SHA256", hashlib.sha256(payload).hexdigest())
    calls = _fake_urlopen(monkeypatch, payload)
    dl = dm.Downloader()
    assert dl.start() is True
    _wait(dl)
    assert dl.error is None and dm.is_available()
    assert len(calls) == len(dm.FILES) and all(u.startswith("https://huggingface.co/") for u in calls)
    assert dl.start() is False                           # 이미 있으면 다시 받지 않는다
    assert dl.state()["available"] is True


# ---- 엔드포인트
@pytest.fixture()
def client(cache):
    app = create_app(Settings(), SyntheticSpec(width=320, height=240, fps=60), serve_frontend=False,
                     segmenter=RectSeg(), processor=VisionProcessor(None))
    with TestClient(app) as c:
        yield c


def test_status_and_compare_report_a_missing_model(client):
    s = client.get("/api/dev/depth-model").json()
    assert s["available"] is False and s["license"] == "Apache-2.0" and s["size_mb"] == dm.APPROX_MB
    _wait_frame(client)
    pid = client.post("/api/objects", json={"line": [0.4, 0.3, 0.55, 0.7], "name": "펜"}).json()["id"]
    r = client.get(f"/api/dev/pen/{pid}/depth-compare").json()
    assert r["ready"] is False and r["reason"] == "model_missing"


def test_download_endpoint_does_nothing_over_the_network_when_not_called(client, monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("network must not be used"))
    client.get("/api/dev/depth-model")                   # 상태 조회만으로는 내려받지 않는다


def test_compare_endpoint_with_a_stubbed_model(client, monkeypatch):
    monkeypatch.setattr(dm, "is_available", lambda: True)
    monkeypatch.setattr(dm.DepthModel, "predict", lambda self, bgr: _plane(.1, .5, .3, *dm.INPUT_SIZE).astype(np.float32))
    _wait_frame(client)
    assert client.get("/api/dev/pen/999/depth-compare").status_code == 404
    obj = client.post("/api/objects", json={"box": [0.1, 0.1, 0.3, 0.3]}).json()["id"]
    assert client.get(f"/api/dev/pen/{obj}/depth-compare").status_code == 404       # 펜이 아닌 물체
    pid = client.post("/api/objects", json={"line": [0.4, 0.3, 0.55, 0.7], "name": "펜"}).json()["id"]
    client.post(f"/api/objects/{pid}/pen/config", json={"contact_method": "legacy"})
    assert client.get(f"/api/dev/pen/{pid}/depth-compare").json() == {"ready": False, "reason": "contact_method"}
    client.post(f"/api/objects/{pid}/pen/config", json={"contact_method": "floor"})
    r = client.get(f"/api/dev/pen/{pid}/depth-compare").json()
    assert r["ready"] is False and r["reason"] in ("learning", "no_floor", "no_frame")


def test_depth_map_images_and_endpoint_with_a_stubbed_model(client, monkeypatch):
    d = _plane(.1, .8, .1, *dm.INPUT_SIZE).astype(np.float32)
    imgs = dm.depth_map_images(d)
    assert imgs["image"].startswith("data:image/png;base64,") and imgs["overlay"].startswith("data:image/png;base64,")
    assert imgs["size"] == list(dm.INPUT_SIZE) and imgs["hi"] > imgs["lo"]
    # 가중치가 없으면 이유만 돌려준다
    monkeypatch.setattr(dm, "is_available", lambda: False)
    assert client.get("/api/dev/depth-map").json() == {"ready": False, "reason": "model_missing"}
    monkeypatch.setattr(dm, "is_available", lambda: True)
    monkeypatch.setattr(dm.DepthModel, "predict", lambda self, bgr: d)
    _wait_frame(client)
    got = None
    for _ in range(100):                              # 첫 요청이 백그라운드 계산을 시작하고 다음 요청이 결과를 받는다
        got = client.get("/api/dev/depth-map").json()
        if got["ready"]:
            break
        time.sleep(0.02)
    assert got["ready"] and got["overlay"].startswith("data:image/png") and got["age"] < 5


def test_scene_map_images_and_endpoint(client):
    lg = np.zeros((90, 160), np.float32)
    lg[:, :80] = -3.0
    lg[30:60, 100:140] = 3.0
    imgs = dm.scene_map_images(lg)
    assert imgs["overlay"].startswith("data:image/png;base64,") and imgs["size"] == [160, 90] and imgs["fg_frac"] > 0
    frac = np.zeros((6, 8), np.float32)
    frac[0, :3] = 0.5                                 # 위쪽 세 칸이 바뀜 (뒤에서 사람이 지나감)
    ok = np.ones((6, 8), bool)
    ok[3, 4] = False                                  # 물체가 덮은 칸
    g = dm.scene_map_images(None, (640, 360), (frac, ok), 0.15)["grid"]   # 무효여도 격자는 그린다
    assert g == {"cols": 8, "rows": 6, "known": 47, "changed": 3}
    _wait_frame(client)
    got = None
    for _ in range(100):                              # 몇 프레임 지나면 배경을 배워 유효해진다
        got = client.get("/api/dev/scene-map").json()
        if (got["ready"] and got["info"]["valid"]) or got.get("reason") == "disabled":
            break
        time.sleep(0.02)
    if got.get("reason") != "disabled":               # 추적기가 없는 구성(모델 미설치)은 건너뛴다
        assert got["ready"] and got["overlay"].startswith("data:image/png") and got["info"]["valid"]


def test_bundled_weights_ship_with_the_program_and_match_the_pinned_hash(monkeypatch):
    """models/ 에 Depth Anything V2 Small 가중치가 들어 있고 (내려받기 없이) 바로 쓸 수 있다."""
    monkeypatch.delenv("ANYCONTROL_DEPTH_DIR", raising=False)
    monkeypatch.delenv("VI_MODELS_DIR", raising=False)
    assert dm.is_bundled() and dm.is_available() and dm.cache_dir() == dm.bundled_dir()
    assert dm.verify_weights()                                    # SHA-256 고정값과 같다
    assert dm.Downloader().start() is False                        # 이미 있으면 내려받지 않는다
    assert dm.Downloader().state()["bundled"] is True
