"""수평 카메라 펜 접촉 (pen_floor): 바닥 모델, 책상 모서리, 상태기계, PenTracker 통합."""

import importlib.util
import math
from pathlib import Path

import cv2
import numpy as np
import pytest

from vision_input.pen import PenConfig, PenTracker
from vision_input.pen_floor import FloorConfig, FloorContact, FloorModel, TableEdge, pen_geometry, table_like
from vision_input.tracking import TrackState
from vision_input.tracking.api import Pose, TrackOutput

DESK_BGR = (150, 190, 215)   # 밝은 베이지 책상
WALL_BGR = (70, 60, 55)      # 어두운 무채색 배경
K, C = 3.0, -510.0           # 접촉 직선 d = K·w − C (drift off 라 기준선 y = 0): w=30 이면 y=600


def scene(tip, w, edge_y=400, tilt=0.0, shadow=None, size=(720, 1280)):
    """책상(아래) + 배경(위) + 회색 펜. 펜은 위로 뻗는다."""
    h, W = size
    img = np.empty((h, W, 3), np.uint8)
    img[:] = DESK_BGR
    for x in range(W):
        img[: int(edge_y + tilt * x), x] = WALL_BGR
    if shadow is not None:
        cv2.circle(img, shadow, 40, (60, 85, 110), -1)  # 같은 색상, 어두운 그림자
    tail = (int(tip[0] - 120), int(tip[1] - 300))
    mask = np.zeros((h, W), np.uint8)
    cv2.line(mask, tail, (int(tip[0]), int(tip[1])), 1, int(round(w)))
    img[mask > 0] = (95, 95, 100)
    return img, mask.astype(bool), tail


W_MEAS = 31.96  # cv2.line 두께 30 의 최대 내접원 지름 (래스터화로 조금 크다)


def contact_y(w):
    """굵기 w(그린 두께)인 펜이 닿았을 때 펜촉 y. 판정은 잰 굵기를 쓰므로 W_MEAS 로 계산한다."""
    return K * (W_MEAS if w == 30 else w) - C


def ready_detector(**kw):
    det = FloorContact(FloorConfig(drift="off", use_shadow=False, min_samples=10 ** 6, **kw))
    det.floor.k, det.floor.c, det.floor.sigma = K, C, 0.08
    return det


def feed(det, tip_y, w=30.0, t=0.0, x=640.0):
    img, mask, tail = scene((x, tip_y), w)
    tip = np.array([x, tip_y])
    u = tip - np.array(tail, float)
    u /= np.linalg.norm(u)
    return det.process(img, cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), mask, tip, u, t)


# ---------------------------------------------------------------- 바닥 모델
def test_floor_model_recovers_contact_line_despite_hover_points():
    rng = np.random.default_rng(1)
    m = FloorModel(min_samples=50, refit_every=10 ** 9)
    for _ in range(400):
        w = rng.uniform(25, 70)
        touching = rng.random() < 0.5
        d = K * w - C + (rng.normal(0, 0.05 * w) if touching else -rng.uniform(0.4, 3.0) * w)
        m.buf.append((w, d, 1.0, 0.0))
    assert m.fit()
    assert m.k == pytest.approx(K, rel=0.08)
    assert m.sigma is not None and m.sigma < 0.12
    assert abs(m.hover(40, K * 40 - C)) < 0.1     # 닿음 → 0
    assert m.hover(40, K * 40 - C - 40) > 0.8     # 펜 지름 하나만큼 위 → 약 1


def test_floor_model_needs_depth_variety():
    m = FloorModel(min_samples=10)
    for _ in range(60):
        m.buf.append((40.0, K * 40 - C, 1.0, 0.0))
    assert not m.fit() and not m.ready


# ---------------------------------------------------------------- 책상
def test_table_like_separates_desk_shadow_and_background():
    img, _, _ = scene((640, 600), 30, shadow=(300, 600))
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    ref = cv2.cvtColor(np.uint8([[DESK_BGR]]), cv2.COLOR_BGR2LAB)[0, 0].astype(float)
    m = table_like(lab, (ref[0] * 100 / 255, ref[1] - 128, ref[2] - 128))
    assert m[650, 1000] and m[600, 300]       # 책상, 그림자
    assert not m[100, 1000]                   # 배경


