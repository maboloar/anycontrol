"""다중 물체: 같은 색 물체 둘이 맞닿았다 떨어져도 ID 가 바뀌지 않는다 (물체끼리 배타 + 다른 물체 = 방해물)."""

import numpy as np

from vision_input.tracking import InitPrompt
from vision_input.tracking.vi_tracker import TrackerConfig, ViTracker


def _frame(xa: float, xb: float, rng) -> np.ndarray:
    img = (170 + rng.integers(-6, 7, (240, 480, 3))).astype(np.uint8)
    for x in (xa, xb):
        x = int(x)
        img[90:150, x - 30:x + 30] = (40, 40, 200)
        img[100:140:8, x - 20:x + 20] = (200, 220, 40)  # 무늬 (점 추적용)
    return img


def test_two_identical_objects_touch_and_separate_without_swap():
    rng = np.random.default_rng(0)
    tr = ViTracker(TrackerConfig(tier1="off"))
    # 폭 60 인 두 물체의 중심이 30 까지 가까워진다 (절반이 겹침) → 다시 떨어짐
    n = 35
    xs = [(120 + 105 * i / n, 360 - 105 * i / n) for i in range(n)] + \
         [(225 - 105 * i / n, 255 + 105 * i / n) for i in range(n)]
    f0 = _frame(*xs[0], rng)
    for oid, x in ((1, xs[0][0]), (2, xs[0][1])):
        m = np.zeros((240, 480), bool)
        m[90:150, int(x) - 30:int(x) + 30] = True
        tr.add(f0, oid, InitPrompt(mask=m))
    out = {}
    overlap_max = 0
    for i, (xa, xb) in enumerate(xs[1:], 1):
        out = tr.step(_frame(xa, xb, rng), i / 30)
        if out[1].mask is not None and out[2].mask is not None:
            overlap_max = max(overlap_max, int((out[1].mask & out[2].mask).sum()))
    assert overlap_max == 0  # 보이는 마스크는 서로 배타
    xa, xb = xs[-1]
    assert out[1].pose is not None and out[2].pose is not None
    assert abs(out[1].pose.cx - xa) < 20, (out[1].pose.cx, xa)
    assert abs(out[2].pose.cx - xb) < 20, (out[2].pose.cx, xb)
