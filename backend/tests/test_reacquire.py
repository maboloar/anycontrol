"""모양 기억·재획득(reacquire.py), 다시 선택(reselect), 마우스 축별 감도·반전, 반전 기본값."""
import math

import cv2
import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vision_input.io.mouse import MouseController, MouseSettings, axis_adjust
from vision_input.io.sink import VirtualSink
from vision_input.pipeline import VisionProcessor
from vision_input.tracking import reacquire as ra
from vision_input.tracking.tier0 import ColorModel

H, W = 180, 320


def blob(cx, cy, a, b, ang, h=H, w=W):
    m = np.zeros((h, w), np.uint8)
    cv2.ellipse(m, (int(cx), int(cy)), (int(a), int(b)), ang, 0, 360, 1, -1)
    return m.astype(bool)


def lab_idx(mask, fg=5, bg=900):
    idx = np.full(mask.shape, bg, np.int32)
    idx[mask] = fg
    return idx


shapes = st.tuples(st.integers(12, 40), st.integers(6, 30), st.integers(0, 179))


# ---------------------------------------------------------------- 모양 기억 속성
@settings(max_examples=40, deadline=None)
@given(shapes)
def test_self_match_passes_thresholds(s):
    """자기 일치: 같은 마스크·프레임으로 만든 기억과 그 마스크의 점수는 모든 합격 임계값을 넘는다."""
    a, b, ang = s
    m = blob(160, 90, a, b, ang)
    idx = lab_idx(m)
    mem = ra.make_memory(m, idx, ColorModel.NB)
    sc = ra.shape_score(mem, m, idx, mem.area)
    assert sc is not None and sc.passes(ra.ReacquireConfig())
    assert sc.iou > 0.95 and sc.hu < 1e-6 and sc.area_ratio == pytest.approx(1.0) and sc.color == pytest.approx(1.0)


@settings(max_examples=40, deadline=None)
@given(shapes, st.integers(-50, 50), st.integers(-30, 30))
def test_aligned_iou_translation_invariant(s, dx, dy):
    """이동 불변: 평행 이동한 마스크의 정렬 IoU 는 원본과 0.01 이내."""
    a, b, ang = s
    m = blob(160, 90, a, b, ang)
    mem = ra.make_memory(m, lab_idx(m), ColorModel.NB)
    shifted = np.roll(np.roll(m, dy, axis=0), dx, axis=1)
    assert abs(ra.aligned_iou(mem.template, shifted) - ra.aligned_iou(mem.template, m)) <= 0.01


def test_different_shape_and_color_rejected():
    m = blob(160, 90, 40, 8, 0)           # 길쭉한 막대
    idx = lab_idx(m)
    mem = ra.make_memory(m, idx, ColorModel.NB)
    disk = blob(160, 90, 18, 18, 0)       # 비슷한 면적의 원
    assert not ra.shape_score(mem, disk, lab_idx(disk), mem.area).passes(ra.ReacquireConfig())
    other_color = ra.shape_score(mem, m, lab_idx(m, fg=77), mem.area)
    assert other_color.color < 0.1 and not other_color.passes(ra.ReacquireConfig())


def test_scale_and_rotation_invariant():
    m = blob(160, 90, 30, 10, 20)
    mem = ra.make_memory(m, lab_idx(m), ColorModel.NB)
    m2 = blob(100, 60, 45, 15, 110)  # 1.5배 크고 90° 돌림
    sc = ra.shape_score(mem, m2, lab_idx(m2), mem.area * 1.5 ** 2)
    assert sc.iou > 0.85 and sc.hu < 0.2 and sc.passes(ra.ReacquireConfig())


# ---------------------------------------------------------------- 탐색
def _scene(objs):
    idx = np.full((H, W), 900, np.int32)
    for m in objs:
        idx[m] = 5
    table = np.zeros(ColorModel.NB, np.float32)
    table[5] = 0.95
    return idx, table[idx]