def test_table_edge_tracks_far_edge_and_slow_tilt():
    te = TableEdge(every=1)
    for i in range(20):
        img, mask, _ = scene((640, 600), 30, edge_y=400 + i, tilt=0.01)
        te.update(img, mask)
    assert te.line is not None
    a, b = te.line
    assert a == pytest.approx(0.01, abs=0.01)
    assert te.edge_y(640) == pytest.approx(419 + 6.4, abs=6)


# ---------------------------------------------------------------- 상태기계
def test_contact_enters_after_debounce_and_lifts_on_rise():
    det = ready_detector()
    t, dt = 0.0, 1 / 30
    assert not feed(det, contact_y(30) - 60, t=t).contact  # 공중
    states = []
    for _ in range(8):
        t += dt
        states.append(feed(det, contact_y(30), t=t).contact)
    assert states[-1] and not states[0]                     # 굵기 안정 + 디바운스 뒤 진입
    for _ in range(6):
        t += dt
        d = feed(det, contact_y(30) - 0.8 * 30, t=t)        # 0.8D 들어 올림
    assert not d.contact


def test_slow_bias_while_sliding_is_absorbed_by_baseline():
    det = ready_detector()
    t = 0.0
    for _ in range(10):
        t += 1 / 30
        feed(det, contact_y(30), t=t)
    assert det.state
    for i in range(60):  # 2초에 걸쳐 0.4D 만큼 천천히 '떠 보이는' 자세 편향
        t += 1 / 30
        d = feed(det, contact_y(30) - 0.4 * 30 * i / 59, t=t)
    assert d.contact


def test_dropout_holds_contact_then_resumes_or_times_out():
    det = ready_detector()
    t = 0.0
    for _ in range(10):
        t += 1 / 30
        feed(det, contact_y(30), t=t)
    assert det.state
    for _ in range(4):  # 0.13초 분할 탈락
        t += 1 / 30
        dec = det.dropout(t)
        assert dec.contact and dec.holding
    t += 1 / 30
    assert feed(det, contact_y(30), t=t).contact            # 같은 곳에서 다시 보임 → 같은 접촉
    for _ in range(15):  # 0.5초 탈락 > memory_s
        t += 1 / 30
        dec = det.dropout(t)
    assert not dec.contact


def test_reappearing_elsewhere_ends_held_contact():
    det = ready_detector()
    t = 0.0
    for _ in range(10):
        t += 1 / 30
        feed(det, contact_y(30), t=t)
    t += 1 / 30
    det.dropout(t)
    t += 1 / 30
    assert not feed(det, contact_y(30), t=t, x=900).contact


def test_pen_geometry_measures_barrel_width():
    _, mask, tail = scene((640, 600), 30)
    tip = np.array([640.0, 600.0])
    u = (tip - tail) / np.linalg.norm(tip - np.array(tail, float))
    g = pen_geometry(mask, tip, u, 170)
    assert g is not None and g.w_ok and g.w == pytest.approx(30, abs=4)


# ---------------------------------------------------------------- PenTracker 통합
def _out(mask):
    ys, xs = np.nonzero(mask)
    return TrackOutput(TrackState.TRACKING, None, Pose(float(xs.mean()), float(ys.mean())), mask, 1.0)


def test_pen_tracker_floor_backfills_stroke_start_and_holds_through_dropout():
    tip = (640.0, contact_y(30))
    img, mask, tail = scene(tip, 30)
    p = PenTracker(tip, tail, PenConfig(contact_method="floor", floor_drift="off", floor_shadow=False,
                                        tip_min_cutoff=1000, floor_min_frames=3))
    p.floor.floor.min_samples = 10 ** 6
    t = 1 / 30
    p.update(img, _out(mask), t)
    # PenTracker 펜촉(경계 보정, 둥근 끝 포함)이 이 자세에서 닿은 것으로 보이게 접촉 직선을 맞춘다
    w0, d0 = p.floor.info["w"], p.floor.info["d"]
    p.floor.floor.k, p.floor.floor.c, p.floor.floor.sigma = K, K * w0 - d0, 0.08
    for _ in range(11):
        t += 1 / 30
        p.update(img, _out(mask), t)
    assert p.contact and p.pressed
    # 진입까지 걸린 디바운스 프레임의 점도 획에 들어 있다 (소급)
    assert p.cur_t[0] < p.cur_t[-1] - 1e-6 and len(p.cur) == len(p.cur_t)
    first = p.cur_t[0]
    t += 1 / 30
    p.update(img, TrackOutput(TrackState.OCCLUDED, None, Pose(0, 0)), t)
    assert p.contact and p.uncertain and p.pressed          # 탈락 중 입력 유지
    t += 1 / 30
    p.update(img, _out(mask), t)
    assert p.contact and p.cur_t[0] == first                # 같은 획이 이어짐


