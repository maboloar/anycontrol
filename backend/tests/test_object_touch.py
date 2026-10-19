"""물체 터치(물체 모습 변화 + 손 확인)와 매핑 연결."""
from __future__ import annotations

import numpy as np

from vision_input.hands.detector import Hand, HandFrame
from vision_input.mapping.engine import InputSnapshot, MappingEngine, ObjectSnap
from vision_input.mapping.schema import Profile
from vision_input.object_touch import ObjectTouch


def _hand(tip: tuple[float, float], size: float = 0.1) -> Hand:
    pts = np.tile(np.asarray(tip, np.float32), (21, 1))
    pts[5] = (tip[0] - size / 2, tip[1] - 0.1); pts[17] = (tip[0] + size / 2, tip[1] - 0.1)
    pts[8] = pts[12] = tip
    return Hand(pts, np.zeros(21, np.float32), "Right", 0.9)


BOX = (0.4, 0.4, 0.6, 0.6)
SKIN = (120, 160, 220)       # BGR 살색
GRAY_THING = (90, 90, 90)


def _scene(finger: tuple | None = None, color=SKIN, light: float = 1.0) -> np.ndarray:
    """회색 책상 위 파란 물체(무늬 있음). finger = (x, y) 정규화 위치에 손가락 크기 덩어리."""
    img = np.full((200, 200, 3), 150, np.uint8)
    img[80:120, 80:120] = (200, 90, 40)
    img[90:110:4, 80:120] = (230, 140, 70)
    if finger:
        x, y = int(finger[0] * 200), int(finger[1] * 200)
        img[y - 8:y + 8, x - 5:x + 5] = color
    return np.clip(img.astype(np.float32) * light, 0, 255).astype(np.uint8)


def _mask() -> np.ndarray:
    m = np.zeros((200, 200), bool); m[80:120, 80:120] = True
    return m


def _run(ot: ObjectTouch, frames: list) -> list[bool]:
    return [ot.update(img, hf, k * 0.033, {1: (BOX, _mask())})[1] for k, (img, hf) in enumerate(frames)]


def test_object_touch_detects_a_finger_in_front_by_appearance_change() -> None:
    ot = ObjectTouch()
    _run(ot, [(_scene(), None)] * 3)                                            # 기준 모습
    hand = HandFrame(0, [_hand((0.5, 0.5))])
    assert _run(ot, [(_scene(finger=(0.5, 0.5)), hand)] * 3)[-1] is True       # 손끝 + 가림 → 닿음
    assert ot.runs[1].reason == "hand-contact"
    assert _run(ot, [(_scene(), None)] * 4)[-1] is False                       # 손을 떼면 꺼짐


def test_object_touch_without_hand_landmarks_never_uses_skin_colour() -> None:
    ot = ObjectTouch()
    _run(ot, [(_scene(), None)] * 3)
    assert not any(_run(ot, [(_scene(finger=(0.5, 0.5)), None)] * 3))       # 살색 변화만 있고 인식된 손이 없으면 닿음이 아니다
    assert ot.runs[1].reason == "no-near-hand"


def test_object_touch_ignores_hand_behind_other_things_and_lighting() -> None:
    ot = ObjectTouch()
    _run(ot, [(_scene(), None)] * 3)
    behind = HandFrame(0, [_hand((0.5, 0.5))])                                  # 손 랜드마크는 물체 위인데 모습은 그대로 (손이 뒤)
    assert not any(_run(ot, [(_scene(), behind)] * 4))
    assert not any(_run(ot, [(_scene(finger=(0.5, 0.5), color=GRAY_THING), None)] * 4))   # 손 아닌 회색 물건
    assert not any(_run(ot, [(_scene(light=0.6), None)] * 4))                  # 조명 급변
    assert _run(ot, [(_scene(light=0.6, finger=(0.5, 0.5)), behind)] * 3)[-1] is True   # 새 조명 기준에서도 다시 동작


def test_object_touch_sensitivity_controls_how_much_cover_is_needed() -> None:
    small = (0.42, 0.42)                                                        # 귀퉁이를 살짝
    ot = ObjectTouch(sensitivity=0.0)
    _run(ot, [(_scene(), None)] * 3)
    img = _scene(); img[82:86, 82:86] = SKIN
    assert not any(_run(ot, [(img, HandFrame(0, [_hand(small)]))] * 4))
    ot.sensitivity = 1.0
    assert _run(ot, [(img, HandFrame(0, [_hand(small)]))] * 3)[-1] is True


