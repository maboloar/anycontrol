"""물체 터치: 손이 물체의 원래 윤곽 안을 실제로 가리는 증거를 확인한다.

손끝뿐 아니라 손바닥·손가락 옆면도 포함한다. 손이 없거나 물체와 멀면
배경/살색만으로 켜지지 않는다. 작은 crop에서 두 프레임 확인하며 큰 모델을 추가하지 않는다.
단일 RGB 영상은 매우 가까운 공중 가림과 물리적 접촉을 완전히 구분하지 못한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from .hands.detector import CONNECTIONS, HandFrame

CROP = 96


def _round(p: np.ndarray | None) -> list[float] | None:
    return None if p is None else [round(float(p[0]), 4), round(float(p[1]), 4)]


def _lab(bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)


def skin_mask(bgr: np.ndarray) -> np.ndarray:
    """살색 (YCrCb 범위). 조명에 따라 틀릴 수 있어 보조 증거로만 쓴다."""
    ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    cr, cb = ycc[..., 1], ycc[..., 2]
    return (cr >= 135) & (cr <= 180) & (cb >= 80) & (cb <= 135)


def _hand_area(regions: list[np.ndarray], bounds, shape) -> np.ndarray:
    """손바닥과 손가락 뼈 주변만 사용한다. 벌어진 손가락 사이를 채우지 않는다."""
    h, w = shape
    area = np.zeros((h, w), np.uint8)
    # 관절점은 손가락 가장자리보다 안쪽에 있고 조금씩 어긋나므로 손가락 굵기만큼 넉넉히 잡는다
    pad = max(4, min(18, round(.026 / max(bounds[2] - bounds[0], bounds[3] - bounds[1]) * max(w, h))))
    for points in regions:
        xy = np.rint((points - [bounds[0], bounds[1]]) / [bounds[2] - bounds[0], bounds[3] - bounds[1]] * [w, h])
        # Clip before integer conversion; off-screen landmarks must not overflow OpenCV.
        xy = np.clip(xy, -10000, 10000).astype(np.int32)
        cv2.fillConvexPoly(area, cv2.convexHull(xy[[0, 1, 5, 9, 13, 17]]), 1)
        for a, b in CONNECTIONS:
            cv2.line(area, tuple(xy[a]), tuple(xy[b]), 1, 2 * pad)
        for x, y in xy:
            cv2.circle(area, (int(x), int(y)), pad, 1, -1)
    return area > 0


def _foreground(cur: np.ndarray, ref: np.ndarray, ref_skin: np.ndarray, ref_image: np.ndarray, img: np.ndarray,
                diff: np.ndarray, core: np.ndarray, near: np.ndarray, thr: float) -> np.ndarray:
    """손 외형이 물체 표면을 대체한 픽셀. 그림자/경계 바깥 배경은 증거가 아니다.

    현재 손의 바깥쪽에서 관측한 색으로 내부 가림을 확인한다. 샘플을 얻을 수
    없는 작은 접촉은 새로 나타난 살색 + 충분한 색차를 보조 증거로 쓴다.
    피부색을 필수 조건으로 사용하지 않는다.
    """
    delta = cur - ref
    chroma = np.linalg.norm(delta[..., 1:], axis=2)
    # Colour is supplementary; external hand samples also support dark skin/gloves.
    evidence = skin_mask(img) & ~ref_skin & (chroma >= 14)
    eligible = core & near & (diff > thr)
    outside = ~cv2.dilate(core.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    samples = cur[near & outside & (diff > thr)]
    if len(samples) >= 4:
        # A few dominant colours allow different skin tones/gloves without a new model.
        bins = (samples / 16).astype(np.int32)
        packed = (bins[:, 0] << 8) | (bins[:, 1] << 4) | bins[:, 2]
        _, inv, counts = np.unique(packed, return_inverse=True, return_counts=True)
        current, reference = cur[eligible], ref[eligible]
        matches = evidence[eligible]
        for k in np.argsort(counts)[-4:]:
            if counts[k] < max(4, len(samples) * .02):
                continue
            colour = np.median(samples[inv == k], axis=0)
            dc, dr = current - colour, reference - colour
            current_distance = np.sqrt(.25 * dc[:, 0] ** 2 + np.sum(dc[:, 1:] ** 2, axis=1))
            reference_distance = np.sqrt(.25 * dr[:, 0] ** 2 + np.sum(dr[:, 1:] ** 2, axis=1))
            matches |= (current_distance < 18) & (reference_distance > current_distance + 10)
        evidence[eligible] = matches
    # A local shadow scales RGB intensity while preserving the surface colour.
    # Prefer no press when an untextured surface provides only this ambiguous cue.
    current_rgb, reference_rgb = img.astype(np.float32), ref_image.astype(np.float32)
    cs, rs = current_rgb.sum(axis=2) + 1, reference_rgb.sum(axis=2) + 1
    colour_distance = np.linalg.norm(current_rgb / cs[..., None] - reference_rgb / rs[..., None], axis=2)
    shadow = (cs < rs * .92) & (colour_distance < .035)
    return evidence & eligible & ~shadow


def _surface_still_visible(cur: np.ndarray, ref: np.ndarray, front: np.ndarray) -> bool:
    """그림자/반사 아래로 물체 무늬가 그대로 보이면 전경 가림으로 세지 않는다.

    피부 윤곽 경계는 제외하고 내부의 고주파 밝기 무늬를 비교한다. 무늬 없는
    물체·작은 접촉에는 이 판정만으로 거절하지 않는다.
    """
    inside = cv2.erode(front.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    if int(inside.sum()) < 16:
        return False
    a = ref[..., 0] - cv2.GaussianBlur(ref[..., 0], (5, 5), 1)
    b = cur[..., 0] - cv2.GaussianBlur(cur[..., 0], (5, 5), 1)
    a, b = a[inside], b[inside]
    a, b = a - a.mean(), b - b.mean()
    aa, bb = float(a @ a), float(b @ b)
    if aa < len(a) * 2 or bb < aa * .0025:
        return False
    return float(a @ b) / np.sqrt(aa * bb) > .94


@dataclass
class _Run:
    on: bool = False
    hits: int = 0
    misses: int = 0
    box: tuple[float, float, float, float] | None = None     # 기준 박스 (정규화, 여유 포함)
    ref: np.ndarray | None = None                            # 기준 모습 (Lab, CROP 크기)
    ref_image: np.ndarray | None = None                      # RGB 비율을 보존하는 그림자 검사
    ref_skin: np.ndarray | None = None                       # 기준 영상의 살색 (보조 검사 캐시)
    area: np.ndarray | None = None                           # 비교할 곳 (물체 마스크를 넓힌 것)
    core: np.ndarray | None = None                           # 넓히지 않은 물체 내부 (접촉 증거 전용)
    contact: np.ndarray | None = None                        # 연속 프레임에서 같은 가림인지 확인
    foreground: float = 0.0
    noise: float = 6.0                                       # 손 없을 때 색 차이 평균
    moved_since: float | None = None
    change: float = 0.0                                      # 마지막 바뀐 비율 (물체 면적 대비)
    skin: float = 0.0
    reason: str = ""
    point: np.ndarray | None = None


class ObjectTouch:
    HAND_HOLD_S = 0.6   # 손 인식이 잠깐 끊겨도 이 시간 동안은 마지막 손 위치를 쓴다

    def __init__(self, sensitivity: float = 0.7) -> None:
        self.sensitivity = sensitivity
        self.runs: dict[int, _Run] = {}
        self._last_regions: list[np.ndarray] = []
        self._last_hand_t = -1e9

    @property
    def min_change(self) -> float:
        """닿음으로 볼 바뀐 면적 (물체 면적 대비): 민감도 0 → 0.06, 1 → 0.005"""
        return 0.06 - 0.055 * float(np.clip(self.sensitivity, 0, 1))

    @staticmethod
    def _crop(frame: np.ndarray, box: tuple[float, float, float, float]) -> tuple[np.ndarray, tuple[int, int, int, int]] | None:
        H, W = frame.shape[:2]
        x0, y0, x1, y1 = int(box[0] * W), int(box[1] * H), int(np.ceil(box[2] * W)), int(np.ceil(box[3] * H))
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        if x1 - x0 < 6 or y1 - y0 < 6:
            return None
        s = CROP / max(x1 - x0, y1 - y0)
        size = (max(4, round((x1 - x0) * s)), max(4, round((y1 - y0) * s)))
        return cv2.resize(frame[y0:y1, x0:x1], size, interpolation=cv2.INTER_AREA), (x0, y0, x1, y1)

    @staticmethod
    def _area(mask: np.ndarray | None, box: tuple[float, float, float, float], size: tuple[int, int], *, expand: bool = True) -> np.ndarray:
        """기준 박스 영역의 물체 마스크를 잘라 crop 크기로 맞추고 조금 넓힌다. 마스크가 없으면 박스 가운데 80%."""
        w, h = size
        if mask is None or not mask.any():
            a = np.zeros((h, w), bool)
            a[int(.1 * h): int(.9 * h), int(.1 * w): int(.9 * w)] = True
            return a
        mh, mw = mask.shape
        x0, y0 = int(box[0] * mw), int(box[1] * mh)
        x1, y1 = int(np.ceil(box[2] * mw)), int(np.ceil(box[3] * mh))
        sub = mask[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]
        if sub.size == 0 or not sub.any():
            return ObjectTouch._area(None, box, size, expand=expand)
        a = cv2.resize(sub.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)
        return (cv2.dilate(a, np.ones((5, 5), np.uint8)) if expand else a) > 0

    def _capture(self, run: _Run, frame: np.ndarray, box: tuple[float, float, float, float], mask: np.ndarray | None) -> None:
        bw, bh = box[2] - box[0], box[3] - box[1]
        m = 0.06 * max(bw, bh)
        rb = (max(0., box[0] - m), max(0., box[1] - m), min(1., box[2] + m), min(1., box[3] + m))
        c = self._crop(frame, rb)
        if c is None:
            return
        img, _ = c
        run.box, run.ref = rb, _lab(img)
        run.ref_skin = skin_mask(img)
        run.ref_image = img.copy()
        run.area = self._area(mask, rb, (img.shape[1], img.shape[0]))
        strict = self._area(mask, rb, (img.shape[1], img.shape[0]), expand=False)
        inner = cv2.erode(strict.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        run.core = inner if inner.sum() >= strict.sum() * .5 else strict
        run.contact = None
        run.moved_since = None

    def update(self, frame: np.ndarray | None, hf: HandFrame | None, t: float,
               objs: dict[int, tuple[tuple[float, float, float, float] | None, np.ndarray | None]]) -> dict[int, bool]:
        """frame: 원본 BGR. objs: 물체 id → (정규화 박스 또는 None(안 보임), 추적 마스크(가림 복원 가능) 또는 None). 반환: id → 닿음."""
        hands = [] if hf is None else [h for h in hf.hands if h.score >= 0.4 and np.isfinite(h.points).all()]
        regions = [h.points for h in hands]
        seen = regions                            # 이번 프레임에 실제로 보인 손 (기준 모습 촬영 판단용)
        if regions:
            self._last_regions, self._last_hand_t = regions, t
        elif t - self._last_hand_t <= self.HAND_HOLD_S:
            regions = self._last_regions          # 손 인식 깜빡임: 직전 손 위치를 잠깐 유지
        has_hand = bool(regions)
        out: dict[int, bool] = {}
        for oid in list(self.runs):
            if oid not in objs:
                del self.runs[oid]
        for oid, (box, mask) in objs.items():
            run = self.runs.setdefault(oid, _Run())
            previous = run.contact
            touched = self._judge(run, frame, box, mask, regions, t, seen)
            # 물체가 안 보이거나 손이 오래 없을 때만 바로 끈다. 그 밖의 한두 프레임 실패는 아래의 3번 연속 규칙으로 넘긴다
            cleared = run.reason == "no-front-occlusion" and run.change < self.min_change * .5    # 손이 확실히 떨어짐
            if not has_hand or cleared or run.reason in {"not-visible", "no-frame", "await-object-mask", "no-near-hand"}:
                run.on, run.hits, run.misses, run.point = False, 0, 0, None
            if touched:
                # Two spatially consistent frames; unrelated one-frame changes cannot add up.
                consistent = previous is not None and run.contact is not None and previous.shape == run.contact.shape and bool(
                    (cv2.dilate(previous.astype(np.uint8), np.ones((11, 11), np.uint8)).astype(bool) & run.contact).any())
                run.hits, run.misses = (run.hits + 1 if consistent else 1), 0
                if run.hits >= 2:
                    run.on = True
            else:
                run.contact = None
                run.misses, run.hits = run.misses + 1, 0
                if run.misses >= 3:
                    run.on, run.point = False, None
            out[oid] = run.on
        return out

    def _judge(self, run: _Run, frame: np.ndarray | None, box, mask, regions, t: float, seen: list | None = None) -> bool:
        run.change = run.skin = run.foreground = 0.0
        run.reason = ""
        if frame is None:
            run.reason = "no-frame"
            return False
        if box is None:
            run.reason = "not-visible"
            return False
        if mask is None or not mask.any():
            run.reason = "await-object-mask"
            return False
        if run.ref is None:
            # A baseline containing a hand would make its removal look like a new press.
            size = (64, 64)
            area = self._area(mask, box, size, expand=False)
            if (_hand_area(regions if seen is None else seen, box, area.shape) & area).any():
                run.reason = "await-clear-object"
                return False
            self._capture(run, frame, box, mask)
            return False
        rb = run.box
        assert rb is not None and run.area is not None
        assert run.core is not None and run.ref_skin is not None and run.ref_image is not None
        near = _hand_area(regions, rb, run.area.shape)
        hand_near = bool((near & run.area).any())
        if not hand_near:
            run.reason = "no-near-hand"
        # 손이 닿은 채 물체를 옮기는 중: 기준 모습은 그대로 두고 비교 영역만 물체를 따라 옮긴다 (터치한 채 이동해도 계속 인식)
        if box is not None and hand_near:
            size = max(rb[2] - rb[0], rb[3] - rb[1])
            dx = (box[0] + box[2]) / 2 - (rb[0] + rb[2]) / 2
            dy = (box[1] + box[3]) / 2 - (rb[1] + rb[3]) / 2
            if abs(dx) > 0.15 * size or abs(dy) > 0.15 * size:   # 손가락에 가려 박스가 조금 흔들리는 것은 무시
                rb = run.box = (rb[0] + dx, rb[1] + dy, rb[2] + dx, rb[3] + dy)
        # 물체가 다른 자리로 옮겨졌나 (손이 없을 때만 판단; 손이 덮으면 추적 박스가 흔들리므로)
        if box is not None and not hand_near:
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            rcx, rcy = (rb[0] + rb[2]) / 2, (rb[1] + rb[3]) / 2
            size = max(rb[2] - rb[0], rb[3] - rb[1])
            if abs(cx - rcx) > 0.15 * size or abs(cy - rcy) > 0.15 * size:
                run.moved_since = run.moved_since if run.moved_since is not None else t
                if t - run.moved_since > 0.4:             # 새 자리에서 잠깐 머물면 다시 찍는다
                    self._capture(run, frame, box, mask)
                return False
            run.moved_since = None
        c = self._crop(frame, rb)
        if c is None:
            return False
        img, _ = c
        if img.shape[:2] != run.ref.shape[:2]:
            self._capture(run, frame, box or rb, mask)
            return False
        cur = _lab(img)
        d = cur - run.ref
        # Remove a global color/light shift; contact is a local change, not a new exposure.
        near = _hand_area(regions, rb, run.area.shape)
        quiet_area = ~near
        # Estimate exposure from pixels outside the hand so a broad palm contact is not subtracted away.
        if int(quiet_area.sum()) >= 12:
            d -= np.median(d[quiet_area], axis=0)
        else:
            # A palm may cover the entire crop. Remove brightness only; subtracting
            # its full colour shift would erase the contact itself.
            d[..., 0] -= np.median(d[..., 0][run.area])
        diff = np.sqrt(0.25 * d[..., 0] ** 2 + d[..., 1] ** 2 + d[..., 2] ** 2)   # 밝기는 반만 (그림자 완화)
        area = run.core
        n_area = max(1, int(area.sum()))
        thr = max(9.0, 2.0 * run.noise)
        changed = (diff > thr) & area
        changed = cv2.morphologyEx(changed.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
        frac = float(changed.sum()) / n_area
        run.change = frac
        skin = skin_mask(img)
        run.skin = float((skin & changed).sum()) / max(1, int(changed.sum())) if changed.any() else 0.0
        if not hand_near:
            # 손이 인식되지 않으면 닿음이 아니다. 다만 물체가 가려진 채로는 기준을 다시 찍지 않는다(손이 기준에 섞이지 않게)
            if frac < self.min_change * .5:
                self._capture(run, frame, box, mask)
            run.reason = "no-near-hand"
            return False
        if frac < self.min_change:
            run.reason = "no-front-occlusion"
            return False
        local = changed & near
        local_count = int(local.sum())
        # Broad frame changes outside the hand remain invalid; full palm coverage is allowed.
        if frac > .85 and local_count < int(changed.sum()) * .65:
            run.reason = "global-change"
            return False
        front = _foreground(cur, run.ref, run.ref_skin, run.ref_image, img, diff, area, near, thr) & changed
        front = cv2.morphologyEx(front.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
        run.foreground = float(front.sum()) / n_area
        enough_front = int(front.sum()) >= max(4, int(self.min_change * n_area * .5))
        # 손이 물체 위에 있고 물체 모습이 문턱 넘게 바뀌었으면, 앞쪽 손 판정이 약해도 바뀐 곳 대부분이 손 둘레이거나 살색이면 터치로 본다
        if not enough_front and run.skin >= .25:
            new_skin = changed & near & skin_mask(img) & ~run.ref_skin    # 원래 물체에 없던 살색이 손 둘레에 새로 나타남
            if int(new_skin.sum()) >= max(4, int(self.min_change * n_area * .5)):
                front, enough_front = new_skin, True
        if enough_front:
            if int(front.sum()) < int(.5 * self.min_change * n_area) and _surface_still_visible(cur, run.ref, front):
                run.reason = "surface-still-visible"
                return False
            run.contact = front
            yy, xx = np.nonzero(front)
            run.point = np.array([rb[0] + float(xx.mean()) / changed.shape[1] * (rb[2] - rb[0]),
                                  rb[1] + float(yy.mean()) / changed.shape[0] * (rb[3] - rb[1])], np.float32)
            run.reason = "hand-contact"
            return True
        run.reason = "no-foreground-hand"
        return False

    def state(self) -> dict[int, dict[str, Any]]:
        return {oid: {"on": r.on, "point": _round(r.point), "occluded": round(r.change, 3), "skin": round(r.skin, 2),
                      "foreground": round(r.foreground, 3), "reason": r.reason, "box": None if r.box is None else [round(v, 4) for v in r.box],
                      "min_change": round(self.min_change, 3)}
                for oid, r in self.runs.items()}
