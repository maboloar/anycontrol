"""정답을 아는 합성 시퀀스 생성기.

특정 물체에 과적합하지 않도록 "물체 유형 × 조건" 행렬로 만든다.
- 물체 유형: 무늬 평면, 무늬 없는 어두운 물체, 저대비 밝은 물체, 가는 펜, 반투명
- 조건: 손 쥐기, 당기기(깊이), 회전(면내·면외), 빠른 휘두르기(흐림), 완전 가림, 화면 이탈,
        쌍둥이 방해물, 조명 변화, 광택 반사, 배경 움직임
정답: 전체(amodal) 포즈, 보이는 마스크·박스, 가시 비율, 방해물 박스.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

import cv2
import numpy as np

OBJECT_KINDS = ("textured", "dark", "light", "pen", "glass")
CONDITIONS = ("grasp", "pull", "rotate", "fast", "full_occlusion", "exit", "twin", "lighting",
              "reflection", "clutter")


# ------------------------------------------------------------------ sprites
@dataclass
class Sprite:
    rgb: np.ndarray    # (h, w, 3) float32 0..1
    alpha: np.ndarray  # (h, w) float32 0..1

    @property
    def size(self) -> tuple[int, int]:
        return self.rgb.shape[1], self.rgb.shape[0]


def _rounded_rect_alpha(w: int, h: int, r: int) -> np.ndarray:
    a = np.zeros((h, w), np.uint8)
    r = max(1, min(r, w // 2 - 1, h // 2 - 1))
    cv2.rectangle(a, (r, 0), (w - r - 1, h - 1), 255, -1)
    cv2.rectangle(a, (0, r), (w - 1, h - r - 1), 255, -1)
    for cx, cy in ((r, r), (w - r - 1, r), (r, h - r - 1), (w - r - 1, h - r - 1)):
        cv2.circle(a, (cx, cy), r, 255, -1, cv2.LINE_AA)
    return cv2.GaussianBlur(a, (3, 3), 0).astype(np.float32) / 255.0


def make_sprite(kind: str, rng: np.random.Generator, base: int = 200) -> Sprite:
    """base = 등록 시 긴 변 길이(px, 1280 폭 기준)."""
    if kind == "pen":
        w, h = int(base * 1.1), max(8, int(base * 0.07))
        col = rng.uniform(0.05, 0.9, 3)
        rgb = np.ones((h, w, 3), np.float32) * col
        shade = np.linspace(0.75, 1.15, h, dtype=np.float32)[:, None, None]
        rgb = np.clip(rgb * shade, 0, 1)
        return Sprite(rgb, _rounded_rect_alpha(w, h, h // 2))

    w = base
    h = int(base * rng.uniform(0.45, 0.75))
    alpha = _rounded_rect_alpha(w, h, int(h * 0.12))
    yy = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    if kind == "textured":
        rgb = rng.uniform(0.2, 0.9, 3).astype(np.float32) * np.ones((h, w, 3), np.float32)
        img = (rgb * 255).astype(np.uint8)
        for _ in range(int(rng.integers(12, 25))):
            c = tuple(int(v) for v in rng.integers(0, 255, 3))
            p = (int(rng.integers(0, w)), int(rng.integers(0, h)))
            if rng.random() < 0.5:
                cv2.circle(img, p, int(rng.integers(4, h // 3)), c, -1, cv2.LINE_AA)
            else:
                q = (int(rng.integers(0, w)), int(rng.integers(0, h)))
                cv2.line(img, p, q, c, int(rng.integers(2, 8)), cv2.LINE_AA)
        cv2.putText(img, "".join(rng.choice(list("ABCDEFGHKMNPRSTXYZ"), 3)), (int(w * 0.1), int(h * 0.7)),
                    cv2.FONT_HERSHEY_DUPLEX, h / 70, (255, 255, 255), max(2, h // 30), cv2.LINE_AA)
        rgb = img.astype(np.float32) / 255.0
    elif kind == "dark":
        # 무늬 없는 어두운 물체: 위쪽 면만 약간 밝고, 옆면에 가는 밝은 띠 하나(흔한 형태)
        base_c = rng.uniform(0.04, 0.14)
        rgb = np.ones((h, w, 3), np.float32) * base_c * (1.0 + 0.6 * (1 - yy))[..., None]
        if rng.random() < 0.7:
            y0 = int(h * rng.uniform(0.45, 0.7))
            rgb[y0 : y0 + max(2, h // 18), int(w * 0.08) : int(w * 0.9)] = rng.uniform(0.6, 0.9)
    elif kind == "light":
        # 밝은 책상 위의 밝은 물체 (저대비)
        c = rng.uniform(0.72, 0.85)
        rgb = np.ones((h, w, 3), np.float32) * c * np.array([1.0, 0.98, 0.95], np.float32)
        rgb = rgb * (0.95 + 0.08 * (1 - yy))[..., None]
    elif kind == "glass":
        rgb = np.ones((h, w, 3), np.float32) * np.array([0.8, 0.9, 0.95], np.float32)
        edge = cv2.Canny((alpha * 255).astype(np.uint8), 50, 150)
        edge = cv2.dilate(edge, np.ones((3, 3), np.uint8)).astype(np.float32) / 255
        rgb = rgb * (1 - edge[..., None]) + 0.98 * edge[..., None]
        alpha = alpha * (0.45 + 0.5 * edge)  # 반투명 몸통 + 진한 테두리
    else:
        raise ValueError(kind)
    return Sprite(np.clip(rgb, 0, 1).astype(np.float32), alpha.astype(np.float32))


# ------------------------------------------------------------------ scene
def make_background(w: int, h: int, rng: np.random.Generator) -> np.ndarray:
    horizon = int(h * rng.uniform(0.3, 0.45))
    bg = np.zeros((h, w, 3), np.float32)
    wall = rng.uniform(0.3, 0.7, 3).astype(np.float32)
    bg[:horizon] = wall
    img = (bg * 255).astype(np.uint8)
    for _ in range(int(rng.integers(15, 40))):  # 선반·물건 같은 배경 잡동사니
        x, y = int(rng.integers(0, w)), int(rng.integers(0, horizon))
        cw, ch = int(rng.integers(10, w // 8)), int(rng.integers(8, horizon // 2 + 9))
        c = tuple(int(v) for v in rng.integers(20, 240, 3))
        cv2.rectangle(img, (x, y), (x + cw, y + ch), c, -1)
    bg = img.astype(np.float32) / 255.0
    # 책상: 원근 그라디언트 + 얼룩
    table = rng.uniform(0.55, 0.85, 3).astype(np.float32) * np.array([1.0, 0.93, 0.85], np.float32)
    ramp = np.linspace(0.85, 1.1, h - horizon, dtype=np.float32)[:, None, None]
    bg[horizon:] = table * ramp
    noise = cv2.GaussianBlur(rng.normal(0, 1, (h, w)).astype(np.float32), (0, 0), 12)
    bg[horizon:] += 0.08 * noise[horizon:, :, None]
    return np.clip(bg, 0, 1), horizon


def _warp_sprite(sp: Sprite, cx: float, cy: float, s: float, ang: float, aspect: float,
                 size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """스프라이트 → 프레임 affine. aspect<1 은 세로 압축(면외 기울임 근사)."""
    sw, sh = sp.size
    a = np.deg2rad(ang)
    R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]], np.float64)
    S = np.diag([s, s * aspect])
    A = R @ S
    t = np.array([cx, cy]) - A @ np.array([sw / 2, sh / 2])
    M = np.hstack([A, t[:, None]])
    rgb = cv2.warpAffine(sp.rgb, M, size, flags=cv2.INTER_LINEAR, borderValue=0)
    al = cv2.warpAffine(sp.alpha, M, size, flags=cv2.INTER_LINEAR, borderValue=0)
    return rgb, al, M


def _hand_mask(size: tuple[int, int], palm: tuple[float, float], scale: float, ang: float,
               spread: float, rng_phase: float) -> np.ndarray:
    """손 모양 가림: 손바닥 타원 + 손가락 4개 캡슐 + 엄지. 위에서 아래로 덮는 자세."""
    w, h = size
    m = np.zeros((h, w), np.uint8)
    px, py = palm
    a = np.deg2rad(ang)
    rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])

    def P(dx: float, dy: float) -> tuple[int, int]:
        v = rot @ np.array([dx, dy]) * scale
        return int(px + v[0]), int(py + v[1])

    cv2.ellipse(m, P(0, 0), (int(70 * scale), int(55 * scale)), ang, 0, 360, 255, -1, cv2.LINE_AA)
    cv2.line(m, P(40, -30), P(160, -110), 255, int(70 * scale), cv2.LINE_AA)  # 팔목·팔
    for i, off in enumerate((-45, -15, 15, 45)):
        ln = (95 + 15 * np.sin(rng_phase + i)) * (1.0 if i in (1, 2) else 0.85)
        tip = (off * (1 + spread) - 10, ln)
        cv2.line(m, P(off * 0.8, 20), P(*tip), 255, max(4, int(22 * scale)), cv2.LINE_AA)
    cv2.line(m, P(-55, -5), P(-110, 45), 255, max(4, int(26 * scale)), cv2.LINE_AA)  # 엄지
    return m.astype(np.float32) / 255.0


SKIN = np.array([0.55, 0.65, 0.85], np.float32)  # BGR


@dataclass
class FrameGT:
    idx: int
    t: float
    target: dict[str, Any]              # amodal pose, visible box, visible_frac, in_view
    distractors: list[dict[str, Any]] = field(default_factory=list)
    visible_mask: np.ndarray | None = None
    hand_frac: float = 0.0              # 물체 중 손에 가린 비율
    hand_mask: np.ndarray | None = None  # 손 영역 (bool). 손 인식 가림 처리의 '완벽한 손 검출' 조건 평가용


@dataclass
class SynthSpec:
    name: str
    obj: str
    conditions: tuple[str, ...]
    seed: int
    frames: int = 150
    fps: float = 30.0
    size: tuple[int, int] = (640, 360)


class SynthSequence:
    """프레임과 정답을 차례로 만든다. 같은 seed 면 항상 같은 영상."""

    def __init__(self, spec: SynthSpec) -> None:
        self.spec = spec
        self.name = spec.name
        self.fps = spec.fps
        self.rng = np.random.default_rng(spec.seed)
        w, h = spec.size
        self.size = (w, h)
        k = w / 1280
        self.bg, self.horizon = make_background(w, h, self.rng)
        self.sprite = make_sprite(spec.obj, self.rng, int(200 * k * self.rng.uniform(0.8, 1.2)))
        self.twin = self.sprite if "twin" in spec.conditions else None
        self._plan = self._make_plan()
        self.init_box = self._visible_box_at(0)

    # -- 동작 계획 ----------------------------------------------------------
    def _make_plan(self) -> dict[str, np.ndarray]:
        n, fps, rng, c = self.spec.frames, self.fps, self.rng, self.spec.conditions
        w, h = self.size
        t = np.arange(n) / fps
        base_y = self.horizon + (h - self.horizon) * rng.uniform(0.35, 0.55)
        cx = w * 0.5 + w * 0.18 * np.sin(2 * np.pi * rng.uniform(0.08, 0.2) * t + rng.uniform(0, 6))
        cy = base_y + h * 0.04 * np.sin(2 * np.pi * rng.uniform(0.1, 0.25) * t + rng.uniform(0, 6))
        scale = np.ones(n)
        ang = 4 * np.sin(2 * np.pi * 0.15 * t)
        aspect = np.ones(n)
        occ = np.zeros(n)         # 완전 가림 여부 (0/1)
        light = np.ones(n)

        def window(a: float, b: float) -> np.ndarray:
            return ((t >= a * t[-1]) & (t <= b * t[-1])).astype(float)

        def smooth_step(a: float, b: float) -> np.ndarray:
            x = np.clip((t - a * t[-1]) / max((b - a) * t[-1], 1e-6), 0, 1)
            return x * x * (3 - 2 * x)

        if "pull" in c:  # 카메라 쪽으로 당겼다 밀기: 크기 최대 약 2.8배, 아래로 이동
            k = smooth_step(0.2, 0.45) - smooth_step(0.6, 0.85)
            scale = 1 + rng.uniform(1.2, 1.8) * k
            cy = cy + (h * 0.18) * k
        if "rotate" in c:
            ang = ang + rng.choice([-1, 1]) * rng.uniform(35, 70) * (smooth_step(0.2, 0.5) - smooth_step(0.6, 0.9))
            aspect = 1 - rng.uniform(0.3, 0.5) * (smooth_step(0.3, 0.5) - smooth_step(0.65, 0.85))
        if "fast" in c:  # 짧은 빠른 휘두르기 2회
            for a in (0.3, 0.65):
                k = smooth_step(a, a + 0.06) - smooth_step(a + 0.08, a + 0.14)
                cx = cx + rng.choice([-1, 1]) * w * 0.3 * k
        if "exit" in c:
            k = smooth_step(0.3, 0.42) - smooth_step(0.6, 0.72)
            cx = cx + np.sign(rng.uniform(-1, 1)) * w * 0.75 * k
        if "full_occlusion" in c:
            occ = window(0.4, 0.4 + rng.uniform(0.12, 0.25))
        if "lighting" in c:
            light = 1 + rng.uniform(-0.45, 0.35) * (smooth_step(0.25, 0.5) - 0.5 * smooth_step(0.7, 0.9))
        plan = dict(t=t, cx=cx, cy=cy, scale=scale, ang=ang, aspect=aspect, occ=occ, light=light)
        if "grasp" in c or "full_occlusion" in c:
            plan["grasp"] = window(0.1, 0.9) if "grasp" in c else occ
            plan["cover"] = rng.uniform(0.45, 0.85) * np.ones(n)  # 손이 덮는 정도 (물체 높이 대비)
        if self.twin is not None:  # 같은 물체가 반대쪽에서 가로질러 온다
            tx = w * 0.5 - (cx - w * 0.5) * 1.1 + rng.uniform(-20, 20)
            plan["twin"] = np.stack([tx, cy + rng.uniform(-8, 8)], 1)
        if "clutter" in c:
            plan["movers"] = rng.uniform(0, 1, (3, 4))
        return plan

    # -- 렌더링 -------------------------------------------------------------
    def _pose(self, i: int) -> dict[str, float]:
        p = self._plan
        return {k: float(p[k][i]) for k in ("cx", "cy", "scale", "ang", "aspect")}

    def _visible_box_at(self, i: int) -> tuple[float, float, float, float] | None:
        _, gt = self.render(i)
        return gt.target["visible_box"]

    def render(self, i: int) -> tuple[np.ndarray, FrameGT]:
        p, c = self._plan, self.spec.conditions
        w, h = self.size
        rng = np.random.default_rng(self.spec.seed * 100003 + i)  # 프레임별 잡음 (재현 가능)
        img = self.bg.copy()
        t = float(p["t"][i])

        if "movers" in p:  # 배경에서 움직이는 사람·물건
            for j, (a, b, cc, d) in enumerate(p["movers"]):
                x = int((a * w + t * (40 + 60 * b) * (1 if j % 2 else -1)) % w)
                cv2.ellipse(img, (x, int(self.horizon * (0.4 + 0.4 * d))),
                            (int(w * 0.05), int(self.horizon * 0.45)), 0, 0, 360,
                            (0.3 + 0.5 * cc, 0.4, 0.5 * b + 0.2), -1)

        pose = self._pose(i)
        s0 = pose["scale"]
        draws: list[tuple[np.ndarray, np.ndarray]] = []
        distractors = []
        if "twin" in p:
            tx, ty = p["twin"][i]
            rgb_t, al_t, _ = _warp_sprite(self.twin, tx, ty, 1.0, -pose["ang"], 1.0, (w, h))
            draws.append((rgb_t, al_t))
            distractors.append({"box": _box(al_t > 0.5)})

        # 빠른 동작은 부분 프레임 평균으로 모션 블러
        if i > 0 and "fast" in c:
            v = np.hypot(p["cx"][i] - p["cx"][i - 1], p["cy"][i] - p["cy"][i - 1])
            sub = int(np.clip(v / 6, 1, 7))
        else:
            sub = 1
        acc_rgb = np.zeros((h, w, 3), np.float32)
        acc_al = np.zeros((h, w), np.float32)
        for k in range(sub):
            f = (k + 0.5) / sub if sub > 1 else 1.0
            q = {kk: float(p[kk][i - 1] + (p[kk][i] - p[kk][i - 1]) * f) if i > 0 else pose[kk] for kk in pose}
            r, a, _ = _warp_sprite(self.sprite, q["cx"], q["cy"], q["scale"], q["ang"], q["aspect"], (w, h))
            acc_rgb += r * a[..., None]
            acc_al += a
        al = acc_al / sub
        rgb = np.divide(acc_rgb, np.maximum(acc_al, 1e-6)[..., None])
        amodal = al > 0.5

        if "reflection" in c:  # 광택 책상에 비친 상 (접촉선 아래 상하 반전, 흐리게)
            ys = np.nonzero(amodal.any(1))[0]
            if ys.size:
                y_bot = ys.max()
                ref_rgb = np.zeros_like(rgb)
                ref_al = np.zeros_like(al)
                span = min(y_bot, h - 1 - y_bot)
                if span > 2:
                    ref_rgb[y_bot + 1 : y_bot + 1 + span] = rgb[y_bot - span : y_bot][::-1]
                    ref_al[y_bot + 1 : y_bot + 1 + span] = al[y_bot - span : y_bot][::-1]
                    ref_al = cv2.GaussianBlur(ref_al, (0, 0), 3) * 0.35
                    draws.insert(0, (cv2.GaussianBlur(ref_rgb, (0, 0), 3), ref_al))

        for r, a in draws:
            img = img * (1 - a[..., None]) + r * a[..., None]
        img = img * (1 - al[..., None]) + rgb * al[..., None]

        # 손
        hand = np.zeros((h, w), np.float32)
        if "grasp" in p and p["grasp"][i] > 0:
            ys, xs = np.nonzero(amodal)
            if ys.size:
                oh = ys.max() - ys.min()
                cover = 1.0 if p["occ"][i] > 0 else float(p["cover"][i])
                palm = (float(xs.mean()) + 10 * np.sin(t * 3), ys.min() - 55 * s0 * (w / 1280) * 1.2
                        + cover * oh)
                hs = (w / 1280) * max(0.8, s0) * (1.8 if p["occ"][i] > 0 else 1.2)
                hand = _hand_mask((w, h), palm, hs, -10 + 8 * np.sin(t), 0.2, t)
                if p["occ"][i] > 0:  # 완전 가림: 물체 전체를 덮는 손 + 팔
                    hand = np.maximum(hand, cv2.dilate(amodal.astype(np.float32),
                                                       np.ones((25, 25), np.uint8)))
        if hand.any():
            skin = SKIN * (0.85 + 0.25 * cv2.GaussianBlur(rng.random((h, w)).astype(np.float32), (0, 0), 6))[..., None]
            img = img * (1 - hand[..., None]) + skin * hand[..., None]

        img = img * float(p["light"][i])
        img = img + rng.normal(0, 0.012, img.shape).astype(np.float32)  # 센서 잡음
        frame = (np.clip(img, 0, 1) * 255).astype(np.uint8)

        visible = amodal & (hand < 0.5)
        area_amodal = amodal.sum()
        # 화면 밖으로 나간 부분까지 고려한 가시 비율: 이론 면적 대비
        sw, sh = self.sprite.size
        theo = max(1.0, float((self.sprite.alpha > 0.5).sum()) * pose["scale"] ** 2 * pose["aspect"])
        gt = FrameGT(
            idx=i, t=t,
            target={
                "cx": pose["cx"], "cy": pose["cy"], "scale": pose["scale"], "angle": pose["ang"],
                "aspect": pose["aspect"],
                "visible_box": _box(visible), "amodal_box": _box(amodal),
                "visible_frac": float(visible.sum() / theo),
                "in_view": bool(area_amodal > 0.3 * theo),
            },
            distractors=distractors,
            visible_mask=visible,
            hand_frac=float((amodal & (hand >= 0.5)).sum() / max(area_amodal, 1)),
            hand_mask=hand >= 0.5,
        )
        return frame, gt

    def __len__(self) -> int:
        return self.spec.frames

    def __iter__(self) -> Iterator[tuple[np.ndarray, FrameGT]]:
        for i in range(self.spec.frames):
            yield self.render(i)


def _box(m: np.ndarray) -> tuple[float, float, float, float] | None:
    ys, xs = np.nonzero(m)
    if xs.size < 4:
        return None
    return float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)


# ------------------------------------------------------------------ 세트
def build_suite(split: str, frames: int = 150, size: tuple[int, int] = (640, 360),
                objects: tuple[str, ...] = OBJECT_KINDS, conditions: tuple[str, ...] = CONDITIONS
                ) -> list[SynthSpec]:
    """split='tune' 은 seed 0.., 'eval' 은 seed 100000.. (튜닝에 쓰지 않는 세트).

    각 시퀀스 = 물체 유형 × 주 조건 1개 + 가벼운 부 조건 0~1개.
    """
    base = 0 if split == "tune" else 100000
    specs = []
    for oi, obj in enumerate(objects):
        for ci, cond in enumerate(conditions):
            seed = base + oi * 1000 + ci
            rng = np.random.default_rng(seed)
            extra = ()
            if rng.random() < 0.5:
                pool = [x for x in ("lighting", "clutter", "reflection", "rotate") if x != cond]
                extra = (str(rng.choice(pool)),)
            specs.append(SynthSpec(f"{split}/{obj}-{cond}", obj, (cond, *extra), seed, frames, 30.0, size))
    return specs