def test_mapping_reads_touch_and_control_outputs() -> None:
    p = Profile.model_validate({"version": 1, "name": "t", "description": "", "mappings": [
        {"id": "m1", "label": "", "enabled": True, "input": {"source": "touch", "object": "컵"}, "output": {"target": "key", "key": "space"},
         "transform": {"range": [0, 1], "deadzone": 0}},
        {"id": "m3", "label": "", "enabled": True, "input": {"source": "object", "object": "컵", "axis": "x"},
         "output": {"target": "control", "name": "dj.cross", "kind": "bipolar"}, "transform": {"range": [-0.2, 0.2], "deadzone": 0}}]})
    e = MappingEngine(p)
    assert e.needs_hands and e.needs_touch
    st = e.update(InputSnapshot(0.0, [ObjectSnap(1, "컵", True, {"x": 0.1}, None, True)], None))
    assert st.keys == {"space"} and abs(st.controls["dj.cross"] - 0.5) < 1e-6


def _scene_at(dx: int, finger: bool) -> np.ndarray:
    img = np.full((200, 200, 3), 150, np.uint8)
    img[80:120, 80 + dx:120 + dx] = (200, 90, 40)
    img[90:110:4, 80 + dx:120 + dx] = (230, 140, 70)
    if finger:
        img[92:108, 95 + dx:105 + dx] = SKIN
    return img


def test_object_touch_keeps_working_while_the_touched_object_moves() -> None:
    ot = ObjectTouch()
    for k in range(3):
        ot.update(_scene_at(0, False), None, k * 0.03, {1: (BOX, _mask())})
    r = []
    for k, dx in enumerate([0, 0, 10, 20, 30, 40]):                           # 손가락을 댄 채 오른쪽으로 옮김
        m = np.zeros((200, 200), bool); m[80:120, 80 + dx:120 + dx] = True
        box = (0.4 + dx / 200, 0.4, 0.6 + dx / 200, 0.6)
        hand = HandFrame(0, [_hand((0.5 + dx / 200, 0.5))])
        r.append(ot.update(_scene_at(dx, True), hand, 1 + k * 0.03, {1: (box, m)})[1])
    assert all(r[1:])


def test_touch_requires_near_fingertip_local_change_and_releases_on_hand_loss():
    ot = ObjectTouch()
    _run(ot, [(_scene(), None)] * 3)
    far = HandFrame(0, [_hand((.85, .85))])
    assert not any(_run(ot, [(_scene(finger=(.5, .5)), far)] * 4))
    _run(ot, [(_scene(), None)] * 3)
    near = HandFrame(0, [_hand((.5, .5))])
    assert not any(_run(ot, [(_scene(light=.7), near)] * 4))
    _run(ot, [(_scene(), None)] * 3)
    assert _run(ot, [(_scene(finger=(.5, .5)), near)] * 3)[-1]
    assert ot.update(_scene(finger=(.5, .5)), None, 2, {1: (BOX, _mask())})[1] is False


def test_touch_rejects_low_confidence_hand():
    ot = ObjectTouch()
    _run(ot, [(_scene(), None)] * 3)
    hand = _hand((.5, .5)); hand.score = .2
    assert not any(_run(ot, [(_scene(finger=(.5, .5)), HandFrame(0, [hand]))] * 4))


def test_touch_accepts_palm_without_any_fingertip_near_object():
    ot = ObjectTouch()
    _run(ot, [(_scene(), None)] * 3)
    points = np.tile(np.array([.5, .5], np.float32), (21, 1))
    for i in [4, 8, 12, 16, 20]:
        points[i] = [.75, .25]
    hand = Hand(points, np.zeros(21, np.float32), "Right", .9)
    assert _run(ot, [(_scene(finger=(.5, .5)), HandFrame(0, [hand]))] * 3)[-1]
    assert ot.runs[1].reason == 'hand-contact'


def test_default_touch_sensitivity_recognizes_small_contact_but_not_far_hand():
    ot = ObjectTouch()
    _run(ot, [(_scene(), None)] * 3)
    img = _scene(); img[94:101, 94:101] = SKIN
    near = HandFrame(0, [_hand((.48, .48))])
    assert _run(ot, [(img, near)] * 3)[-1]
    far = HandFrame(0, [_hand((.85, .85))])
    assert not ot.update(img, far, 2, {1: (BOX, _mask())})[1]


