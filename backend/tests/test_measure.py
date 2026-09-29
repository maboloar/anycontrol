"""마스크 측정과 각도 펼치기, 등록 판정."""

import cv2
import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vision_input.tracking.measure import AngleTracker, largest_component, mask_contour, measure_mask
from vision_input.tracking.register import (
    RegistrationError,
    choose_candidate,
    contrast_score,
    register,
    texture_score,
)
from vision_input.tracking.segment import SegResult


def rect_mask(cx, cy, w, h, ang, size=(640, 480)):
    m = np.zeros(size[::-1], np.uint8)
    pts = cv2.boxPoints(((cx, cy), (w, h), ang)).astype(np.int32)
    cv2.fillConvexPoly(m, pts, 1)
    return m.astype(bool)


@settings(max_examples=60, deadline=None)
@given(cx=st.floats(150, 490), cy=st.floats(150, 330), w=st.floats(60, 200), ratio=st.floats(1.6, 4.0),
       ang=st.floats(-89, 89))
def test_measure_recovers_center_area_and_axis(cx, cy, w, ratio, ang):
    h = w / ratio
    m = measure_mask(rect_mask(cx, cy, w, h, ang))
    assert m is not None
    assert abs(m.cx - cx) < 1.5 and abs(m.cy - cy) < 1.5
    # fillConvexPoly 는 꼭짓점을 정수로 자르고 경계 픽셀을 포함한다 → 둘레 한 바퀴(약 2(w+h))까지 허용
    assert abs(m.area - w * h) <= 2.2 * (w + h) + 8
    assert m.angle_valid
    d = (m.angle - ang + 90) % 180 - 90  # 180° 주기 비교
    assert abs(d) < 2.5
    assert m.elongation == pytest.approx(ratio, rel=0.15)


def test_round_object_has_invalid_angle():
    m = np.zeros((200, 200), np.uint8)
    cv2.circle(m, (100, 100), 40, 1, -1)
    r = measure_mask(m.astype(bool))
    assert r is not None and not r.angle_valid


def test_bottom_line_ignores_thin_protrusion():
    m = rect_mask(320, 240, 200, 60, 0)
    m[270:330, 318:322] = True  # 아래로 튀어나온 가는 선 (반사 줄무늬 등)
    r = measure_mask(m)
    assert abs(r.bottom_y - 270) < 3
    assert r.bottom_width > 150


@settings(max_examples=50, deadline=None)
@given(steps=st.lists(st.floats(-40, 40), min_size=1, max_size=60), start=st.floats(-89, 89))
def test_angle_tracker_unwraps_continuous_rotation(steps, start):
    """|프레임 간 회전| < 90° 이면 누적 각도를 정확히 복원한다."""
    t = AngleTracker()
    true = start
    t.update(((true + 90) % 180) - 90)
    for s in steps:
        true += s
        out = t.update(((true + 90) % 180) - 90)
    assert out == pytest.approx(true - (start - (((start + 90) % 180) - 90)), abs=1e-6)


def test_angle_tracker_holds_on_invalid():
    t = AngleTracker()
    t.update(10)
    assert t.update(80, valid=False) == 10


def test_largest_component_and_contour():
    m = rect_mask(200, 200, 100, 50, 0) | rect_mask(500, 400, 10, 10, 0)
    main, frac = largest_component(m)
    assert frac > 0.95 and not main[400, 500]
    c = mask_contour(main, 20)
    assert 3 <= len(c) <= 20


def test_texture_and_contrast_separate_plain_from_patterned():
    rng = np.random.default_rng(0)
    bg = np.full((360, 640, 3), 180, np.uint8)
    m = rect_mask(320, 180, 200, 120, 0, (640, 360))
    plain = bg.copy()
    plain[m] = (30, 30, 30)
    pat = plain.copy()
    noise = rng.integers(0, 255, (360, 640, 3), dtype=np.uint8)
    pat[m] = cv2.GaussianBlur(noise, (0, 0), 2)[m]
    g = lambda im: cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    assert texture_score(g(pat), m) > texture_score(g(plain), m) + 0.3
    assert contrast_score(plain, m) > 0.8
    same = bg.copy()
    assert contrast_score(same, m) < 0.1


class FakeSeg:
    name = "fake"

    def __init__(self, masks, scores):
        self.r = SegResult(masks, scores)

    def segment(self, frame, box=None, points=None):
        return self.r


def test_box_prompt_prefers_mask_that_fills_box():
    small = rect_mask(320, 240, 40, 30, 0)     # 물체 일부
    whole = rect_mask(320, 240, 200, 120, 0)   # 박스를 채움
    huge = np.ones((480, 640), bool)            # 배경 전체
    seg = SegResult([small, whole, huge], [0.95, 0.85, 0.9])
    assert choose_candidate(seg, (220, 180, 420, 300))[0] == 1


def test_register_rejects_tiny_and_huge_and_reports_candidates():
    frame = np.full((480, 640, 3), 128, np.uint8)
    with pytest.raises(RegistrationError):
        register(frame, FakeSeg([rect_mask(100, 100, 8, 8, 0)], [0.9]), box=(90, 90, 110, 110))
    with pytest.raises(RegistrationError):
        register(frame, FakeSeg([np.ones((480, 640), bool)], [0.9]), box=(0, 0, 640, 480))
    a, b = rect_mask(320, 240, 200, 120, 0), rect_mask(320, 240, 150, 100, 0)
    r = register(frame, FakeSeg([a, b], [0.9, 0.8]), box=(220, 180, 420, 300))
    assert len(r.candidates) == 2 and r.candidate_index == 0
    r2 = register(frame, FakeSeg([a, b], [0.9, 0.8]), box=(220, 180, 420, 300), candidate=1)
    assert r2.mask.sum() < r.mask.sum()


def test_register_warns_on_fragments_and_low_score():
    frame = np.full((480, 640, 3), 128, np.uint8)
    frag = rect_mask(200, 240, 120, 100, 0) | rect_mask(450, 240, 100, 100, 0)
    r = register(frame, FakeSeg([frag], [0.4]), box=(100, 150, 520, 330))
    assert any("조각" in w for w in r.warnings) and any("신뢰도" in w for w in r.warnings)
