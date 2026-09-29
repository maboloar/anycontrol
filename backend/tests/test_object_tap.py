"""잡고 있는 물체의 검지 탭: 준비, 관측 중복, 소실 안전성."""

from vision_input.hands.detector import HandFrame
from vision_input.hands.object_tap import ObjectTapDetector
from vision_input.io.mouse import MouseController, MouseSettings
from vision_input.io.sink import VirtualSink

from .handkit import make_hand

BOX = (.4, .5, .6, .7)


def hand(touch=False):
    h = make_hand(.5, .55, .1)
    h.points[8] = (.5, .52 if touch else .47)
    return h


def test_tap_requires_lift_then_contact_and_distinct_observations():
    d = ObjectTapDetector()
    assert not d.update([hand(True)], BOX, 0, 0)
    assert not d.update([hand()], BOX, .1, .1)
    assert not d.update([hand()], BOX, .12, .1)  # 워커의 같은 관측
    assert not d.armed
    assert not d.update([hand()], BOX, .2, .2)
    assert d.armed
    assert not d.update([hand(True)], BOX, .3, .3)
    assert d.update([hand(True)], BOX, .4, .4)
    assert not d.update([hand(True)], BOX, .5, .5)


def test_missing_hand_or_object_cancels_armed_tap():
    for lost_box, hands in ((None, [hand()]), (BOX, [])):
        d = ObjectTapDetector()
        d.update([hand()], BOX, 0, 0)
        d.update([hand()], BOX, .1, .1)
        assert d.armed
        assert not d.update(hands, lost_box, .2, .2)
        assert not d.update([hand(True)], BOX, .3, .3)
        assert not d.update([hand(True)], BOX, .4, .4)


def test_object_mouse_tap_emits_one_click_then_releases():
    sink = VirtualSink()
    c = MouseController(sink)
    c.configure(MouseSettings(mode="object", object_id=1))
    for t, touching in ((0, False), (.1, False), (.2, True), (.3, True), (.5, True)):
        c.update(t, HandFrame(t, [hand(touching)]), (.5, .6), True, obj_box=BOX)
    events = sink.snapshot()["events"]
    assert [e["type"] for e in events if e["button"] == "left"] == ["down", "up"]
    assert not sink.buttons["left"]
