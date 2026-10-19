"""물체를 엄지·새끼로 쥐고 검지·중지를 든 채 쓰는 클릭 (내려가서 물체에 닿으면 누름)."""

import numpy as np

from vision_input.hands.detector import HandFrame
from vision_input.hands.finger_click import FingerClickDetector
from vision_input.io.mouse import MouseController, MouseSettings
from vision_input.io.sink import VirtualSink

from .handkit import make_hand

FPS = 30
S = 0.15
TIPS = {"index": 8, "middle": 12, "ring": 16, "pinky": 20}
# 손가락 끝이 내려오면 닿는 물체 (손 크기 단위로 손 중심 아래쪽)
BOX = (0.3, 0.5 - 0.5 * S, 0.7, 0.5 + 0.6 * S)


def hand(down=None, cx=0.5, cy=0.5):
    """down: 손가락 이름 → 끝을 손 크기의 몇 배 내렸는지 (1.0 = 든 높이 전부)."""
    h = make_hand(cx, cy, S)
    for n, v in (down or {}).items():
        h.points[TIPS[n]] = h.points[TIPS[n]] + np.array([0.0, v * S], np.float32)
    return h


def run(det, seq, box=BOX, t0=0.0):
    return [det.update(hand(d), t0 + i / FPS, box) for i, d in enumerate(seq)]


UP = [{}] * 10
M, I = {"middle": .75}, {"index": .75}


def test_default_raised_posture_never_clicks():
    outs = run(FingerClickDetector(), UP * 3)
    assert not any(o.left or o.right for o in outs)


def test_middle_down_on_object_is_left_button_held_then_released():
    outs = run(FingerClickDetector(), UP + [M] * 6 + UP)
    assert any(o.left for o in outs) and not any(o.right for o in outs)
    assert not outs[-1].left
    assert [o.left for o in outs[len(UP):len(UP) + 6]][-1]  # 누르고 있는 동안 유지 (드래그 가능)


def test_index_down_on_object_is_right_button():
    outs = run(FingerClickDetector(), UP + [I] * 6 + UP)
    assert any(o.right for o in outs) and not any(o.left for o in outs)


def test_down_but_not_touching_object_is_ignored():
    far = (0.3, 0.9, 0.7, 0.95)
    outs = run(FingerClickDetector(), UP + [M] * 6 + UP, box=far)
    assert not any(o.left or o.right for o in outs)


def test_bare_hand_without_object_uses_down_only():
    outs = run(FingerClickDetector(), UP + [M] * 6 + UP, box=None)
    assert any(o.left for o in outs)


def test_whole_hand_curl_is_ignored():
    curl = {"index": .75, "middle": .75, "ring": .75}
    outs = run(FingerClickDetector(), UP + [curl] * 6 + UP)
    assert not any(o.left or o.right for o in outs)


def test_one_frame_dip_ignored():
    outs = run(FingerClickDetector(), UP + [M] + UP)
    assert not any(o.left for o in outs)


def test_starting_with_finger_already_down_does_not_click_until_raised_first():
    outs = run(FingerClickDetector(), [M] * 10)
    assert not any(o.left for o in outs)


def test_approach_freezes_cursor_then_press_freeze_expires():
    outs = run(FingerClickDetector(), UP + [{"middle": .3}] * 3 + [M] * 14)
    assert any(o.freeze for o in outs)
    assert not outs[-1].freeze
    assert any(o.left and not o.freeze for o in outs[-6:])  # 누른 채 이동 (드래그)


def test_losing_hand_resets():
    d = FingerClickDetector()
    run(d, UP + [M] * 4)
    o = d.update(None, 2.0)
    assert not (o.left or o.right or o.freeze)


def _ctl(**kw):
    sink = VirtualSink()
    c = MouseController(sink)
    c.configure(MouseSettings(**kw))
    return c, sink


def test_object_mode_picks_gripping_hand_nearest_the_object():
    c, sink = _ctl(mode="object", object_id=1, hand_clicks=True, coordinate_mode="image")
    far = make_hand(0.15, 0.5, S)
    near = hand()
    h = c._pick_hand([far, near], (0.5, 0.5))
    assert h is near


def test_hand_mode_default_uses_thumb_index_pinch():
    c, sink = _ctl(mode="hand", hand_control="air")
    for i in range(20):
        c.update(i / FPS, HandFrame(i / FPS, [make_hand(0.5, 0.5, S, pinch=0.2)]), None, False)
    assert sink.buttons["left"] and not sink.buttons["right"]