def test_full_palm_cover_is_not_erased_as_a_global_colour_shift():
    ot = ObjectTouch()
    _run(ot, [(_scene(), None)] * 3)
    points = np.tile(np.array([.5, .5], np.float32), (21, 1))
    points[[0, 5, 9, 17]] = [[.3, .3], [.7, .3], [.7, .7], [.3, .7]]
    hand = Hand(points, np.zeros(21, np.float32), 'Right', .9)
    img = _scene(); img[65:135, 65:135] = SKIN
    assert _run(ot, [(img, HandFrame(0, [hand]))] * 3)[-1]


# Foreground ordering regressions: the hand hull can overlap an unchanged object
# while the visible hand changes only the background behind its edge.
def test_behind_hand_changing_background_at_object_edge_is_not_contact():
    ot = ObjectTouch()
    _run(ot, [(_scene(), None)] * 3)
    img = _scene(); img[72:80, 85:115] = SKIN
    hand = HandFrame(0, [_hand((.5, .43))])
    assert not any(_run(ot, [(img, hand)] * 6))
    assert ot.runs[1].reason == 'no-front-occlusion'


def test_hand_visible_through_a_hole_in_object_does_not_touch_object():
    mask = _mask(); mask[90:110, 90:110] = False
    base = _scene(); base[90:110, 90:110] = 150
    front = base.copy(); front[93:107, 93:107] = SKIN
    ot = ObjectTouch()
    for k in range(3):
        ot.update(base, None, k * .03, {1: (BOX, mask)})
    hf = HandFrame(0, [_hand((.5, .5))])
    assert not any(ot.update(front, hf, .2 + k * .03, {1: (BOX, mask)})[1] for k in range(5))


def test_local_hand_shadow_on_object_is_not_a_press():
    ot = ObjectTouch()
    _run(ot, [(_scene(), None)] * 3)
    img = _scene(); img[90:112, 90:112] = (img[90:112, 90:112] * .65).astype(np.uint8)
    hf = HandFrame(0, [_hand((.5, .5))])
    assert not any(_run(ot, [(img, hf)] * 5))
    assert ot.runs[1].reason == 'no-foreground-hand'


def test_hand_passing_back_releases_without_waiting_for_debounce():
    ot = ObjectTouch()
    _run(ot, [(_scene(), None)] * 3)
    hf = HandFrame(0, [_hand((.5, .5))])
    assert _run(ot, [(_scene(finger=(.5, .5)), hf)] * 3)[-1]
    img = _scene(); img[72:80, 85:115] = SKIN
    assert not ot.update(img, hf, 1, {1: (BOX, _mask())})[1]
    assert ot.runs[1].reason == 'no-front-occlusion'


def test_unrelated_changes_on_consecutive_frames_do_not_combine_into_press():
    ot = ObjectTouch()
    _run(ot, [(_scene(), None)] * 3)
    hf = HandFrame(0, [_hand((.5, .5), size=.2)])
    for x in [.42, .58, .42, .58]:
        assert not ot.update(_scene(finger=(x, .45)), hf, 1, {1: (BOX, _mask())})[1]


def test_wait_for_clear_object_before_capturing_touch_baseline():
    ot = ObjectTouch()
    hf = HandFrame(0, [_hand((.5, .5))])
    assert not any(_run(ot, [(_scene(finger=(.5, .5)), hf)] * 3))
    assert ot.runs[1].ref is None
    assert ot.runs[1].reason == 'await-clear-object'
    _run(ot, [(_scene(), None)] * 3)
    assert _run(ot, [(_scene(finger=(.5, .5)), hf)] * 3)[-1]


def test_non_skin_foreground_uses_visible_hand_appearance_not_skin_threshold():
    # A dark glove covers the object's upper edge and part of its interior.
    ot = ObjectTouch()
    _run(ot, [(_scene(), None)] * 3)
    img = _scene(); img[65:100, 94:106] = (38, 32, 27)
    hf = HandFrame(0, [_hand((.5, .45))])
    assert _run(ot, [(img, hf)] * 3)[-1]
    assert ot.runs[1].foreground > 0


def test_gap_between_spread_fingers_is_not_hand_surface():
    from vision_input.object_touch import _hand_area
    points = np.tile(np.array([.5, .8], np.float32), (21, 1))
    points[[0, 1, 5, 9, 13, 17]] = [.5, .8]
    points[[6, 7, 8]] = [[.35, .6], [.25, .4], [.15, .2]]
    points[[10, 11, 12]] = [[.65, .6], [.75, .4], [.85, .2]]
    area = _hand_area([points], (0, 0, 1, 1), (200, 200))
    assert area[40, 30] and area[40, 170]
    assert not area[45, 100]


