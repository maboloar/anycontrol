"""검지·중지 끝점 직접 추적과, '원래 자리에서 내려와 물체에 닿으면' 클릭."""

import cv2
import numpy as np

from vision_input.hands.tip_click import TipClickDetector
from vision_input.hands.tip_track import Tip, TipFrame, TipTracker
from vision_input.io.mouse import MouseController, MouseSettings
from vision_input.io.sink import VirtualSink

from .handkit import make_hand

W, H = 640, 360
RNG = np.random.default_rng(3)
BG = RNG.integers(60, 200, (H, W), dtype=np.uint8)
BLOB = cv2.GaussianBlur(RNG.integers(0, 255, (40, 40), dtype=np.uint8), (3, 3), 0)


def frame_with_blobs(points):
    """배경 위에 질감 있는 원(손끝 모양)을 points 위치에 그린다."""
    g = BG.copy()
    for (x, y) in points:
        x, y = int(round(x)), int(round(y))
        g[y - 14:y + 14, x - 14:x + 14] = BLOB[6:34, 6:34]
        cv2.circle(g, (x, y), 16, 255, 1)
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)


def hand_at(cx=.5, cy=.5, size=.12):
    h = make_hand(cx, cy, size)
    return h, h.points[[8, 12]] * [W, H]


def test_anchors_from_landmarks_then_follows_the_tip_without_landmarks():
    hand, tips = hand_at()
    tr = TipTracker()
    f = tr.update(frame_with_blobs(tips), 0.0, hand, 0.0)
    assert f.tips["index"].valid and f.tips["middle"].valid and f.landmark_fresh
    assert np.allclose(f.tips["index"].xy, tips[0], atol=1.5)
    # 랜드마크 없이 점이 아래로 움직여도 (손을 오므린 것처럼) 따라간다
    for k in range(1, 41):
        moved = tips + [0.0, 1.2 * k]
        f = tr.update(frame_with_blobs(moved), k / 30, None, None)
    assert f.tips["index"].valid and f.tips["middle"].valid
    assert np.linalg.norm(f.tips["index"].xy - moved[0]) < 3.0
    assert np.linalg.norm(f.tips["middle"].xy - moved[1]) < 3.0


def test_losing_the_target_marks_it_invalid_instead_of_inventing_a_point():
    hand, tips = hand_at()
    tr = TipTracker()
    tr.update(frame_with_blobs(tips), 0.0, hand, 0.0)
    f = None
    for k in range(1, 12):
        f = tr.update(frame_with_blobs([]), k / 30, None, None)  # 점이 사라진 장면
    assert not f.tips["index"].valid


def test_confident_track_is_not_dragged_to_a_hallucinated_landmark():
    hand, tips = hand_at()
    tr = TipTracker()
    tr.update(frame_with_blobs(tips), 0.0, hand, 0.0)
    fake, _ = hand_at(cx=.2, cy=.7)               # 엉뚱한 곳에 '곧게 든' 손이 검출됨
    f = tr.update(frame_with_blobs(tips), 0.05, fake, 0.05)
    assert np.linalg.norm(f.tips["index"].xy - tips[0]) < 3.0


def test_bent_finger_landmark_is_not_trusted_for_anchoring():
    hand, tips = hand_at()
    for i in (8, 12):                              # 끝이 뿌리 쪽으로 접힘 → 곧게 들리지 않음
        hand.points[i] = hand.points[i - 3] + [0.0, 0.01]
    tr = TipTracker()
    f = tr.update(frame_with_blobs(tips), 0.0, hand, 0.0)
    assert not f.tips["index"].valid and not f.tips["middle"].valid


def test_same_landmark_observation_is_not_applied_twice():
    hand, tips = hand_at()
    tr = TipTracker()
    tr.update(frame_with_blobs(tips), 0.0, hand, 0.0)
    f = tr.update(frame_with_blobs(tips), 0.03, hand, 0.0)
    assert not f.landmark_fresh


# ---------------------------------------------------------------- 클릭 판정 (합성 끝점)
HS = 100.0                                    # 손 크기 (px)
BOX = (0.35, 0.60, 0.65, 0.85)                # 정규화 (x0, y0, x1, y1)
BOX_PX = np.array([BOX[0] * W, BOX[1] * H, BOX[2] * W, BOX[3] * H])


def tipframe(t, pos, raised=True, fresh=True, valid=True):
    """pos: 이름 → 끝점 px. raised: 이번 프레임에 랜드마크로 보정됨(손가락을 곧게 든 상태)."""
    tips = {}
    for n, p in pos.items():
        tips[n] = Tip(valid=valid, xy=np.array(p, float), conf=.9, anchored_t=t if raised else -1e9)
    return TipFrame(t, (W, H), tips, HS, np.array([0., -1.]), fresh)


