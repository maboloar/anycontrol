import numpy as np
import pytest

from vision_input.hands.detector import HandFrame
from vision_input.io.depth import palm_scale
from vision_input.io.mouse import MouseController, MouseSettings
from vision_input.io.sink import VirtualSink
from vision_input.io.touchpad import TouchSurface
from .handkit import make_hand


def controller(**settings):
    sink = VirtualSink()
    mouse = MouseController(sink)
    mouse.configure(MouseSettings(**settings))
    return mouse, sink


def test_defaults_use_depth_and_leave_x_unmirrored():
    s = MouseSettings()
    assert s.hand_control == "depth" and s.coordinate_mode == "depth" and not s.mirror


def test_object_image_height_does_not_move_y_but_approach_and_retreat_do():
    c, s = controller(mode="object", object_id=1, hand_clicks=False, smoothing=10)
    c.update(0, None, (.4, .2), True, obj_scale=1)
    c.update(.1, None, (.5, .8), True, obj_scale=1)
    assert s.x > .5 and s.y == .5
    c.update(.2, None, (.5, .8), True, obj_scale=1.15)
    assert s.y < .5
    near = s.y
    for i in range(3, 9):
        c.update(i / 10, None, (.5, .8), True, obj_scale=1)
    assert s.y > near


def test_hand_image_height_does_not_move_y_but_palm_scale_does():
    c, s = controller(mode="hand", smoothing=10)
    for i, (y, size) in enumerate([(.4, .1), (.6, .1), (.6, .12)]):
        c.update(i / 10, HandFrame(i / 10, [make_hand(.5, y, size)]), None, False)
        if i < 2:
            assert s.y == .5
    assert s.y < .5


def test_palm_scale_ignores_finger_pinching():
    h = make_hand(.5, .5, .1)
    baseline = palm_scale(h)
    h.points[[4, 8, 12, 16, 20]] = .5
    assert palm_scale(h) == baseline


def test_lost_object_and_reappearance_do_not_jump_cursor():
    c, s = controller(mode="object", object_id=1, hand_clicks=False)
    c.update(0, None, (.4, .6), True, obj_scale=1)
    c.update(.03, None, (.45, .6), True, obj_scale=1.02)
    position = (s.x, s.y)
    c.update(.06, None, None, False)
    c.update(.09, None, (.8, .2), True, obj_scale=1.4)
    assert (s.x, s.y) == position


def test_calibrated_plane_uses_contact_point_instead_of_object_size():
    c, s = controller(mode="object", object_id=1, hand_clicks=False, smoothing=10)
    c.set_surface(TouchSurface.quad([[.1, .2], [.9, .2], [.9, .8], [.1, .8]]))
    c.update(0, None, (.5, .5), True, obj_scale=1, obj_box=(.4, .4, .6, .6))
    c.update(.1, None, (.5, .5), True, obj_scale=1.3, obj_box=(.4, .4, .6, .6))
    assert s.y == pytest.approx(.5)
    c.update(.2, None, (.5, .5), True, obj_scale=1.3, obj_box=(.4, .4, .6, .65))
    assert s.y < .5


def test_invert_y_reverses_approach():
    c, s = controller(mode="object", object_id=1, hand_clicks=False, invert_y=True)
    c.update(0, None, (.5, .5), True, obj_scale=1)
    c.update(.1, None, (.5, .5), True, obj_scale=1.2)
    assert s.y > .5