def test_floor_is_default_and_legacy_is_unchanged_when_selected():
    assert PenTracker((700, 500), (600, 200)).floor_mode and PenConfig().floor_depth_roll
    p = PenTracker((700, 500), (600, 200), PenConfig(contact_method="legacy"))
    assert p.cfg.contact_method == "legacy" and not p.floor_mode
    p.contact, p.uncertain = True, True
    assert not p.pressed                                   # legacy: 불확실하면 입력 차단 (기존과 같음)


# ---------------------------------------------------------------- 벤치 지표
def _bench_metrics():
    path = Path(__file__).resolve().parents[2] / "bench" / "pen" / "metrics.py"
    spec = importlib.util.spec_from_file_location("pen_bench_metrics", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_bench_metrics_events_and_ignore_radius():
    m = _bench_metrics()
    ref = {"contact_intervals": [[10, 19]], "ignore_radius": 2}
    pred = [0] * 12 + [1] * 9 + [0] * 9          # 2 프레임 늦게 시작, 1 프레임 늦게 끝
    r = m.score(pred, ref)
    assert r["events"][0][2:] == (2, 1)
    assert r["fp"] == 0 and r["fn"] == 0 and math.isclose(r["f1"], 1.0)  # 경계 ±2 는 채점 제외
    assert m.densify({3: True, 6: False}, 8) == [0, 0, 0, 1, 1, 1, 0, 0]


def test_pen_api_accepts_only_known_contact_methods():
    from pydantic import ValidationError

    from vision_input.server.objects import PenBody

    assert PenBody(contact_method="floor").contact_method == "floor"
    assert PenBody().contact_method is None
    with pytest.raises(ValidationError):
        PenBody(contact_method="magic")


# ---------------------------------------------------------------- 바닥 평면 (카메라 롤)
A_ROLL = 100.0      # px: 프레임 폭 전체에 걸친 좌우 기울기 (롤 약 4.5° @1280)


def plane_samples(n=500, seed=3, a=A_ROLL, hover_frac=0.5):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        w = rng.uniform(25, 70)
        x = rng.uniform(-0.45, 0.45)
        d = K * w + a * x - C
        if rng.random() < hover_frac:
            d -= rng.uniform(0.4, 3.0) * w
        else:
            d += rng.normal(0, 0.03 * w)
        out.append((w, d, 1.0, x))
    return out


def fitted(roll: bool):
    m = FloorModel(min_samples=50, refit_every=10 ** 9, roll=roll)
    m.a_max_px = 0.5 * 1280
    m.buf.extend(plane_samples())
    assert m.fit()
    return m


def test_plane_model_recovers_roll_term_and_line_model_cannot():
    plane, line = fitted(True), fitted(False)
    assert plane.k == pytest.approx(K, rel=0.08) and plane.a == pytest.approx(A_ROLL, rel=0.2)
    assert line.a == 0.0
    # 닿은 펜의 hover: 좌우 어느 쪽에서도 0 근처 (평면), 직선 모델은 좌우 끝에서 어긋난다
    for x in (-0.4, 0.0, 0.4):
        w = 45.0
        d = K * w + A_ROLL * x - C
        assert abs(plane.hover(w, d, x)) < 0.15
    assert abs(line.hover(45.0, K * 45 + A_ROLL * 0.4 - C, 0.4)) > 0.25


def test_three_touches_define_the_plane_exactly():
    m = FloorModel(roll=True)
    m.a_max_px = 640
    pts = [(65.0, K * 65 + A_ROLL * -0.35 - C, -0.35),     # 가까운 곳, 왼쪽
           (28.0, K * 28 + A_ROLL * 0.0 - C, 0.0),         # 먼 곳, 가운데
           (45.0, K * 45 + A_ROLL * 0.35 - C, 0.35)]       # 중간, 오른쪽
    assert m.set_touches(pts)
    assert (m.k, m.a, m.c) == pytest.approx((K, A_ROLL, C), rel=1e-6)
    assert m.hover(50.0, K * 50 + A_ROLL * 0.2 - C, 0.2) == pytest.approx(0.0, abs=1e-6)
    assert len(m.anchors) == 3
    # 거리가 한 가지뿐이면 평면을 정하지 못한다
    assert not FloorModel(roll=True).set_touches([(40.0, 10.0, -0.2), (40.5, 11.0, 0.2), (40.2, 10.5, 0.0)])


def test_floor_map_value_grows_towards_the_camera():
    m = fitted(True)
    ys = [100.0, 300.0, 500.0, 700.0]                       # 화면 위(먼 곳) → 아래(가까운 곳)
    ws = [m.contact_w(y, 0.0) for y in ys]
    assert all(b > a for a, b in zip(ws, ws[1:]))             # 가까울수록 접촉한 펜이 굵다
    # contact_w 와 contact_d 는 서로 역
    assert m.contact_w(m.contact_d(50.0, 0.2), 0.2) == pytest.approx(50.0)


def test_probe_reads_width_and_position_without_touching_state():
    det = ready_detector()
    img, mask, tail = scene((900.0, contact_y(30)), 30)
    tip = np.array([900.0, contact_y(30)])
    u = tip - np.array(tail, float)
    u /= np.linalg.norm(u)
    before = (det.state, len(det.floor.buf), det.on_cnt)
    w, d, x = det.probe(img, cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), mask, tip, u)
    assert w == pytest.approx(W_MEAS, abs=3) and x == pytest.approx(900 / 1280 - 0.5)
    assert (det.state, len(det.floor.buf), det.on_cnt) == before
    assert det.probe(img, cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), np.zeros_like(mask), tip, u) is None
    assert det.set_touch_plane([(65.0, K * 65 - C, -0.3), (28.0, K * 28 - C, 0.0), (45.0, K * 45 - C, 0.3)])
    assert det.floor.k == pytest.approx(K, rel=1e-6)


