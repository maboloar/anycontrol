"""물체 기억 보기: 놓쳤을 때 복귀(재획득·Tier 1 재고정)에 쓰는 기억을 사람이 볼 수 있는 그림으로 남긴다.

추적기가 실제로 쓰는 기억은 마스크·색 히스토그램·모델 임베딩이라 그대로는 볼 수 없다. 기억이 '기록되는 순간'의
작업 해상도 프레임에서 물체 부분만 작게 잘라 둔다 (프레임당 비용 없음: 기록 이벤트 때만 1ms 미만).

- registration: 등록 / 다시 선택 때 기억한 모습 (모양 기억 · 색 · Tier 1 조건 프레임 0)
- anchor:       Tier 1 이 '매우 확실 + 크기가 다름' 으로 추가한 앵커 프레임 (최대 3개, 오래된 것부터 교체)
- reacquired:   모양 기억 재획득으로 복구하며 Tier 1 메모리를 다시 고정한 프레임
"""
from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field

import cv2
import numpy as np

THUMB = 160            # 잘라 둔 그림의 긴 변 (px)
KEEP = {"registration": 1, "anchor": 3, "reacquired": 3}


@dataclass
class Snapshot:
    kind: str
    t: float
    image: np.ndarray          # BGR, 물체 박스 + 여백 (긴 변 THUMB 이하)
    mask: np.ndarray           # 같은 크기 bool
    info: dict = field(default_factory=dict)


def capture(frame_bgr: np.ndarray, mask: np.ndarray, kind: str, t: float, info: dict | None = None
            ) -> Snapshot | None:
    """frame·mask 는 같은 해상도. 물체 박스에 30% 여백을 두고 잘라 작게 줄인다."""
    if mask is None or frame_bgr is None or mask.shape != frame_bgr.shape[:2] or not mask.any():
        return None
    ys, xs = np.nonzero(mask)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    pad = int(0.3 * max(x1 - x0, y1 - y0)) + 4
    H, W = mask.shape
    x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
    img, m = frame_bgr[y0:y1, x0:x1], mask[y0:y1, x0:x1]
    s = min(1.0, THUMB / max(img.shape[:2]))
    if s < 1.0:
        size = (max(1, round(img.shape[1] * s)), max(1, round(img.shape[0] * s)))
        img = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
        m = cv2.resize(m.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST).astype(bool)
    return Snapshot(kind, float(t), img.copy(), m.copy(), dict(info or {}))


def remember(store: list[Snapshot], snap: Snapshot | None) -> None:
    """종류별 개수 제한을 지키며 추가한다 (registration 은 새로 오면 교체)."""
    if snap is None:
        return
    same = [s for s in store if s.kind == snap.kind]
    for old in same[: max(0, len(same) - KEEP.get(snap.kind, 3) + 1)]:
        store.remove(old)
    store.append(snap)


def _data_uri(img: np.ndarray, ext: str = ".jpg") -> str:
    ok, buf = cv2.imencode(ext, img, [cv2.IMWRITE_JPEG_QUALITY, 85] if ext == ".jpg" else [])
    if not ok:
        return ""
    mime = "image/jpeg" if ext == ".jpg" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(buf.tobytes()).decode()}"


def render_snapshot(s: Snapshot) -> str:
    """물체 바깥은 어둡게, 마스크 윤곽은 밝게 그린 그림."""
    vis = s.image.copy()
    out = ~s.mask
    vis[out] = (vis[out] * 0.35).astype(np.uint8)
    cnt, _ = cv2.findContours(s.mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(vis, cnt, -1, (80, 255, 120), 1)
    return _data_uri(vis)


def render_icon(s: Snapshot) -> str:
    """물체 패널 아이콘: 바깥만 살짝 어둡게 한 사진 (윤곽선 없음)."""
    vis = s.image.copy()
    out = ~s.mask
    vis[out] = (vis[out] * 0.55).astype(np.uint8)
    return _data_uri(vis)


def render_template(template: np.ndarray, size: int = 128) -> str:
    """정규화 캔버스의 모양 기억 (중심·면적·주축 정렬). 재획득은 이것과 후보의 정렬 IoU 를 본다."""
    img = cv2.resize(template.astype(np.uint8) * 255, (size, size), interpolation=cv2.INTER_NEAREST)
    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    img[img[..., 0] == 0] = (40, 40, 40)
    return _data_uri(img, ".png")


def palette(hist: np.ndarray, l_bins: int, a_bins: int, b_bins: int, top: int = 8) -> list[dict]:
    """색 기억(Lab 히스토그램)의 주요 색. 칸 중심 Lab → sRGB."""
    order = np.argsort(hist)[::-1][:top]
    out = []
    for i in order:
        w = float(hist[i])
        if w < 0.01:
            break
        li, rest = divmod(int(i), a_bins * b_bins)
        ai, bi = divmod(rest, b_bins)
        lab = np.uint8([[[(li + .5) * 256 / l_bins, (ai + .5) * 256 / a_bins, (bi + .5) * 256 / b_bins]]])
        b, g, r = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)[0, 0]
        out.append({"hex": f"#{int(r):02x}{int(g):02x}{int(b):02x}", "weight": round(w, 3)})
    return out


def describe(snaps: list[Snapshot], now: float) -> list[dict]:
    order = {"registration": 0, "anchor": 1, "reacquired": 2}
    def age(s: Snapshot) -> float:
        return round(max(0.0, now - s.t), 1) if math.isfinite(s.t) and math.isfinite(now) else 0.0

    return [{"kind": s.kind, "t": round(s.t, 3) if math.isfinite(s.t) else None, "age_s": age(s),
             "image": render_snapshot(s), "info": {k: (round(v, 3) if isinstance(v, float) and math.isfinite(v) else v)
                                                   for k, v in s.info.items()}}
            for s in sorted(snaps, key=lambda s: (order.get(s.kind, 9), s.t))]
