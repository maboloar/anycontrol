"""획 처음·끝의 삐침 방지: 시작 지연, 끝 정리, 뜬 펜 점 건너뛰기, 뜬 펜촉의 투영."""
import numpy as np
import pytest
from vision_input.pen import PenConfig, PenTracker
from vision_input.pen_floor import FloorDecision

W, H = 1280, 720
WIDTH = 60.0


def _pen(**cfg):
    pen = PenTracker((640, 500), (600, 200), PenConfig(contact_method="floor", **cfg))
    pen.frame_w, pen.frame_h = W, H
    f = pen.floor
    f.floor.k, f.floor.c, f.floor.a = 2.9, -100.0, 0.0           # 바닥 평면이 있다 (ready)
    pen.width = WIDTH
    pen.uncertain = False
    return pen


def _step(pen, t, x, y, hover, dec):
    """한 프레임: 펜촉 위치·바닥 모델의 높이(펜 지름 단위)·접촉 판정을 주고 _decide 를 부른다."""
    pen.tip = np.array([x, y], float)
    pen.y_hist.append(float(y))
    pen.floor.info = {"w": WIDTH, "hover": hover}
    pen.floor_dec = dec
    pen._d_last = 0.0
    xy = pen._drawing_point()
    if xy is not None:
        pen._recent.append((t, xy, pen.hover_px() / WIDTH))
    pen._decide(t)


def _down(onset):
    return FloorDecision(True, onset_t=onset, reason="down F")


CONTACT = FloorDecision(True, reason="contact")


def _run(pen, frames):
    """frames: (t, x, y, hover, decision) 목록 → 마지막에 이탈 판정까지 넣어 닫힌 획을 돌려준다."""
    for f in frames:
        _step(pen, *f)
    return pen.strokes[-1] if pen.strokes else None


def _scene(dt=1 / 30, n=12):
    """안착(처음 3프레임은 아직 y 가 내려가는 중) → 오른쪽으로 긋기 → 들어 올림(y 가 위로, 높이 증가)."""
    fr = []
    for i in range(n):
        t = 1.0 + i * dt
        y = 600 + min(i, 3) * 8.0 - 24.0 if i < 3 else 600.0
        dec = _down(1.0) if i == 0 else CONTACT
        fr.append((t, 700 + 12 * i, y, -0.05, dec))
    return fr


def test_start_delay_skips_the_landing_points():
    pen = _pen()
    for f in _scene()[:6]:
        _step(pen, *f)
    first_t = pen.cur_t[0]
    assert first_t >= 1.0 + pen.cfg.stroke_start_delay_s - 1e-6           # 안착 전 프레임은 그리지 않는다
    assert len(pen.cur) == 6 - sum(1 for f in _scene()[:6] if f[0] < 1.0 + pen.cfg.stroke_start_delay_s)

    off = _pen(stroke_start_delay_s=0.0)
    for f in _scene()[:6]:
        _step(off, *f)
    assert len(off.cur) == 6                                                # 지연 0 이면 예전처럼 모두


def test_end_trim_drops_the_lifting_points_before_the_release_evidence():
    pen = _pen()
    frames = _scene(n=12)
    for f in frames:
        _step(pen, *f)
    t_end = frames[-1][0]
    n_before = len(pen.cur)
    _step(pen, t_end + 1 / 30, 790, 600.0, 0.1, FloorDecision(False, offset_t=t_end, reason="lift"))   # 이탈 근거가 t_end 부터
    stroke = pen.strokes[-1]
    assert len(stroke) < n_before
    assert pen.last_stroke_span[1] <= t_end - pen.cfg.stroke_end_trim_s + 1e-6

    keep = _pen(stroke_end_trim_s=0.0)
    for f in frames:
        _step(keep, *f)
    _step(keep, t_end + 1 / 30, 790, 600.0, 0.1, FloorDecision(False, offset_t=t_end, reason="lift"))
    assert len(keep.strokes[-1]) > len(stroke)                # 정리를 끄면 더 많은 끝 점이 남는다


def test_points_are_not_drawn_while_the_pen_is_lifted_even_if_contact_is_held():
    pen = _pen()
    frames = _scene(n=10)
    for f in frames:
        _step(pen, *f)
    n = len(pen.cur)
    t = frames[-1][0]
    _step(pen, t + 1 / 30, 800, 560.0, 0.6, CONTACT)       # 0.6D 떠 있는데 접촉 유지(디바운스) 중
    assert len(pen.cur) == n                               # 점을 찍지 않는다
    _step(pen, t + 2 / 30, 802, 600.0, -0.05, CONTACT)     # 다시 닿으면 찍는다
    assert len(pen.cur) == n + 1


def test_hovering_tip_is_projected_down_to_where_it_would_touch_but_not_while_in_contact():
    pen = _pen()
    _step(pen, 0.0, 700, 560.0, 0.5, FloorDecision(False, reason="air"))
    hov = pen.hover_px()
    assert hov == pytest.approx(0.5 * WIDTH)
    proj = pen._projected_tip()
    assert proj[1] == pytest.approx(560.0 + (hov - pen.cfg.draw_project_dead * WIDTH))      # 닿을 자리 쪽으로
    assert proj[1] <= 560.0 + hov
    # 안정적으로 닿아 있으면 평면 잡음이 새지 않게 그대로
    pen.contact = True
    pen.floor.info = {"w": WIDTH, "hover": 0.2}
    assert pen._projected_tip()[1] == 560.0
    # 끄면 항상 그대로
    off = _pen(draw_project=False)
    _step(off, 0.0, 700, 560.0, 0.5, FloorDecision(False, reason="air"))
    assert off._projected_tip()[1] == 560.0


def test_manual_and_legacy_paths_keep_the_old_stroke_behavior():
    legacy = PenTracker((640, 500), (600, 200), PenConfig(contact_method="legacy"))
    assert legacy.hover_px() == 0.0 and legacy._hovering(False) is False
    pen = _pen()
    pen.manual_contact = True                                # 수동 누름: floor_auto 가 아니므로 지연 없음
    pen.tip = np.array([700.0, 600.0])
    pen.y_hist.append(600.0)
    pen.floor_dec = None
    pen._decide(1.0)
    pen._decide(1.03)
    assert len(pen.cur) == 2
