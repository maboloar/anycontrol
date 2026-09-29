"""손 인식 엔진 선택 (MediaPipe / Apple Vision): 관절 변환, 집게 특징, 엔진 전환 API."""

import numpy as np
import pytest

from vision_input.hands import detector as det
from vision_input.hands import vision as vn
from vision_input.hands.gestures import GestureConfig, GestureRecognizer, features

from .handkit import make_hand
from .test_mouse import client_hands  # noqa: F401  (fixture 재사용)


def joints_of(hand, conf=0.9, skip=()):
    """Hand → hand_from_joints 입력 ({번호: (x, y, 신뢰도)})."""
    return {k: (float(p[0]), float(p[1]), conf) for k, p in enumerate(hand.points) if k not in skip}


def test_hand_from_joints_roundtrip_and_chirality():
    h = make_hand(0.5, 0.5, 0.2)
    for ch, name in ((-1, "Left"), (1, "Right"), (0, "Unknown")):
        out = vn.hand_from_joints(joints_of(h), ch)
        assert out is not None and out.handedness == name
        assert np.allclose(out.points, h.points, atol=1e-6)
        assert out.depth.shape == (21,) and not out.depth.any()  # Vision 은 깊이를 주지 않는다
        assert out.score == pytest.approx(0.9)


def test_hand_from_joints_needs_gesture_joints():
    h = make_hand(0.5, 0.5, 0.2)
    for need in vn.NEEDED:  # 제스처가 쓰는 점이 하나라도 없으면 손으로 인정하지 않는다
        assert vn.hand_from_joints(joints_of(h, skip=(need,)), 1) is None
    low = joints_of(h)
    low[8] = (*low[8][:2], 0.01)  # 신뢰도가 너무 낮은 점은 없는 것으로 본다
    assert vn.hand_from_joints(low, 1) is None
    assert vn.hand_from_joints(joints_of(h, conf=0.2), 1) is None  # 평균 신뢰도 미만


def test_hand_from_joints_fills_optional_joints():
    h = make_hand(0.5, 0.5, 0.2)
    out = vn.hand_from_joints(joints_of(h, skip=(1, 2, 3, 7, 11, 15, 19)), 1)  # 엄지 관절·DIP 는 없어도 된다
    assert out is not None
    assert np.allclose(out.points[[0, 4, 5, 6, 8, 12, 16, 20]], h.points[[0, 4, 5, 6, 8, 12, 16, 20]], atol=1e-6)
    assert np.allclose(out.points[7], h.points[6])  # 빠진 DIP 는 앞 관절(PIP) 위치로
    assert np.isfinite(out.points).all()


def test_pinch_and_gestures_work_on_vision_hands():
    """Vision 손(깊이 0·chirality)도 집게·오른쪽 집게·스크롤 제스처가 같은 로직으로 동작한다."""
    cfg = GestureConfig()

    def as_vision(h):
        return vn.hand_from_joints(joints_of(h), 1)

    assert features(as_vision(make_hand(0.5, 0.5, 0.2, pinch=0.1)), cfg).pinch_index < cfg.pinch_on
    assert features(as_vision(make_hand(0.5, 0.5, 0.2, pinch=1.0)), cfg).pinch_index > cfg.pinch_off
    rec = GestureRecognizer()
    states = [rec.update(as_vision(make_hand(0.5, 0.5, 0.2, pinch=p)), i / 30).gesture
              for i, p in enumerate([1.0, 1.0, 0.1, 0.1, 0.1, 0.1, 1.0, 1.0, 1.0])]
    assert states[:2] == ["move", "move"] and "left" in states and states[-1] == "move"
    rec = GestureRecognizer()
    right = [rec.update(as_vision(make_hand(0.5, 0.5, 0.2, pinch=1.0, pinch_middle=0.1)), i / 30).gesture
             for i in range(6)]
    assert right[-1] == "right"
    rec = GestureRecognizer()
    sc = [rec.update(as_vision(make_hand(0.5, 0.5 + 0.01 * i, 0.2, scroll_pose=True)), i / 30) for i in range(8)]
    assert sc[-1].gesture == "scroll" and sum(o.scroll for o in sc) > 0


def test_available_backends_and_default(monkeypatch):
    monkeypatch.setattr(det, "mediapipe_available", lambda: True)
    monkeypatch.setattr(vn, "available", lambda: True)
    assert det.available_backends() == ["mediapipe", "vision"]
    monkeypatch.delenv("VI_HAND_BACKEND", raising=False)
    assert det.default_backend() == "vision"
    monkeypatch.setenv("VI_HAND_BACKEND", "mediapipe")
    assert det.default_backend() == "mediapipe"
    monkeypatch.delenv("VI_HAND_BACKEND", raising=False)
    monkeypatch.setattr(vn, "available", lambda: False)
    assert det.available_backends() == ["mediapipe"] and det.default_backend() == "mediapipe"
    monkeypatch.setattr(det, "mediapipe_available", lambda: False)
    assert det.available_backends() == [] and not det.available()
    monkeypatch.setenv("VI_HAND_BACKEND", "bogus")
    assert det.default_backend() == "vision"


def test_worker_set_backend_validates_and_restarts(monkeypatch):
    monkeypatch.setattr(det, "available_backends", lambda: ["mediapipe", "vision"])
    monkeypatch.setattr(det, "make_detector", lambda b: type("D", (), {"detect": lambda s, i, t: det.HandFrame(t, []),
                                                                       "close": lambda s: None})())
    w = det.HandWorker("mediapipe")
    with pytest.raises(ValueError):
        w.set_backend("hybrid")
    w.set_backend("mediapipe")  # 같으면 아무 일 없음
    w.start()
    assert w.running
    w.set_backend("vision")
    assert w.backend == "vision" and w.running  # 돌고 있었으면 새 엔진으로 다시 시작
    w.stop()
    w.set_backend("mediapipe")
    assert w.backend == "mediapipe" and not w.running  # 꺼져 있었으면 켜지 않는다


def test_tracking_api_hand_backend(client_hands):  # noqa: F811
    c, hands = client_hands
    r = c.get("/api/tracking").json()
    assert r["hand_backend"] == "vision" and isinstance(r["hand_backends"], list)
    r = c.put("/api/tracking", json={"hand_backend": "mediapipe"}).json()
    assert r["hand_backend"] == "mediapipe" and hands.backend == "mediapipe"
    assert c.put("/api/tracking", json={"hand_backend": "hybrid"}).status_code == 422
    assert c.get("/api/mouse").json()["hand_backend"] == "mediapipe"


@pytest.mark.skipif(not vn.available(), reason="Apple Vision 없음 (macOS 전용)")
def test_apple_vision_detector_runs_on_blank_image():
    d = vn.AppleVisionDetector()
    fr = d.detect(np.zeros((360, 640, 3), np.uint8), 0.0)  # 손이 없는 영상: 오류 없이 빈 결과
    assert fr.hands == [] and fr.ms > 0