REST = {"index": (250.0, 150.0), "middle": (330.0, 150.0)}      # 물체 위쪽 (박스 위 변 y=216)
TOUCH_Y = BOX_PX[1] + 5                                         # 박스 위에 닿음


def run_click(det, finger="middle", end_y=TOUCH_Y, other_follows=False, n_rest=6, n_down=5, n_hold=5):
    outs, t = [], 0.0
    fr = lambda pos, raised: det.update(t, tipframe(t, pos, raised, fresh=raised), BOX)   # noqa: E731
    for _ in range(n_rest):
        outs.append(fr(REST, True)); t += 1 / 30
    for k in range(1, n_down + 1):
        pos = dict(REST)
        y = REST[finger][1] + (end_y - REST[finger][1]) * k / n_down
        pos[finger] = (REST[finger][0], y)
        if other_follows:
            other = "index" if finger == "middle" else "middle"
            pos[other] = (REST[other][0], y)
        outs.append(fr(pos, False)); t += 1 / 30
    for _ in range(n_hold):
        pos = dict(REST); pos[finger] = (REST[finger][0], end_y)
        if other_follows:
            other = "index" if finger == "middle" else "middle"
            pos[other] = (REST[other][0], end_y)
        outs.append(fr(pos, False)); t += 1 / 30
    for k in range(1, 6):
        pos = dict(REST); pos[finger] = (REST[finger][0], end_y + (REST[finger][1] - end_y) * k / 5)
        outs.append(fr(pos, False)); t += 1 / 30
    for _ in range(4):
        outs.append(fr(REST, True)); t += 1 / 30
    return outs


def test_middle_down_onto_object_presses_left_then_releases_when_returned():
    outs = run_click(TipClickDetector())
    assert any(o.left for o in outs) and not any(o.right for o in outs)
    assert not outs[-1].left
    first = next(i for i, o in enumerate(outs) if o.left)
    assert first >= 6 and outs[first + 2].left        # 내려오기 시작한 뒤에 눌리고 잠시 유지 (드래그 가능)


def test_index_down_is_right_button():
    outs = run_click(TipClickDetector(), finger="index")
    assert any(o.right for o in outs) and not any(o.left for o in outs)


def test_coming_down_but_not_reaching_the_object_does_not_click():
    outs = run_click(TipClickDetector(), end_y=BOX_PX[1] - 70)   # 박스에서 아직 멀다
    assert not any(o.left or o.right for o in outs)


def test_small_dip_below_the_drop_distance_does_not_click():
    outs = run_click(TipClickDetector(), end_y=REST["middle"][1] + 12)
    assert not any(o.left or o.right for o in outs)


def test_whole_hand_sinking_with_both_fingers_equally_is_ambiguous():
    outs = run_click(TipClickDetector(), other_follows=True)
    assert not any(o.left or o.right for o in outs)


def test_not_ready_until_both_rest_positions_are_known():
    det = TipClickDetector()
    assert not det.ready
    det.update(0.0, tipframe(0.0, REST), BOX)
    assert det.ready


def test_losing_the_tip_while_pressed_releases_after_a_short_time():
    det = TipClickDetector()
    outs = run_click(det, n_hold=40)
    t = 5.0
    assert any(o.left for o in outs[:20])
    st = det.update(t, tipframe(t, REST, raised=False, valid=False), BOX)
    assert not st.left


def test_cursor_freezes_while_approaching_and_briefly_after_pressing():
    outs = run_click(TipClickDetector(), n_down=8, n_hold=10)
    assert any(o.freeze for o in outs[6:14])
    assert not outs[-1].freeze


# ---------------------------------------------------------------- 컨트롤러 연동
def _ctl(**kw):
    sink = VirtualSink()
    c = MouseController(sink)
    c.configure(MouseSettings(mode="object", object_id=1, hand_clicks=True, coordinate_mode="image", **kw))
    return c, sink


def test_controller_falls_back_to_landmarks_when_tip_tracking_is_off_or_unavailable():
    c, sink = _ctl(finger_track=False)
    st = c.update(0.0, None, (.5, .7), True, obj_box=BOX, tips=tipframe(0.0, REST))
    assert st["tip_mode"] is False
    c2, _ = _ctl()
    st = c2.update(0.0, None, (.5, .7), True, obj_box=BOX, tips=None)
    assert st["tip_mode"] is False


