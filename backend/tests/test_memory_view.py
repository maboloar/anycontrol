"""물체 기억 보기: 기록 순간의 모습 잘라 두기, 개수 제한, 트래커·API 노출."""

import base64

import cv2
import numpy as np
import pytest

from vision_input.tracking import InitPrompt, TrackState
from vision_input.tracking import memory_view as mv
from vision_input.tracking.vi_tracker import TrackerConfig, ViTracker


def scene(cx=320, cy=200, size=(360, 640)):
    img = np.full((*size, 3), 90, np.uint8)
    cv2.rectangle(img, (cx - 40, cy - 25), (cx + 40, cy + 25), (40, 60, 220), -1)
    m = np.zeros(size, bool)
    m[cy - 25:cy + 26, cx - 40:cx + 41] = True
    return img, m


def decode(uri: str) -> np.ndarray:
    raw = base64.b64decode(uri.split(",", 1)[1])
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


def test_capture_crops_object_with_margin_and_limits_size():
    img, m = scene()
    s = mv.capture(img, m, "registration", 1.0)
    assert s is not None and max(s.image.shape[:2]) <= mv.THUMB
    assert s.image.shape[:2] == s.mask.shape
    assert 0.2 < s.mask.mean() < 0.8           # 물체 + 여백
    assert mv.capture(img, np.zeros_like(m), "anchor", 0.0) is None
    assert mv.capture(img, m[:10], "anchor", 0.0) is None  # 크기가 다르면 버린다


def test_remember_keeps_per_kind_limits():
    img, m = scene()
    store: list = []
    for i in range(5):
        mv.remember(store, mv.capture(img, m, "anchor", float(i)))
    mv.remember(store, mv.capture(img, m, "registration", 0.0))
    mv.remember(store, mv.capture(img, m, "registration", 9.0))
    kinds = [s.kind for s in store]
    assert kinds.count("anchor") == mv.KEEP["anchor"] and kinds.count("registration") == 1
    assert [s.t for s in store if s.kind == "anchor"] == [2.0, 3.0, 4.0]   # 오래된 것부터 교체
    assert [s.t for s in store if s.kind == "registration"] == [9.0]


def test_render_outputs_decodable_images_and_palette_matches_object_color():
    img, m = scene()
    d = mv.describe([mv.capture(img, m, "registration", 0.0)], now=2.0)
    assert d[0]["kind"] == "registration" and d[0]["age_s"] == 2.0
    pic = decode(d[0]["image"])
    assert pic is not None and pic.size > 0
    from vision_input.tracking.reacquire import make_memory
    from vision_input.tracking.tier0 import A_BINS, B_BINS, L_BINS, ColorModel, _lab_index

    mem = make_memory(m, _lab_index(img), ColorModel.NB)
    pal = mv.palette(mem.color, L_BINS, A_BINS, B_BINS)
    r, g, b = (int(pal[0]["hex"][i:i + 2], 16) for i in (1, 3, 5))
    assert r > 150 and b < 120                  # 빨간 물체 (BGR 40,60,220)
    assert decode(mv.render_template(mem.template)) is not None


def test_vi_tracker_memory_reports_registration_and_shape():
    img, m = scene()
    tr = ViTracker(TrackerConfig(tier1="off"))
    tr.add(img, 1, InitPrompt(mask=m))
    tr.step(img, 1 / 30)
    mem = tr.memory(1)
    assert mem["state"] == TrackState.TRACKING.value and mem["lost_for_s"] is None
    assert [s["kind"] for s in mem["snapshots"]] == ["registration"]
    # 시각을 모르고(새 소스) 등록해도 첫 프레임 시각을 받아 나이가 0 에서 시작한다
    assert mem["snapshots"][0]["t"] == pytest.approx(1 / 30, abs=1e-3) and mem["snapshots"][0]["age_s"] == 0.0
    tr.step(img, 3.0)
    assert tr.memory(1)["snapshots"][0]["age_s"] == pytest.approx(3.0 - 1 / 30, abs=0.1)
    assert mem["shape"]["elongation"] > 1.2 and mem["shape"]["palette"]
    assert mem["tier1"] is None and not mem["reacquire"]["enabled"]
    with pytest.raises(KeyError):
        tr.memory(99)


def test_reselect_replaces_registration_view():
    img, m = scene()
    tr = ViTracker(TrackerConfig(tier1="off"))
    tr.add(img, 1, InitPrompt(mask=m))
    img2, m2 = scene(cx=200, cy=150)
    tr.step(img2, 1 / 30)
    tr.reselect(img2, 1, InitPrompt(mask=m2))
    snaps = tr.tracks[1].memory_views
    assert len(snaps) == 1 and snaps[0].kind == "registration"
