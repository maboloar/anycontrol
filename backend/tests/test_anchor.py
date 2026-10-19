"""물체 커서 기준점: 분할 영역이 흔들려도 바닥 아래-가운데 점은 물체를 따라간다."""
import cv2
import numpy as np
import pytest
from vision_input.tracking.anchor import AnchorConfig, ObjectAnchor, bottom_center

W, H = 640, 360
RNG = np.random.default_rng(3)
BG = (RNG.integers(60, 200, (H, W)).astype(np.uint8))                 # 질감 있는 정지 배경
TEX = cv2.GaussianBlur(RNG.integers(0, 255, (80, 200)).astype(np.uint8), (0, 0), 1.2)   # 물체 표면 무늬


def frame(x0, y0, scale=1.0):
    """무늬 있는 직사각형 물체를 (x0, y0) 왼쪽 위에 scale 배로 붙인다. (영상, 참 마스크, 참 바닥 가운데 점)"""
    img = BG.copy()
    tex = cv2.resize(TEX, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    th, tw = tex.shape
    x0, y0 = int(round(x0)), int(round(y0))
    img[y0:y0 + th, x0:x0 + tw] = tex
    m = np.zeros((H, W), bool)
    m[y0:y0 + th, x0:x0 + tw] = True
    return img, m, (x0 + tw / 2, y0 + th - 0.10 * th)


def run(frames, masks, trust=True, pose_scales=None):
    a = ObjectAnchor(AnchorConfig(work_width=W))
    out = []
    for i, (img, m) in enumerate(zip(frames, masks)):
        out.append(a.update(img, m, True, trust, (W, H), None if pose_scales is None else pose_scales[i]))
    return a, out


def test_bottom_center_of_a_mask():
    m = np.zeros((H, W), bool)
    m[100:160, 200:400] = True
    x, y, h, w = bottom_center(m, 0.2, 0.1, 8)
    assert x == pytest.approx(299.5, abs=1) and y == pytest.approx(159 - 0.1 * 59, abs=1) and h == pytest.approx(59, abs=1) and w == pytest.approx(199, abs=1)
    assert bottom_center(np.zeros((H, W), bool), 0.2, 0.1, 8) is None
    tiny = np.zeros((H, W), bool)
    tiny[10:14, 10:14] = True
    assert bottom_center(tiny, 0.2, 0.1, 8) is None


def test_follows_the_object_while_the_segmentation_is_dragged_around_by_a_hand():
    frames, masks, truth, bad = [], [], [], []
    for i in range(70):
        x0, y0 = 120 + 4 * i, 150 + 18 * np.sin(i / 9)
        img, m, bc = frame(x0, y0)
        if 10 <= i < 60:                              # 손으로 쥔다: 마스크가 위로 늘어나고(손 덩어리) 오른쪽이 잘려 나간다
            m = m.copy()
            m[max(int(y0) - 70, 0):int(y0), int(x0):int(x0) + 90] = True
            m[:, int(x0) + 120:] &= False
        frames.append(img); masks.append(m); truth.append(bc)
        b = bottom_center(m, 0.2, 0.1, 8)
        bad.append(np.hypot(b[0] - bc[0], b[1] - bc[1]) if b else 0.0)
    _, out = run(frames, masks)
    err = np.array([np.hypot(o.xy[0] - t[0], o.xy[1] - t[1]) for o, t in zip(out, truth)])
    assert float(err[10:60].max()) < 4.0              # 손 마스크 없이(trust=True)도, 영역 크기가 기대와 다르면 당기지 않아 바닥 가운데에 머문다
    assert float(np.max(bad[10:60])) > 25.0           # 같은 구간에서 프레임별 마스크 측정은 크게 어긋난다
    assert all(o.valid for o in out) and out[-1].source == "flow"


def test_without_trusting_the_mask_it_still_follows_by_flow_alone():
    frames, masks, truth = [], [], []
    for i in range(50):
        img, m, bc = frame(100 + 5 * i, 140 + 12 * np.cos(i / 7))
        m = m.copy(); m[:, int(100 + 5 * i) + 100:] &= False        # 항상 반쪽만 보이는 마스크
        frames.append(img); masks.append(m); truth.append(bc)
    # 처음엔 온전한 마스크로 시작
    masks[0] = frame(100, 140 + 12)[1]
    _, out = run(frames, masks, trust=False)
    err = [np.hypot(o.xy[0] - t[0], o.xy[1] - t[1]) for o, t in zip(out, truth)]
    assert max(err[1:]) < 5.0


def test_scale_is_measured_from_the_flow_not_the_mask():
    frames, masks, scales = [], [], []
    for i in range(40):
        sc = 1.0 + 0.005 * i                                          # 카메라 쪽으로 20% 다가온다
        img, m, _ = frame(150, 120, sc)
        m = m.copy()
        if i % 2:                                                      # 마스크 크기는 프레임마다 흔들린다
            m[:, :int(150 + 40)] &= False
        frames.append(img); masks.append(m); scales.append(sc)
    a, out = run(frames, masks, trust=False, pose_scales=[1.0] * 40)  # 포즈 크기는 1.0 으로 고정(분할이 못 믿을 때)
    assert out[0].scale == pytest.approx(1.0, abs=1e-6)
    assert out[-1].scale == pytest.approx(scales[-1], rel=0.03)


def test_reinit_when_flow_is_lost_and_generation_advances():
    img0, m0, _ = frame(100, 140)
    a = ObjectAnchor(AnchorConfig(work_width=W))
    a.update(img0, m0, True, True, (W, H))
    g = a.generation
    flat = np.full((H, W), 128, np.uint8)                              # 무늬가 사라져 흐름을 못 믿는다
    img1, m1, bc = frame(300, 200)
    for _ in range(8):
        a.update(flat, m1, True, False, (W, H))
    st = a.update(img1, m1, True, False, (W, H))
    assert a.generation > g                                             # 마스크에서 다시 찍었다
    assert abs(st.xy[0] - bc[0]) < 8 and abs(st.xy[1] - bc[1]) < 8


def test_holds_while_invisible_and_scales_to_the_original_resolution():
    img, m, bc = frame(200, 150)
    a = ObjectAnchor(AnchorConfig(work_width=W // 2))
    g = cv2.resize(img, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
    mm = cv2.resize(m.astype(np.uint8), (W // 2, H // 2), interpolation=cv2.INTER_NEAREST) > 0
    st = a.update(g, mm, True, True, (W, H))
    assert st.xy[0] == pytest.approx(bc[0], abs=4) and st.xy[1] == pytest.approx(bc[1], abs=4)      # 원본 좌표로 돌려준다
    held = a.update(g, None, False, False, (W, H))
    assert held.xy == st.xy


# ---------------------------------------------------------------- 파이프라인 연동
def _processor(frame_w=W, frame_h=H):
    from vision_input.capture import Frame
    from vision_input.io.mouse import MouseSettings
    from vision_input.pipeline import TrackedObject, VisionProcessor
    from vision_input.tracking.api import Pose, TrackOutput, TrackState
    from vision_input.tracking.axes import AxisState
    vp = VisionProcessor(None)
    vp.set_ema(False)                                  # 좌표 비교를 위해 EMA 는 끈다
    vp.frame_size = (frame_w, frame_h)
    vp.mouse.configure(MouseSettings(mode="object", object_id=1, coordinate_mode="depth", hand_clicks=False))
    out = TrackOutput(TrackState.TRACKING, (100, 100, 300, 180), Pose(200, 140, 1.0, 0.0, 1.0), None, 1.0)
    vp.objects[1] = TrackedObject(1, "a", "#fff", None, {}, AxisState((frame_w, frame_h)), 80.0, out)  # type: ignore[arg-type]
    return vp, vp.objects[1], Frame, TrackOutput, TrackState, Pose


def test_pipeline_moves_the_cursor_by_the_anchor_and_shows_it_in_the_object_info():
    vp, obj, Frame, TrackOutput, TrackState, Pose = _processor()
    img, mask, bc = frame(100, 100)
    obj.out = TrackOutput(TrackState.TRACKING, (100, 100, 300, 180), Pose(200, 140, 1.0, 0.0, 1.0), mask, 1.0)
    fr = Frame(0, cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), 0.0, 0.0)
    vp._update_anchors(fr)
    info = {"anchor": vp._anchor_norm(obj)}              # object_info 가 보내는 값
    assert info["anchor"] is not None and abs(info["anchor"][0] * W - bc[0]) < 3 and abs(info["anchor"][1] * H - bc[1]) < 3
    center, visible = vp._mouse_object()
    assert visible and center == pytest.approx(tuple(info["anchor"]), abs=1e-3)           # 포즈 중심(200,140)이 아니라 기준점
    from vision_input.io.mouse import MouseSettings
    vp.mouse.configure(MouseSettings(mode="object", object_id=1, coordinate_mode="depth", hand_clicks=False, anchor_cursor=False))
    center, _ = vp._mouse_object()
    assert center == pytest.approx((200 / W, 140 / H), abs=1e-3)                          # 끄면 예전처럼 분할 중심
    assert vp._anchor_norm(obj) is not None                                               # 점 표시는 설정과 무관하게 항상


def test_pipeline_hides_the_anchor_when_the_object_is_not_visible_and_forgets_removed_objects():
    vp, obj, Frame, TrackOutput, TrackState, Pose = _processor()
    img, mask, _ = frame(100, 100)
    obj.out = TrackOutput(TrackState.TRACKING, (100, 100, 300, 180), Pose(200, 140, 1.0, 0.0, 1.0), mask, 1.0)
    fr = Frame(0, cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), 0.0, 0.0)
    vp._update_anchors(fr)
    obj.out = TrackOutput(TrackState.LOST, None, Pose(200, 140, 1.0, 0.0, 1.0), None, 0.0)
    vp._update_anchors(fr)
    assert vp._anchor_norm(obj) is None
    del vp.objects[1]
    vp._update_anchors(fr)
    assert 1 not in vp._anchors