# ---------------------------------------------------------------- 살색 확인 + EfficientTAM 보정
SKIN = (120, 150, 200)   # BGR 살색 비슷한 값
BLUE = (200, 80, 40)


def color_frame(tip_xy, bg=BLUE, skin_box=None):
    img = np.full((H, W, 3), bg, np.uint8)
    noise = RNG.integers(-12, 12, (H, W, 1), dtype=np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    if skin_box is not None:
        x0, y0, x1, y1 = skin_box
        sk = np.clip(np.array(SKIN, np.int16) + RNG.integers(-12, 12, (y1 - y0, x1 - x0, 1), dtype=np.int16), 0, 255).astype(np.uint8)
        img[y0:y1, x0:x1] = sk
    return img


def test_point_that_drifts_off_skin_is_dropped():
    hand, tips = hand_at()
    tr = TipTracker()
    x, y = tips[0]
    box = (int(x - 40), int(y - 40), int(x + 40), int(y + 40))
    tr.update(color_frame(tips[0], skin_box=box), 0.0, hand, 0.0)
    assert tr.tips["index"].valid and tr.skin is not None
    f = None
    for k in range(1, 12):  # 손가락이 사라지고 파란 배경만 남음 (질감 없는 배경이라 LK 는 버티지만 살색이 아니다)
        f = tr.update(color_frame(tips[0]), k / 30, None, None)
    assert not f.tips["index"].valid


class FakeSeg:
    """점 프롬프트 주변의 원을 '손가락 살색 부분'으로 돌려주는 가짜 분할기."""
    def __init__(self, offset, radius):
        self.offset, self.radius, self.calls = np.asarray(offset, float), radius, 0

    def segment(self, frame, box=None, points=None):
        from vision_input.tracking.segment import SegResult
        self.calls += 1
        h, w = frame.shape[:2]
        m = np.zeros((h, w), np.uint8)
        # 프롬프트(크롭 좌표) 중 첫 점에서 offset 만큼 떨어진 곳이 실제 손가락 (점이 어긋난 상황)
        c = np.asarray(points[0][:2], float) + self.offset
        cv2.circle(m, (int(c[0]), int(c[1])), int(self.radius), 1, -1)
        return SegResult([m.astype(bool)], [0.8])


def test_refiner_pulls_a_drifted_point_back_into_the_skin_mask_and_rebuilds_the_skin_model():
    import time
    from vision_input.hands.tip_refine import TipRefiner

    hand, tips = hand_at()
    tr = TipTracker()
    img = color_frame(tips[0], skin_box=(int(tips[0][0] - 50), int(tips[0][1] - 50), int(tips[0][0] + 50), int(tips[0][1] + 50)))
    f = tr.update(img, 0.0, hand, 0.0)
    true = tips[0].copy()
    tr.tips["index"].xy = true + [30.0, 0.0]            # 점이 옆으로 어긋남 (마스크 밖)
    seg = FakeSeg((-30.0, 0.0), 28)   # 첫 프롬프트(검지, +30 어긋남) 기준 -30 위치가 진짜 손가락
    ref = TipRefiner(seg, period_s=0.0)
    ref.maybe_submit(img, 0.1, f)
    for _ in range(300):                                  # GPU 스레드 작업 완료 대기
        if not ref._pending:
            break
        time.sleep(0.01)
    ref.apply(tr)
    assert seg.calls >= 1
    assert np.linalg.norm(tr.tips["index"].xy - true) <= 28.6   # 마스크(반지름 28) 경계 안쪽으로 당겨짐 (30 → 28.5)
    assert tr.skin is not None


def test_refiner_without_segmenter_or_before_the_interval_does_nothing():
    from vision_input.hands.tip_refine import TipRefiner

    hand, tips = hand_at()
    tr = TipTracker()
    f = tr.update(frame_with_blobs(tips), 0.0, hand, 0.0)
    ref = TipRefiner(None)
    ref.maybe_submit(frame_with_blobs(tips), 1.0, f)
    assert ref.stats["jobs"] == 0
    seg = FakeSeg((0.0, 0.0), 20)
    ref2 = TipRefiner(seg, period_s=10.0)
    ref2._last = 0.5
    ref2.maybe_submit(frame_with_blobs(tips), 1.0, f)
    assert ref2.stats["jobs"] == 0


def test_fingertip_tracking_is_removed_and_always_off():
    from vision_input.io.mouse import MouseSettings
    assert MouseSettings().finger_track is False
    assert MouseSettings(finger_track=True).finger_track is False   # 예전 저장값이 켜져 있어도 끈다
