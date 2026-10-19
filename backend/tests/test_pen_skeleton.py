"""펜 뼈대: 곧은 막대라는 사실로 손에 가려진 가운데·끝을 채운다."""
import cv2
import numpy as np
import pytest
from vision_input.pen_skeleton import PenSkeleton, fit_axis, visible_runs

TIP = np.array([500.0, 120.0])
TAIL = np.array([140.0, 380.0])
L0 = float(np.linalg.norm(TIP - TAIL))
U = (TIP - TAIL) / L0
TIPX, TAILX = TIP + U * 5, TAIL - U * 5     # cv2.line 은 굵기의 절반만큼 끝이 더 나온다: 마스크 기준 진짜 끝
L = L0 + 10                                  # 기억하는 길이는 마스크로 잰 값
SKIN = (120, 150, 210)


def _scene(hand=None, radius=34, width=10):
    """펜(펜촉 쪽 빨강, 반대쪽 파랑)과 손으로 가린 원. (이미지, 보이는 펜 마스크, 손 마스크)"""
    img = np.full((480, 640, 3), 200, np.uint8)
    pen = np.zeros((480, 640), np.uint8)
    cv2.line(pen, tuple(map(int, TAIL)), tuple(map(int, TIP)), 255, width)
    body = (60, 60, 60)
    cv2.line(img, tuple(map(int, TAIL)), tuple(map(int, TIP)), body, width)
    cv2.line(img, tuple(map(int, TIP - U * 0.15 * L)), tuple(map(int, TIP)), (0, 0, 220), width)
    cv2.line(img, tuple(map(int, TAIL)), tuple(map(int, TAIL + U * 0.15 * L)), (220, 0, 0), width)
    occ = np.zeros((480, 640), bool)
    if hand is not None:
        cv2.circle(img, tuple(map(int, hand)), radius, SKIN, -1)
        o = np.zeros((480, 640), np.uint8)
        cv2.circle(o, tuple(map(int, hand)), radius, 1, -1)
        occ = o > 0
    visible = (pen > 0) & ~occ
    return img, visible, occ


def _err(a, b):
    return float(np.linalg.norm(np.asarray(a) - np.asarray(b)))


def test_fully_visible_pen_gives_both_ends():
    _, mask, _ = _scene()
    sk = PenSkeleton().observe(mask, U, L)
    assert sk.state == "seen" and not sk.hidden
    assert _err(sk.tip, TIPX) < 3 and _err(sk.tail, TAILX) < 3


def test_hand_over_the_middle_is_a_hidden_segment_between_two_visible_pieces():
    _, mask, occ = _scene(hand=(TAIL + TIP) / 2)
    sk = PenSkeleton().observe(mask, U, L, occluder=occ)
    assert sk.state == "middle_hidden" and len(sk.visible) == 2 and len(sk.hidden) == 1
    gap = _err(*sk.hidden[0])
    assert 50 < gap < 90                                   # 원의 지름(68) 근처
    assert _err(sk.tip, TIPX) < 3 and _err(sk.tail, TAILX) < 3


@pytest.mark.parametrize("kind", ["occluder"])
def test_hand_over_the_tip_infers_the_tip_from_the_remembered_length(kind):
    img, mask, occ = _scene(hand=TIP - U * 5, radius=90)    # 펜촉 쪽 약 90px 이 가려짐
    pts = np.array(np.nonzero(mask)[::-1]).T
    assert _err(pts[np.argmax(pts @ U)], TIPX) > 55          # 보이는 끝은 진짜 펜촉이 아니다
    kw = {"occluder": occ} if kind == "occluder" else {"bgr": img}
    sk = PenSkeleton().observe(mask, U, L, **kw)
    assert sk.state == "tip_hidden" and sk.evidence == kind
    assert _err(sk.tip, TIPX) < 5 and _err(sk.tail, TAILX) < 5
    assert len(sk.hidden) == 1 and _err(*sk.hidden[0]) > 40


def test_hand_over_the_tail_end_is_the_tail_that_is_inferred():
    _, mask, occ = _scene(hand=TAIL + U * 5, radius=70)
    sk = PenSkeleton().observe(mask, U, L, occluder=occ)
    assert sk.state == "tail_hidden" and sk.evidence == "occluder"
    assert _err(sk.tip, TIPX) < 5 and _err(sk.tail, TAILX) < 5


def test_short_pen_without_evidence_is_not_extended():
    """카메라 쪽으로 기울여 짧아 보이는 펜(3D 단축)을 가려졌다고 착각해 끝을 늘리지 않는다."""
    img, _, _ = _scene()
    short = np.zeros((480, 640), bool)
    cv2.line(short.view(np.uint8), tuple(map(int, TAIL)), tuple(map(int, TAIL + U * 0.6 * L0)), 1, 10)
    sk = PenSkeleton().observe(short, U, L, bgr=img)         # 끝 너머는 피부색이 아니다
    assert sk.state == "seen" and sk.evidence == ""
    assert _err(sk.tip, TAIL + U * 0.6 * L0) < 8


def test_stray_blob_next_to_the_pen_does_not_bend_the_axis():
    _, mask, _ = _scene()
    mask = mask.copy()
    cv2.circle(mask.view(np.uint8), (300, 300), 22, 1, -1)  # 펜 옆 손가락 조각
    c, u, P, w = fit_axis(mask)
    assert abs(float(u @ U)) > 0.995


def test_end_colors_detect_a_flipped_direction():
    img, mask, _ = _scene()
    ps = PenSkeleton()
    sk = ps.observe(mask, U, L)
    ps.learn_ends(img, mask, sk, 10)
    assert ps.tip_lab is not None
    assert not ps.should_flip(img, mask, sk, 10)
    reversed_sk = PenSkeleton().observe(mask, -U, L)       # 방향을 반대로 잡으면 펜촉/꼬리가 바뀐다
    assert _err(reversed_sk.tip, TAILX) < 4
    assert ps.should_flip(img, mask, reversed_sk, 10)


def test_visible_runs_ignore_tiny_gaps():
    s = np.concatenate([np.arange(0, 100, 0.5), np.arange(104, 200, 0.5)])
    assert len(visible_runs(s, 10)) == 1                   # 4px 틈은 같은 구간
    s2 = np.concatenate([np.arange(0, 100, 0.5), np.arange(140, 200, 0.5)])
    assert len(visible_runs(s2, 10)) == 2


def test_pose_prediction_alone_never_extends_an_end():
    _, mask, _ = _scene(hand=TIP - U * 5, radius=90)
    sk = PenSkeleton().observe(mask, U, L, pred_tip=TIP, pred_tail=TAIL)     # 손의 증거 없음
    assert sk.state == "seen" and not sk.hidden


def test_skin_color_alone_never_hides_the_tip_but_can_hide_the_tail():
    img, mask, _ = _scene(hand=TIP - U * 5, radius=90)
    assert PenSkeleton().observe(mask, U, L, bgr=img).state == "seen"        # 책상이 피부색과 비슷할 수 있다
    img2, mask2, _ = _scene(hand=TAIL + U * 5, radius=90)
    sk = PenSkeleton().observe(mask2, U, L, bgr=img2)
    assert sk.state == "tail_hidden" and sk.evidence == "skin" and _err(sk.tail, TAILX) < 5