def _fake_seg(truth):
    """박스와 가장 많이 겹치는 정답 마스크를 돌려주는 분할기."""
    def seg(frame, box):
        x1, y1, x2, y2 = (int(v) for v in box)
        best = max(truth, key=lambda m: m[y1:y2, x1:x2].sum())
        return [best], [0.95]
    return seg


def test_search_finds_remembered_object_anywhere():
    m0 = blob(60, 50, 30, 10, 0)
    mem = ra.make_memory(m0, lab_idx(m0), ColorModel.NB)
    now = blob(250, 130, 30, 10, 30)  # 다른 곳, 돌아감
    idx, prob = _scene([now])
    r = ra.search(np.zeros((H, W, 3), np.uint8), idx, prob, mem, 1.0, 0.5, ra.ReacquireConfig(), _fake_seg([now]), [])
    assert r is not None and not r.ambiguous and ra._mask_iou(r.mask, now) > 0.99


def test_search_excludes_other_tracked_object_and_flags_twins():
    m0 = blob(60, 50, 30, 10, 0)
    mem = ra.make_memory(m0, lab_idx(m0), ColorModel.NB)
    a, b = blob(90, 60, 30, 10, 0), blob(240, 120, 30, 10, 0)
    idx, prob = _scene([a, b])
    cfg = ra.ReacquireConfig()
    frame = np.zeros((H, W, 3), np.uint8)
    both = ra.search(frame, idx, prob, mem, 1.0, 0.5, cfg, _fake_seg([a, b]), [])
    assert both is not None and both.ambiguous  # 똑같은 둘: 고르지 않는다
    only = ra.search(frame, idx, prob, mem, 1.0, 0.5, cfg, _fake_seg([a, b]), [a])  # a 는 다른 물체가 추적 중
    assert only is not None and not only.ambiguous and ra._mask_iou(only.mask, b) > 0.99


def test_search_rejects_wrong_shape():
    m0 = blob(60, 50, 30, 10, 0)
    mem = ra.make_memory(m0, lab_idx(m0), ColorModel.NB)
    disk = blob(200, 100, 17, 17, 0)
    idx, prob = _scene([disk])
    assert ra.search(np.zeros((H, W, 3), np.uint8), idx, prob, mem, 1.0, 0.5, ra.ReacquireConfig(),
                     _fake_seg([disk]), []) is None


# ---------------------------------------------------------------- 마우스 축별 감도·반전
coords = st.tuples(st.floats(0, 1), st.floats(0, 1))
sens = st.floats(0.2, 5.0)


@given(coords, sens, sens, st.booleans(), st.booleans())
def test_axis_adjust_stays_in_screen(p, sx, sy, ix, iy):
    q = axis_adjust(np.array(p), sx, sy, ix, iy)
    assert 0.0 <= q[0] <= 1.0 and 0.0 <= q[1] <= 1.0


@given(coords)
def test_axis_adjust_defaults_are_identity_and_invert_roundtrips(p):
    arr = np.array(p)
    assert np.allclose(axis_adjust(arr), arr)
    once = axis_adjust(arr, invert_x=True, invert_y=True)
    assert np.allclose(axis_adjust(once, invert_x=True, invert_y=True), arr)


def test_axis_adjust_scales_about_center():
    q = axis_adjust(np.array([0.6, 0.4]), 2.0, 3.0)
    assert q == pytest.approx([0.7, 0.2])
    assert axis_adjust(np.array([0.6, 0.4]), 1.0, 1.0, True, False) == pytest.approx([0.4, 0.4])


def test_mouse_settings_validation_and_defaults():
    s = MouseSettings()
    assert (s.sens_x, s.sens_y, s.mirror, s.invert_y) == (1.0, 1.0, False, False)
    for bad in ({"sens_x": 0.1}, {"sens_y": 5.5}):
        with pytest.raises(ValueError):
            MouseSettings(**bad)