def test_frame_or_object_loss_releases_touch_immediately():
    for image, box in [(None, BOX), (_scene(), None)]:
        ot = ObjectTouch()
        _run(ot, [(_scene(), None)] * 3)
        hf = HandFrame(0, [_hand((.5, .5))])
        assert _run(ot, [(_scene(finger=(.5, .5)), hf)] * 3)[-1]
        assert not ot.update(image, hf, 1, {1: (box, _mask())})[1]


def test_dark_hand_behind_and_its_strong_shadow_preserve_object_texture():
    ot = ObjectTouch()
    _run(ot, [(_scene(), None)] * 3)
    img = _scene()
    img[65:80, 90:110] = (38, 32, 27)  # visible hand behind the object's upper edge
    img[85:115, 90:110] = (img[85:115, 90:110] * .18).astype(np.uint8)
    hf = HandFrame(0, [_hand((.5, .5))])
    assert not any(_run(ot, [(img, hf)] * 5))


def test_missing_segmentation_does_not_guess_a_touch_from_the_box():
    ot = ObjectTouch()
    assert not ot.update(_scene(), None, 0, {1: (BOX, None)})[1]
    assert ot.runs[1].ref is None
    assert ot.runs[1].reason == 'await-object-mask'
    _run(ot, [(_scene(), None)] * 3)
    hf = HandFrame(0, [_hand((.5, .5))])
    assert _run(ot, [(_scene(finger=(.5, .5)), hf)] * 3)[-1]
    assert not ot.update(_scene(finger=(.5, .5)), hf, 1, {1: (BOX, None)})[1]


def test_contact_near_image_edge_uses_matching_crop_coordinates():
    ot = ObjectTouch()
    mask = np.zeros((200, 200), bool); mask[80:120, :40] = True
    box = (0., .4, .2, .6)
    for k in range(3):
        ot.update(_scene_at(-80, False), None, k * .03, {1: (box, mask)})
    hf = HandFrame(0, [_hand((.1, .5))])
    states = [ot.update(_scene_at(-80, True), hf, .2 + k * .03, {1: (box, mask)})[1] for k in range(3)]
    assert states[-1]
    assert ot.runs[1].box[0] == 0


def test_strong_shadow_on_untextured_surface_is_not_foreground_contact():
    ot = ObjectTouch()
    base = _scene(); base[80:120, 80:120] = (200, 90, 40)
    _run(ot, [(base, None)] * 3)
    img = base.copy(); img[65:80, 90:110] = (38, 32, 27)
    img[85:115, 90:110] = (36, 16, 7)
    hf = HandFrame(0, [_hand((.5, .5))])
    assert not any(_run(ot, [(img, hf)] * 5))


def test_touch_survives_brief_hand_detection_dropouts() -> None:
    """손 인식기가 한두 프레임 손을 놓쳐도(비동기 지연·깜빡임) 손가락이 그대로면 터치는 유지된다."""
    ot = ObjectTouch()
    seq = [(_scene(), None)] * 3
    hand = HandFrame(0, [_hand((0.5, 0.5))])
    seq += [(_scene(finger=(0.5, 0.5)), hand)] * 3
    seq += [(_scene(finger=(0.5, 0.5)), None)] * 2                            # 손 인식이 잠깐 끊김
    seq += [(_scene(finger=(0.5, 0.5)), hand)] * 2
    out = _run(ot, seq)
    assert out[5] and out[6] and out[7] and out[8] and out[9]


def test_touch_releases_after_hand_is_gone_longer_than_hold() -> None:
    ot = ObjectTouch()
    hand = HandFrame(0, [_hand((0.5, 0.5))])
    frames = [(_scene(), None)] * 3 + [(_scene(finger=(0.5, 0.5)), hand)] * 3 + [(_scene(), None)] * 30
    out = [ot.update(img, hf, k * 0.033, {1: (BOX, _mask())})[1] for k, (img, hf) in enumerate(frames)]
    assert out[5] is True and out[-1] is False


def test_touch_tolerates_landmarks_slightly_off_the_visible_finger() -> None:
    """랜드마크가 실제 손가락보다 조금 어긋나 있어도(손 인식 오차) 닿음으로 본다."""
    ot = ObjectTouch()
    _run(ot, [(_scene(), None)] * 3)
    hand = HandFrame(0, [_hand((0.5, 0.56))])                                   # 손가락 덩어리보다 약 12px 아래
    assert _run(ot, [(_scene(finger=(0.5, 0.5)), hand)] * 3)[-1] is True
