"""정지 배경 모델(scene.py)과 추적기·등록·파이프라인 연동 (모델 없이)."""

import cv2
import numpy as np

from vision_input.tracking.api import InitPrompt, TrackState
from vision_input.tracking.register import choose_candidate
from vision_input.tracking.scene import SceneConfig, SceneModel
from vision_input.tracking.segment import SegResult
from vision_input.tracking.vi_tracker import TrackerConfig, ViTracker

H, W = 360, 640


def desk(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = np.zeros((H, W, 3), np.float32)
    img[:] = (150, 170, 190)
    img += cv2.GaussianBlur(rng.normal(0, 25, (H, W, 3)).astype(np.float32), (0, 0), 6)
    img[: H // 3] = (90, 110, 80)  # 벽
    return np.clip(img, 0, 255).astype(np.uint8)


def noisy(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    return np.clip(img.astype(np.float32) + rng.normal(0, 2, img.shape), 0, 255).astype(np.uint8)


def with_box(img: np.ndarray, x: int, y: int, w: int = 80, h: int = 50, color=(40, 40, 200)) -> np.ndarray:
    out = img.copy()
    cv2.rectangle(out, (x, y), (x + w, y + h), color, -1)
    cv2.putText(out, "AB", (x + 10, y + 35), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    return out


def box_mask(x: int, y: int, w: int = 80, h: int = 50) -> np.ndarray:
    m = np.zeros((H, W), bool)
    m[y:y + h + 1, x:x + w + 1] = True
    return m


def learn(sc: SceneModel, img: np.ndarray, n: int = 10, t0: float = 0.0, ex=None, seed: int = 1) -> float:
    rng = np.random.default_rng(seed)
    t = t0
    for _ in range(n):
        sc.update(noisy(img, rng), t, ex)
        t += 1 / 30
    return t


# ---------------------------------------------------------------- 배경 모델 단위
def test_new_object_is_foreground_and_desk_is_background():
    sc = SceneModel(SceneConfig(depth=False))
    bg = desk()
    t = learn(sc, bg)
    sc.update(with_box(bg, 300, 200), t)
    lg = sc.logit(t)
    assert sc.valid and lg is not None and lg.shape == (H, W)
    assert np.median(lg[box_mask(305, 205, 70, 40)]) > 2.0
    assert np.median(lg[250:350, 20:200]) < -1.0


def test_global_lighting_change_is_not_foreground():
    sc = SceneModel(SceneConfig(depth=False))
    bg = desk()
    t = learn(sc, bg)
    dim = (bg.astype(np.float32) * 0.75).astype(np.uint8)
    sc.update(dim, t)
    lg = sc.logit(t)
    assert sc.valid and lg is not None
    assert (lg > 1.0).mean() < 0.05


def test_small_camera_shift_is_compensated():
    sc = SceneModel(SceneConfig(depth=False))
    bg = desk()
    t = learn(sc, bg)
    shifted = cv2.warpAffine(bg, np.float32([[1, 0, 4], [0, 1, 3]]), (W, H), borderMode=cv2.BORDER_REPLICATE)
    sc.update(shifted, t)
    assert sc.valid
    assert sc.changed_frac < 0.1


def test_whole_scene_change_is_invalid_then_relearned():
    sc = SceneModel(SceneConfig(depth=False))
    t = learn(sc, desk(0))
    rng = np.random.default_rng(7)                    # 완전히 다른 장면 (카메라를 다른 곳으로 돌림)
    other = cv2.resize(rng.integers(0, 255, (H // 8, W // 8, 3)).astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST)
    sc.update(other, t)
    assert not sc.valid and sc.logit(t) is None
    t = learn(sc, other, n=40, t0=t + 1 / 30)
    assert sc.stats["relearn"] >= 1 and sc.valid
    assert (sc.logit(t) > 1.0).mean() < 0.05


def test_people_walking_in_the_far_background_do_not_switch_the_model_off():
    """수평 카메라 시연: 물체는 앞 책상에 있고 뒤쪽(화면 위쪽)으로 사람들이 계속 오간다. 사람이 배경의 20~30% 를 덮어도
    배경 모델은 꺼지지 않아야 하고(카메라 이동이 아님), 앞 물체 판정은 그대로여야 한다."""
    sc = SceneModel(SceneConfig(depth=False))
    bg = desk()
    t = learn(sc, bg)
    rng = np.random.default_rng(5)
    valid = []
    for i in range(90):
        img = with_box(bg, 300, 230)
        for k in range(4):                            # 사람 4명: 화면 위쪽 절반을 좌우로 지나간다
            x = int((60 * k + 9 * i * (1 if k % 2 else -1)) % W)
            cv2.ellipse(img, (x, 90), (40, 85), 0, 0, 360, (30 + 50 * k, 60, 160 - 30 * k), -1)
        sc.update(noisy(img, rng), t)
        valid.append(sc.valid)
        t += 1 / 30
    assert sum(valid) >= 85 and sc.stats["relearn"] == 0
    lg = sc.logit(t)
    assert np.median(lg[box_mask(305, 235, 70, 40)]) > 2.0
    assert np.median(lg[300:350, 20:200]) < -1.0


def test_excluded_object_is_not_absorbed_but_untracked_one_is():
    sc = SceneModel(SceneConfig(depth=False, absorb_s=2.0))
    bg = desk()
    t = learn(sc, bg)
    img = with_box(with_box(bg, 100, 200), 400, 200, color=(30, 200, 30))
    ex = box_mask(95, 195, 90, 60)   # 왼쪽 물체만 추적 중
    t = learn(sc, img, n=150, t0=t, ex=ex)   # 5초
    lg = sc.logit(t)
    assert np.median(lg[box_mask(105, 205, 70, 40)]) > 2.0    # 추적 물체는 계속 전경
    assert np.median(lg[box_mask(405, 205, 70, 40)]) < 1.0    # 추적하지 않는 물건은 배경이 됐다


def test_place_left_by_registered_object_becomes_background():
    """등록 때 물체가 있던 자리(모름)는 물체가 떠나면 책상으로 채워져야 한다 (물체 색으로 굳으면 유령)."""
    sc = SceneModel(SceneConfig(depth=False))
    bg = desk()
    first = with_box(bg, 300, 200)
    sc.update(first, 0.0, box_mask(290, 190, 100, 70))
    t = learn(sc, bg, n=20, t0=1 / 30)       # 물체가 떠남
    lg = sc.logit(t)
    assert np.median(lg[box_mask(305, 205, 70, 40)]) < 0.0


def test_shadow_is_weak_foreground():
    sc = SceneModel(SceneConfig(depth=False))
    bg = desk()
    t = learn(sc, bg)
    sh = bg.copy()
    sh[250:320, 300:420] = (sh[250:320, 300:420].astype(np.float32) * 0.7).astype(np.uint8)
    sc.update(sh, t)
    assert np.median(sc.logit(t)[260:310, 310:410]) <= 0.5


def test_depth_adds_near_objects_and_suppresses_reflection_but_never_erases_flat_objects():
    sc = SceneModel(SceneConfig(depth=True))
    bg = desk()
    yy = np.linspace(0.2, 0.9, H, dtype=np.float32)[:, None] * np.ones((1, W), np.float32)   # 책상: 아래가 가깝다
    t = 0.0
    rng = np.random.default_rng(3)
    for _ in range(10):
        sc.push_depth(yy + rng.normal(0, 0.003, yy.shape).astype(np.float32), t)
        sc.update(noisy(bg, rng), t)
        t += 1 / 30
    img = bg.copy()
    # 같은 색이라 색으로는 거의 안 보이는 솟은 물체 + 약한 반사 + 색이 분명한 납작한 물체
    img[220:270, 100:180] = np.clip(img[220:270, 100:180].astype(np.int16) + 6, 0, 255).astype(np.uint8)
    img[280:330, 300:380] = np.clip(img[280:330, 300:380].astype(np.int16) + 18, 0, 255).astype(np.uint8)
    img = with_box(img, 480, 250)
    d = yy.copy()
    d[220:270, 100:180] += 0.25
    sc.push_depth(2.0 * d + 0.1, t)   # 스케일·이동이 다른 상대 깊이
    sc.update(img, t)
    lg = sc.logit(t, depth_weight=1.0)
    assert sc.depth_logit is not None
    color = cv2.resize(sc.color_logit, (W, H))
    assert np.median(color[230:260, 110:170]) < 0.0          # 색으로는 책상
    assert np.median(lg[230:260, 110:170]) > 1.0              # 깊이로 솟은 물체
    assert np.median(lg[285:325, 305:375]) <= 0.0
    assert np.median(lg[255:295, 485:555]) > 2.0


# ---------------------------------------------------------------- 추적기 연동
def test_tracker_does_not_claim_object_after_it_leaves_the_frame():
    bg = desk()
    trk = ViTracker(TrackerConfig(tier1="off"))
    rng = np.random.default_rng(0)
    trk.add(noisy(with_box(bg, 300, 200), rng), 1, InitPrompt(box=(300, 200, 381, 251)))
    t, x, said = 0.0, 300, []
    for i in range(1, 150):
        t = i / 30
        x = 300 + min(i, 60) * 8 if i < 90 else x   # 오른쪽으로 나가서 돌아오지 않는다
        frame = with_box(bg, x, 200) if x < W else bg
        out = trk.step(noisy(frame, rng), t)[1]
        if i >= 100:
            said.append(out.state.visible)
    assert trk.scene.valid
    assert sum(said) <= 5


def test_scene_is_off_for_pens_and_when_disabled():
    trk = ViTracker(TrackerConfig(tier1="off"))
    img = with_box(desk(), 300, 200)
    trk.add(img, 1, InitPrompt(mask=box_mask(300, 200), kind="pen"))
    for i in range(1, 5):
        trk.step(img, i / 30)
    assert trk.scene.valid
    assert trk._scene_logit(trk.tracks[1], 4 / 30) is None
    off = ViTracker(TrackerConfig(tier1="off", scene=SceneConfig(enabled=False)))
    off.add(img, 1, InitPrompt(mask=box_mask(300, 200)))
    off.step(img, 1 / 30)
    assert off.scene.logit(1 / 30) is None and off.scene.mean is None


def test_observe_learns_background_before_any_object():
    trk = ViTracker(TrackerConfig(tier1="off"))
    bg = desk()
    for i in range(5):
        trk.observe(bg, i / 30)
    assert trk.scene.valid and not trk.tracks


def test_sim_depth_is_delivered_after_latency():
    trk = ViTracker(TrackerConfig(tier1="off"))
    calls = []

    def predict(img):  # type: ignore[no-untyped-def]
        calls.append(img.shape)
        return np.full(img.shape[:2], 0.5, np.float32)
    trk.depth_predict = predict
    trk.t1_mode = "sim"
    bg = desk()
    for i in range(10):
        trk.observe(bg, i / 30)
    assert calls and trk.scene.dmean is not None


# ---------------------------------------------------------------- 등록 후보
def test_choose_candidate_avoids_leaking_into_known_background():
    obj = box_mask(300, 200)
    leak = obj | box_mask(380, 200, 120, 50)    # 물체 + 옆 책상
    scene = np.full((H, W), -3.0, np.float32)
    scene[obj] = 3.0
    seg = SegResult([leak, obj], [0.95, 0.90])
    box = (300.0, 200.0, 500.0, 251.0)          # 사용자가 넓게 그린 박스: 박스만 보면 번진 후보가 맞는다
    assert choose_candidate(seg, box)[0] == 0
    assert choose_candidate(seg, box, scene)[0] == 1
    # 물체가 처음부터 있어 배경에 배어 있으면 (모든 후보가 배경처럼 보임) 순서를 바꾸지 않는다
    assert choose_candidate(seg, box, np.full((H, W), -3.0, np.float32))[0] == 0


# ---------------------------------------------------------------- 파이프라인
def test_pipeline_wires_depth_and_observes_without_objects():
    from vision_input.capture import Frame
    from vision_input.pipeline import VisionProcessor

    proc = VisionProcessor(lambda: ViTracker(TrackerConfig(tier1="off")), hand_worker=None)
    assert callable(proc.tracker.depth_submit)
    bg = desk()
    for i in range(5):
        proc.process(Frame(i, bg, i / 30, i / 30))
    assert proc.tracker.scene.valid
    snap = proc.scene_snapshot()
    assert snap is not None and snap.shape == (H, W)