def test_object_mouse_applies_invert_after_mirror():
    sink = VirtualSink()
    c = MouseController(sink)
    c.input_mirror = True
    c.configure(MouseSettings(mode="object", object_id=1, hand_clicks=False, object_region=[0, 0, 1, 1],
                              coordinate_mode="image", mirror=True, invert_y=True, sens_x=1.0))
    for i in range(40):
        c.update(i / 30, None, (0.2, 0.3), True)  # 전역 거울 → 0.8, 마우스 좌우 반전 → 0.2
    assert sink.x == pytest.approx(0.2, abs=0.02) and sink.y == pytest.approx(0.7, abs=0.02)


def test_mirror_defaults_on():
    p = VisionProcessor(None)
    assert p.input_mirror is True
    # 전역 거울이 켜진 기본 상태에서 마우스도 거울이 된다 (마우스 전용 mirror 는 기본 끔: XOR)
    assert MouseSettings().mirror is False
    c = p.mouse
    c.configure(MouseSettings(mode="object", object_id=1, hand_clicks=False, object_region=[0, 0, 1, 1],
                              coordinate_mode="image"))
    for i in range(40):
        c.update(i / 30, None, (0.2, 0.5), True)
    assert p.sink.x == pytest.approx(0.8, abs=0.02)  # type: ignore[attr-defined]


def test_put_mouse_rejects_out_of_range(client_srv):
    before = client_srv.get("/api/mouse").json()["settings"]
    r = client_srv.put("/api/mouse", json={**before, "sens_x": 9})
    assert r.status_code == 422
    assert client_srv.get("/api/mouse").json()["settings"] == before
    r = client_srv.put("/api/mouse", json={**before, "sens_x": 2.5, "invert_y": True})
    assert r.status_code == 200 and r.json()["settings"]["sens_x"] == 2.5 and r.json()["settings"]["invert_y"]


# ---------------------------------------------------------------- 다시 선택 API
class RectSeg:
    """요청 박스 안쪽 80% 사각형을 마스크로 (모델 없이 API 흐름만 검사, test_server 와 같음)."""
    name = "rect"

    def segment(self, frame, box=None, points=None):
        from vision_input.tracking.segment import SegResult
        h, w = frame.shape[:2]
        if box is None:
            x, y = points[0][0], points[0][1]
            box = (x - 30, y - 20, x + 30, y + 20)
        m = np.zeros((h, w), bool)
        bw, bh = box[2] - box[0], box[3] - box[1]
        m[int(box[1] + 0.1 * bh):int(box[3] - 0.1 * bh), int(box[0] + 0.1 * bw):int(box[2] - 0.1 * bw)] = True
        return SegResult([m, m.copy()], [0.9, 0.7])


@pytest.fixture()
def client_srv():
    from fastapi.testclient import TestClient

    from vision_input.config import Settings
    from vision_input.server.app import SyntheticSpec, create_app

    app = create_app(Settings(), SyntheticSpec(width=320, height=240, fps=60), serve_frontend=False,
                     segmenter=RectSeg(), processor=VisionProcessor(None))
    with TestClient(app) as c:
        yield c


def _add(c, body):
    import time
    for _ in range(50):
        r = c.post("/api/objects", json=body)
        if r.status_code != 409:
            return r
        time.sleep(0.05)
    return r


def test_reselect_keeps_identity_and_mouse_link(client_srv):
    c = client_srv
    a = _add(c, {"box": [0.1, 0.1, 0.4, 0.4]}).json()
    b = _add(c, {"box": [0.6, 0.6, 0.9, 0.9]}).json()
    assert c.patch(f"/api/objects/{a['id']}", json={"name": "지우개"}).status_code == 200
    ms = c.get("/api/mouse").json()["settings"]
    assert c.put("/api/mouse", json={**ms, "mode": "object", "object_id": a["id"]}).status_code == 200
    ids0 = sorted(o["id"] for o in c.get("/api/objects").json())
    r = c.post(f"/api/objects/{a['id']}/reselect", json={"box": [0.5, 0.2, 0.8, 0.5]})
    assert r.status_code == 200, r.text
    o = r.json()
    assert (o["id"], o["name"], o["color"]) == (a["id"], "지우개", a["color"]) and o["state"] == "tracking"
    assert o["box"][0] > 0.5  # 새 위치의 마스크
    assert sorted(x["id"] for x in c.get("/api/objects").json()) == ids0  # id 집합 불변
    s = c.get("/api/mouse").json()["settings"]
    assert s["mode"] == "object" and s["object_id"] == a["id"]
    assert b["id"] in ids0


