"""책상 상대 이동과 카메라 방향 회귀 테스트."""

import numpy as np
import pytest

from vision_input.hands.detector import Hand, HandFrame
from vision_input.io.mouse import MouseController, MouseSettings
from vision_input.io.sink import VirtualSink
from vision_input.io.touchpad import TouchSurface

from .handkit import make_hand


def contact_hand(x: float, y: float, size: float = .12, *, touch: bool = True,
                 scroll: bool = False) -> Hand:
    h = make_hand(x, y, size, scroll_pose=scroll)
    h.points[8] = [x, y]
    h.points[6] = [x, y - (.025 if touch else -.065)]
    if scroll:
        h.points[12] = [x + .025, y]
        h.points[10] = [x + .025, y - .025]
    return h


def run(c: MouseController, hand: Hand, i: int) -> None:
    t = i / 30
    c.update(t, HandFrame(t, [hand]), None, False)


def test_quad_touchpad_moves_only_while_contact_and_does_not_jump_on_retouch():
    sink = VirtualSink()
    c = MouseController(sink)
    c.configure(MouseSettings(mode="hand", hand_control="touchpad", mirror=False, touch_depth_blend=0,
                              touch_deadzone=0, touch_sensitivity=1))
    c.set_surface(TouchSurface.quad([[.1, .2], [.9, .2], [.9, .8], [.1, .8]]))
    run(c, contact_hand(.4, .55), 0)
    run(c, contact_hand(.4, .55), 1)
    run(c, contact_hand(.45, .55), 2)
    assert sink.x > .5
    moved = sink.x
    run(c, contact_hand(.75, .55, touch=False), 3)
    run(c, contact_hand(.75, .55, touch=False), 4)
    assert sink.x == moved
    run(c, contact_hand(.7, .55), 5)
    run(c, contact_hand(.7, .55), 6)
    assert sink.x == moved
    run(c, contact_hand(.72, .55), 7)
    assert sink.x > moved


def test_near_camera_moves_up_and_can_be_inverted():
    sink = VirtualSink()
    c = MouseController(sink)
    c.configure(MouseSettings(mode="hand", hand_control="touchpad", mirror=False, touch_depth_blend=0, touch_deadzone=0))
    c.set_surface(TouchSurface.quad([[.1, .2], [.9, .2], [.9, .8], [.1, .8]]))
    for i in range(3):
        run(c, contact_hand(.5, .55 + .02 * max(0, i - 1)), i)
    assert sink.y < .5
    c.configure(c.settings.model_copy(update={"invert_y": True}))
    for i in range(3, 6):
        run(c, contact_hand(.5, .55 + .02 * max(0, i - 4)), i)
    assert sink.y > .5 - .04


def test_horizontal_line_uses_scale_for_depth():
    sink = VirtualSink()
    c = MouseController(sink)
    c.configure(MouseSettings(mode="hand", hand_control="touchpad", mirror=False, touch_depth_blend=1,
                              touch_deadzone=0))
    c.set_surface(TouchSurface.line([[.1, .6], [.9, .6]]))
    run(c, contact_hand(.5, .65, .1), 0)
    run(c, contact_hand(.5, .65, .1), 1)
    run(c, contact_hand(.5, .65, .12), 2)
    assert sink.y < .5  # 손이 커지면 카메라에 가까워졌으므로 위로


def test_pen_relative_only_on_contact_and_release():
    sink = VirtualSink()
    c = MouseController(sink)
    c.configure(MouseSettings(mode="object", object_id=1, hand_clicks=False, mirror=False,
                              pen_sensitivity=1, pen_depth_blend=0))
    c.update(0, None, (.4, .6), True, obj_pressed=False, obj_is_pen=True)
    c.update(.03, None, (.5, .6), True, obj_pressed=True, obj_is_pen=True)
    assert sink.x == pytest.approx(.5)
    c.update(.06, None, (.55, .65), True, obj_pressed=True, obj_is_pen=True)
    assert sink.x > .5 and sink.y < .5
    x = sink.x
    c.update(.09, None, (.8, .8), True, obj_pressed=False, obj_is_pen=True)
    c.update(.12, None, (.85, .8), True, obj_pressed=True, obj_is_pen=True)
    assert sink.x == x
    assert sink.buttons["left"]
    c.update(.15, None, None, False, obj_pressed=False, obj_is_pen=True)
    assert not sink.buttons["left"]


def test_invalid_line_does_not_change_surface():
    original = TouchSurface.line([[.1, .5], [.9, .5]])
    assert original.contains(np.array([.5, .6]), 0)
    with pytest.raises(ValueError):
        TouchSurface.line([[.5, .5], [.51, .5]])


def test_slow_movement_accumulates_through_deadzone():
    sink = VirtualSink()
    c = MouseController(sink)
    c.configure(MouseSettings(mode="hand", hand_control="touchpad", mirror=False, smoothing=10,
                              touch_depth_blend=0, touch_deadzone=.004))
    c.set_surface(TouchSurface.quad([[.1, .2], [.9, .2], [.9, .8], [.1, .8]]))
    for i in range(30):
        run(c, contact_hand(.4 + .001 * i, .55), i)
    assert sink.x > .52
