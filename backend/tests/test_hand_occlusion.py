"""손 인식 가림 처리: 손 마스크 생성, 트래커의 손 영역 제외·쥠 상태, API 토글."""

import numpy as np

from vision_input.eval.harness import run_synth
from vision_input.eval.synth import SynthSpec
from vision_input.hands.detector import Hand, HandFrame
from vision_input.pipeline import hand_mask
from vision_input.tracking.vi_tracker import TrackerConfig, ViTracker

from .handkit import make_hand


def test_hand_mask_covers_landmarks():
    h = make_hand(0.5, 0.5, 0.15)
    m = hand_mask(HandFrame(0.0, [h]), (640, 480))
    assert m is not None and m.dtype == bool
    p = (h.points * [640, 480]).astype(int)
    assert m[p[:, 1].clip(0, 479), p[:, 0].clip(0, 639)].all()
    assert m.mean() < 0.3
    assert hand_mask(HandFrame(0.0, []), (640, 480)) is None
    assert isinstance(h, Hand)


def _vi_off():
    return ViTracker(TrackerConfig(tier1="off"))


def test_oracle_hands_keep_grasped_object_and_report_grasped():
    spec = SynthSpec("tune/dark-grasp", "dark", ("grasp",), seed=3, frames=90)
    with_hands = run_synth(_vi_off, spec, hands=True)
    without = run_synth(_vi_off, spec, hands=False)
    assert with_hands["success"] >= without["success"] - 0.05
    assert with_hands["success"] > 0.5


def test_grasped_state_when_hand_covers_most():
    img = np.full((240, 320, 3), 180, np.uint8)
    img[80:160, 100:220] = (30, 60, 200)
    m = np.zeros((240, 320), bool)
    m[80:160, 100:220] = True
    tr = _vi_off()
    tr.add(img, 1, __import__("vision_input.tracking", fromlist=["InitPrompt"]).InitPrompt(mask=m))
    hand = np.zeros_like(m)
    hand[70:170, 95:200] = True  # 물체의 약 83% 를 덮음
    img2 = img.copy()
    img2[hand] = (140, 170, 230)
    tr.set_occluders(hand)
    out = tr.step(img2, 1 / 30)[1]
    assert out.debug["hand_frac"] > 0.5
    assert out.state.value in ("grasped", "occluded")
    if out.mask is not None:
        assert not (out.mask & hand).any()  # 손 영역은 물체 마스크에 들어가지 않는다
