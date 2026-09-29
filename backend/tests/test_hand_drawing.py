"""맨손 검지 그리기: 집기, 놓기, 중복/오래된 관측, 손 교체, 독립적인 손 추적."""

import numpy as np
import pytest

from vision_input.capture import Frame
from vision_input.hands.detector import HandFrame
from vision_input.hands.drawing import HandDrawing
from vision_input.pipeline import VisionProcessor

from .handkit import make_hand
from .test_mouse import FakeHands


def update(drawing, t, x=.5, pinch=.1, size=.12, hand=None):
    h = hand or make_hand(x, .5, size, pinch=pinch)
    drawing.update(HandFrame(t, [h]), t)
    return drawing.state()


def started():
    d = HandDrawing()
    d.set_enabled(True)
    update(d, 0)
    assert update(d, .03)["contact"]
    return d


@pytest.mark.parametrize("size", [.08, .2])
def test_pinch_draws_index_tip_and_release_splits_strokes(size):
    d = HandDrawing()
    d.set_enabled(True)
    assert not update(d, 0, pinch=1, size=size)["contact"]
    update(d, .03, size=size)
    st = update(d, .06, size=size)
    assert st["contact"]
    assert st["point"] == pytest.approx(make_hand(.5, .5, size).points[8], abs=1e-5)
    st = update(d, .09, x=.52, size=size)
    assert st["point"][0] > st["current"][0][0]  # 마우스의 누름 직후 freeze가 적용되지 않는다.
    first = st["current"].copy()
    st = update(d, .12, x=.52, pinch=1, size=size)
    assert not st["contact"] and st["events"] == [{"type": "up", "stroke": first}]
    update(d, .15, x=.55, size=size)
    st = update(d, .18, x=.55, size=size)
    assert st["contact"] and len(st["current"]) == 1 and st["stroke_count"] == 1


def test_repeated_hand_observation_does_not_debounce_or_duplicate_points():
    d = HandDrawing()
    d.set_enabled(True)
    hf = HandFrame(0, [make_hand(.5, .5, .12, pinch=.1)])
    for t in [0, .01, .02]:
        d.update(hf, t)
        assert not d.state()["contact"]
    assert update(d, .03)["contact"]
    d.update(HandFrame(.03, hf.hands), .04)
    assert len(d.state()["current"]) == 1


@pytest.mark.parametrize("missing", ["none", "empty", "stale"])
def test_lost_or_stale_hand_ends_stroke(missing):
    d = started()
    hf = {"none": None, "empty": HandFrame(.4, []),
          "stale": HandFrame(.03, [make_hand(.5, .5, .12, pinch=.1)])}[missing]
    d.update(hf, .4)
    st = d.state()
    assert not st["contact"] and not st["hand_visible"] and st["current"] is None
    assert st["events"][0]["type"] == "up"
    assert not update(d, .43)["contact"]  # 다시 나타났을 때 새 집기를 확인한다.


def test_middle_pinch_does_not_draw_and_hysteresis_avoids_flicker():
    d = started()
    assert update(d, .06, pinch=.38)["contact"]
    assert not update(d, .09, pinch=1)["contact"]
    d = HandDrawing()
    d.set_enabled(True)
    for t in [0, .03, .06]:
        assert not update(d, t, hand=make_hand(.5, .5, .12, pinch=1, pinch_middle=.1))["contact"]


def test_different_hand_or_large_position_jump_does_not_connect_strokes():
    d = started()
    left = make_hand(.5, .5, .12, pinch=.1)
    left.handedness = "Left"
    st = update(d, .06, hand=left)
    assert not st["contact"] and st["events"][0]["type"] == "up"
    update(d, .09, hand=left)
    assert update(d, .12, hand=left)["contact"]
    left.points += [.4, 0]
    assert not update(d, .15, hand=left)["contact"]


def test_clear_and_disable_do_not_restore_previous_stroke():
    d = started()
    d.clear()
    st = d.state()
    assert st["current"] is None and st["stroke_count"] == 0
    assert st["events"] == [{"type": "clear"}]
    update(d, .06)
    assert update(d, .09)["contact"]
    d.set_enabled(False)
    assert not update(d, .12)["contact"]
    d.set_enabled(True)
    assert not update(d, .15)["contact"]


class DrawingHands(FakeHands):
    def offer(self, img, t):
        self.result = HandFrame(t, [make_hand(.5, .5, .12, pinch=.1)])

    def latest(self):
        return self.result


def frame(seq):
    return Frame(seq, np.zeros((120, 160, 3), np.uint8), seq / 30, seq / 30)


def test_pipeline_draws_with_mouse_off_and_stops_unused_hand_worker():
    hands = DrawingHands()
    p = VisionProcessor(None, hand_worker=hands)
    p.set_hand_drawing(True)
    p.process(frame(0))
    st = p.process(frame(1))
    assert hands.running and st["hand_drawing"]["contact"]
    assert st["mouse"]["mode"] == "off" and not st["mouse"]["left"]
    assert (st["mouse"]["x"], st["mouse"]["y"]) == (.5, .5)
    p.emergency_stop()
    st = p.process(frame(2))
    assert not hands.running and not st["hand_drawing"]["enabled"]
    assert not st["hand_drawing"]["contact"]


def test_source_reset_clears_drawing_and_starts_with_fresh_hand_observations():
    hands = DrawingHands()
    p = VisionProcessor(None, hand_worker=hands)
    p.set_hand_drawing(True)
    p.process(frame(0))
    assert p.process(frame(1))["hand_drawing"]["contact"]
    p.reset()
    assert not hands.running and p.hand_drawing.enabled
    st = p.process(frame(0))["hand_drawing"]
    assert not st["contact"] and st["stroke_count"] == 0 and st["events"] == [{"type": "clear"}]


def test_unavailable_hand_model_rejects_enable():
    p = VisionProcessor(None, hand_worker=FakeHands())
    p.hands = None
    with pytest.raises(ValueError, match="손 인식 모델"):
        p.set_hand_drawing(True)
    assert not p.hand_drawing.enabled