def test_reselect_errors_leave_object_unchanged(client_srv):
    c = client_srv
    a = _add(c, {"box": [0.1, 0.1, 0.4, 0.4]}).json()
    assert c.post("/api/objects/999/reselect", json={"box": [0.1, 0.1, 0.4, 0.4]}).status_code == 404
    # 너무 작은 선택 → 분할 실패(빈 마스크·등록 오류) → 422, 상태 그대로
    r = c.post(f"/api/objects/{a['id']}/reselect", json={"box": [0.5, 0.5, 0.505, 0.505]})
    assert r.status_code == 422
    # 일반 물체에 펜 두 점 → 422
    assert c.post(f"/api/objects/{a['id']}/reselect", json={"line": [0.1, 0.1, 0.3, 0.3]}).status_code == 422
    now = [o for o in c.get("/api/objects").json() if o["id"] == a["id"]][0]
    assert now["box"] == a["box"] and now["name"] == a["name"]


def test_axis_rebase_keeps_values_continuous():
    from vision_input.tracking.api import Pose
    from vision_input.tracking.axes import AxisState

    ax = AxisState((640, 480))
    ax.sample(Pose(100, 100, 1.0, 0.0, 1.0), None, 10)
    ax.sample(Pose(120, 100, 1.2, 15.0, 1.1), None, 10)
    before_vals, before = ax.values(), ax.last
    ax.sample(Pose(120, 100, 1.0, 0.0, 1.0), None, 10)  # 다시 등록: 새 기준 (크기 1, 각도 0)
    ax.rebase(before, ax.last)
    v = ax.values()
    for k in ("x", "y", "depth", "angle", "stretch"):
        assert v[k] == pytest.approx(before_vals[k], abs=1e-4), k
    assert math.isfinite(v["depth"])


def test_tracker_reselect_same_id_new_shape_and_tracking():
    from vision_input.tracking.api import InitPrompt, TrackState
    from vision_input.tracking.vi_tracker import TrackerConfig, ViTracker

    frame = np.full((H, W, 3), 60, np.uint8)
    m1 = blob(80, 90, 30, 10, 0)
    frame[m1] = (30, 30, 220)
    t = ViTracker(TrackerConfig(tier1="off"))
    t.add(frame, 7, InitPrompt(box=(50, 80, 110, 100), mask=m1))
    old_shape = t.tracks[7].shape
    for i in range(3):
        t.step(frame, (i + 1) / 30)
    t.tracks[7].state = TrackState.LOST
    frame2 = np.full((H, W, 3), 60, np.uint8)
    m2 = blob(230, 100, 20, 20, 0)
    frame2[m2] = (30, 220, 30)
    out = t.reselect(frame2, 7, InitPrompt(box=(210, 80, 250, 120), mask=m2))
    tr = t.tracks[7]
    assert list(t.tracks) == [7] and out.state == TrackState.TRACKING and tr.state == TrackState.TRACKING
    assert tr.shape is not old_shape and tr.shape.area == pytest.approx(m2.sum(), rel=0.05)
    assert abs(tr.kf.x[0] - 230) < 3
    # 빈 마스크·없는 id: 아무것도 바꾸지 않는다
    with pytest.raises(ValueError):
        t.reselect(frame2, 7, InitPrompt(box=(0, 0, 1, 1), mask=np.zeros((H, W), bool)))
    assert t.tracks[7] is tr
    with pytest.raises(KeyError):
        t.reselect(frame2, 99, InitPrompt(box=(210, 80, 250, 120), mask=m2))