# ---------------------------------------------------------------- 바닥 그라데이션 맵 (개발자 보기)
def _decode_png(uri: str):
    import base64
    raw = base64.b64decode(uri.split(",", 1)[1])
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)


def test_floor_map_is_a_near_bright_far_dark_gradient_only_on_the_floor():
    det = ready_detector()
    img, mask, _ = scene((640.0, 600.0), 30)
    det.table.update(img, mask)                       # 책상 색 기준 학습
    det.floor.a = 0.0
    m = det.render_map(img, mask)
    assert m["ready"] and m["size"] == [1280, 720] and m["k"] == pytest.approx(K)
    g = _decode_png(m["image"])
    o = _decode_png(m["overlay"])
    assert g.ndim == 2 and o.shape[2] == 4
    sh = g.shape[0]
    col = g[:, 40]                                                         # 펜이 없는 왼쪽 열
    floor_rows = np.nonzero(col > 0)[0]
    assert floor_rows.size > 20 and floor_rows.min() > 0.6 * sh            # 벽(위쪽)은 검정, 바닥은 아래쪽에만
    assert col[floor_rows[-1]] > col[floor_rows[0]]                        # 가까울수록(아래) 밝다
    assert o[..., 3][floor_rows[-1], 40] > 0 and o[..., 3][5, 40] == 0     # 오버레이는 바닥에서만 보인다
    assert m["w_range"][1] > m["w_range"][0]


def test_floor_map_reports_why_it_is_not_ready():
    det = ready_detector()
    img, mask, _ = scene((640.0, 600.0), 30)
    det.floor.k = None
    m = det.render_map(img, mask)
    assert m["ready"] is False and m["reason"] == "learning"


def test_pen_tracker_floor_map_requires_floor_contact_method():
    tip = (640.0, contact_y(30))
    img, mask, tail = scene(tip, 30)
    p = PenTracker(tip, tail, PenConfig(contact_method="legacy"))
    assert p.floor_map(img, mask) == {"ready": False, "reason": "contact_method"}
    p2 = PenTracker(tip, tail, PenConfig(contact_method="floor", floor_drift="off"))
    assert p2.floor_map(None, None)["reason"] == "no_frame"
    out = p2.floor_map(img, mask)
    assert out["ready"] is False and out["reason"] == "learning"
    assert len(out["tip"]) == 2 and all(0 <= v <= 1 for v in out["tip"])         # 등록한 펜촉 위치 (정규화)
