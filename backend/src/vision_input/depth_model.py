"""깊이 모델 비교 (개발자 모드 전용 실험). 접촉 판정에는 쓰지 않는다.

Depth Anything V2 Small (Apache-2.0, Apple 이 변환한 Core ML 판, F16 약 50MB)을 pyobjc CoreML 로 돌려 책상 영역의
상대 깊이를 얻고, 거기에 평면을 맞춰 펜 접촉으로 학습한 바닥 평면과 비교한다.

왜 접촉 판정에 쓰지 않나
- 단안 깊이 모델의 출력은 프레임마다 스케일·이동이 다른 '상대' 역깊이다. 펜 굵기(∝ 역깊이)와 직접 견줄 수 없다.
- 광택 있는 책상에서 잡음이 크고, 첫 실행에 가중치를 내려받아야 한다 (로컬 전용·오프라인이라는 설계와 충돌).
그래도 '평면이다'라는 사실만은 스케일에 무관하다: 책상 영역의 역깊이는 화면 좌표의 1차식이다.
이 1차식의 기울기(앞뒤 그라데이션과 좌우 롤)를 터치로 학습한 평면의 기울기와 비교하면 학습이 맞는지 검증할 수 있다.

가중치(Apache-2.0, 50MB)는 프로그램에 같이 들어 있다: models/DepthAnythingV2SmallF16.mlpackage (SHA-256 고정).
번들에 없을 때만 대비책으로 내려받기를 사용자가 누를 때 받는다 (huggingface.co → ~/Library/Caches/AnyControl/depth,
환경변수 ANYCONTROL_DEPTH_DIR 로 바꿀 수 있다). 어느 쪽도 없으면 이 기능만 꺼지고 터치로 배운 기울기·물체 크기를 쓴다.
"""
from __future__ import annotations

import hashlib
import os
import ssl
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np

REPO = "apple/coreml-depth-anything-v2-small"
VARIANT = "DepthAnythingV2SmallF16.mlpackage"
FILES = (f"{VARIANT}/Manifest.json", f"{VARIANT}/Data/com.apple.CoreML/model.mlmodel",
         f"{VARIANT}/Data/com.apple.CoreML/weights/weight.bin")
WEIGHT_SHA256 = "fa60d9b6a155734f59029ebb882fd54e549bfaee3539c1a9cbd2cbbab64a0fed"
APPROX_MB = 50
INPUT_SIZE = (518, 392)       # (폭, 높이) 모델 입력


def bundled_dir() -> Path:
    """프로그램에 같이 들어 있는 가중치 위치 (models/). 번들 설치에서는 VI_MODELS_DIR 이 가리킨다."""
    return Path(os.environ.get("VI_MODELS_DIR") or Path(__file__).resolve().parents[3] / "models")


def user_cache_dir() -> Path:
    """내려받기(번들 가중치가 없을 때의 대비책)가 저장하는 위치. 환경변수 ANYCONTROL_DEPTH_DIR 로 바꾼다."""
    return Path(os.environ.get("ANYCONTROL_DEPTH_DIR") or Path.home() / "Library" / "Caches" / "AnyControl" / "depth")


def _complete(d: Path) -> bool:
    return all((d / f).exists() for f in FILES)


def cache_dir() -> Path:
    """실제로 읽을 가중치 폴더. ANYCONTROL_DEPTH_DIR 가 있으면 그것, 아니면 번들 가중치, 없으면 사용자 캐시."""
    if os.environ.get("ANYCONTROL_DEPTH_DIR"):
        return user_cache_dir()
    b = bundled_dir()
    return b if _complete(b) else user_cache_dir()


def is_bundled() -> bool:
    return not os.environ.get("ANYCONTROL_DEPTH_DIR") and _complete(bundled_dir())


def verify_weights(d: Path | None = None) -> bool:
    """가중치 파일의 SHA-256 이 고정값과 같은가 (번들 무결성 검사용. 50MB 를 읽으므로 시작 때 한 번만)."""
    w = (d or cache_dir()) / FILES[-1]
    return w.is_file() and hashlib.sha256(w.read_bytes()).hexdigest() == WEIGHT_SHA256


def is_available() -> bool:
    return _complete(cache_dir())


# ---------------------------------------------------------------- 내려받기 (사용자가 눌렀을 때만)
class Downloader:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.error: str | None = None
        self.done_bytes = 0

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self) -> bool:
        with self.lock:
            if self.running or is_available():
                return False
            self.error, self.done_bytes = None, 0
            self.thread = threading.Thread(target=self._run, name="depth-download", daemon=True)
            self.thread.start()
            return True

    def _run(self) -> None:
        import urllib.request

        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = ssl.create_default_context()
        root = user_cache_dir()
        try:
            for f in FILES:
                dst = root / f
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_suffix(dst.suffix + ".part")
                with urllib.request.urlopen(f"https://huggingface.co/{REPO}/resolve/main/{f}", timeout=60, context=ctx) as r, \
                        open(tmp, "wb") as o:
                    while chunk := r.read(1 << 20):
                        o.write(chunk)
                        self.done_bytes += len(chunk)
                if f.endswith("weight.bin") and hashlib.sha256(tmp.read_bytes()).hexdigest() != WEIGHT_SHA256:
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError("내려받은 가중치의 SHA-256 이 맞지 않습니다.")
                tmp.replace(dst)
        except Exception as exc:  # 네트워크·디스크·검증 실패: 받다 만 파일은 지운다
            self.error = str(exc)
            for f in FILES:
                (root / f).with_suffix((root / f).suffix + ".part").unlink(missing_ok=True)

    def state(self) -> dict:
        return {"available": is_available(), "downloading": self.running, "error": self.error,
                "downloaded_mb": round(self.done_bytes / 1e6, 1), "size_mb": APPROX_MB, "license": "Apache-2.0",
                "source": f"huggingface.co/{REPO}", "path": str(cache_dir()), "bundled": is_bundled()}


# ---------------------------------------------------------------- 추론
class DepthModel:
    """Core ML 모델 하나. 처음 predict 할 때 컴파일·적재한다 (스레드 안전)."""

    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()
        self.last_ms: float | None = None

    def _load(self):  # type: ignore[no-untyped-def]
        import CoreML
        import Foundation

        url = Foundation.NSURL.fileURLWithPath_(str(cache_dir() / VARIANT))
        compiled = CoreML.MLModel.compileModelAtURL_error_(url, None)[0]
        cfg = CoreML.MLModelConfiguration.alloc().init()
        cfg.setComputeUnits_(CoreML.MLComputeUnitsAll)
        model = CoreML.MLModel.modelWithContentsOfURL_configuration_error_(compiled, cfg, None)[0]
        if model is None:
            raise RuntimeError("깊이 모델을 불러오지 못했습니다.")
        return model

    def predict(self, bgr: np.ndarray) -> np.ndarray:
        """BGR 프레임 → (392, 518) float32, 0..1 의 상대 역깊이 (클수록 가깝다)."""
        import objc
        with objc.autorelease_pool():   # Core ML 객체를 호출마다 바로 해제 (장시간 실행 시 메모리 누적 방지)
            return self._predict(bgr)

    def _predict(self, bgr: np.ndarray) -> np.ndarray:
        import CoreML
        import Foundation
        try:
            import CoreVideo as CV
        except ImportError:  # pyobjc 구성에 따라 Quartz 에 들어 있다
            import Quartz as CV

        with self._lock:
            if self._model is None:
                self._model = self._load()
            t0 = time.perf_counter()
            fd, path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            try:
                cv2.imwrite(path, bgr)
                desc = self._model.modelDescription().inputDescriptionsByName()["image"]
                fv = CoreML.MLFeatureValue.featureValueWithImageAtURL_constraint_options_error_(
                    Foundation.NSURL.fileURLWithPath_(path), desc.imageConstraint(), None, None)[0]
            finally:
                os.unlink(path)
            prov = CoreML.MLDictionaryFeatureProvider.alloc().initWithDictionary_error_({"image": fv}, None)[0]
            out = self._model.predictionFromFeatures_error_(prov, None)[0]
            pb = out.featureValueForName_("depth").imageBufferValue()
            CV.CVPixelBufferLockBaseAddress(pb, 1)
            try:
                w, h, bpr = CV.CVPixelBufferGetWidth(pb), CV.CVPixelBufferGetHeight(pb), CV.CVPixelBufferGetBytesPerRow(pb)
                buf = CV.CVPixelBufferGetBaseAddress(pb).as_buffer(bpr * h)
                arr = np.frombuffer(buf, dtype=np.float16).reshape(h, bpr // 2)[:, :w].astype(np.float32).copy()
            finally:
                CV.CVPixelBufferUnlockBaseAddress(pb, 1)
            self.last_ms = (time.perf_counter() - t0) * 1000
            return arr


# ---------------------------------------------------------------- 평면 비교 (모델과 무관한 순수 계산)
def fit_depth_plane(depth: np.ndarray, floor: np.ndarray, iters: int = 200, seed: int = 0) -> dict | None:
    """바닥 영역의 상대 역깊이에 평면 D = A·x + B·y + C 를 맞춘다 (x, y 는 0..1 로 정규화한 위치). RANSAC + 최소제곱.

    반환: 계수, 내점 비율, 평면에서의 RMS 잔차(깊이 범위 대비). 점이 너무 적으면 None."""
    h, w = depth.shape
    ys, xs = np.nonzero(floor)
    if xs.size < 200:
        return None
    X = np.stack([(xs + 0.5) / w, (ys + 0.5) / h, np.ones(xs.size)], 1)
    z = depth[ys, xs].astype(np.float64)
    rng = np.random.default_rng(seed)
    span = float(np.ptp(z)) or 1.0
    tol = 0.03 * span
    best, best_n = None, 0
    for _ in range(iters):
        idx = rng.choice(xs.size, 3, replace=False)
        try:
            p = np.linalg.solve(X[idx], z[idx])
        except np.linalg.LinAlgError:
            continue
        n = int((np.abs(X @ p - z) < tol).sum())
        if n > best_n:
            best_n, best = n, p
    if best is None:
        return None
    inl = np.abs(X @ best - z) < 2 * tol
    p = np.linalg.lstsq(X[inl], z[inl], rcond=None)[0]
    res = X[inl] @ p - z[inl]
    return {"A": float(p[0]), "B": float(p[1]), "C": float(p[2]), "inlier_frac": float(inl.mean()),
            "rms_rel": float(np.sqrt(np.mean(res ** 2)) / span), "span": span}


def compare_planes(depth_plane: dict, w_plane: np.ndarray, valid: np.ndarray, frame_wh: tuple[int, int]) -> dict:
    """깊이 모델 평면과 터치로 배운 바닥 평면(접촉 굵기 맵 w_plane)을 같은 영역에서 비교한다. 스케일·이동에 무관한 지표만.

    corr:       두 평면 값의 상관 (1 = 같은 그라데이션)
    angle_deg:  두 평면의 기울기 방향 차이 (화면 위·아래 그라데이션이 어긋난 정도, 롤 포함)
    roll_*:     등고선이 수평에서 기운 각도 (카메라 롤) 각각."""
    h, w = w_plane.shape
    gy, gx = np.mgrid[0:h, 0:w].astype(np.float64)
    D = depth_plane["A"] * (gx + 0.5) / w + depth_plane["B"] * (gy + 0.5) / h + depth_plane["C"]
    a, b = D[valid], w_plane[valid]
    corr = float(np.corrcoef(a, b)[0, 1]) if a.size > 10 and a.std() > 0 and b.std() > 0 else float("nan")
    # 화면 px 단위 기울기: 정규화 좌표의 계수를 W, H 로 나눈다
    W, H = frame_wh
    g_depth = np.array([depth_plane["A"] / W, depth_plane["B"] / H])
    by, bx = np.polyfit(np.arange(h)[:, None].repeat(w, 1)[valid] * (H / h), b, 1)[0], \
        np.polyfit(np.arange(w)[None, :].repeat(h, 0)[valid] * (W / w), b, 1)[0]
    g_touch = np.array([bx, by])
    def ang(g):   # 수직 그라데이션(0,1)에서 기운 각도 = 카메라 롤
        return float(np.degrees(np.arctan2(g[0], g[1])))
    cos = float(g_depth @ g_touch / (np.linalg.norm(g_depth) * np.linalg.norm(g_touch) + 1e-12))
    return {"corr": round(corr, 3), "angle_deg": round(float(np.degrees(np.arccos(np.clip(cos, -1, 1)))), 2),
            "roll_depth_deg": round(ang(g_depth), 2), "roll_touch_deg": round(ang(g_touch), 2)}


# ---------------------------------------------------------------- 백그라운드 추론 (프레임 처리 스레드를 막지 않는다)
class DepthService:
    """깊이 모델을 별도 스레드에서 돌린다. submit() 은 기다리지 않고, 이미 계산 중이면 새 요청을 버린다.
    펜 바닥 기울기와 물체 마우스 깊이가 같이 쓴다. 가중치가 없으면 available 이 False 이고 submit() 은 아무것도 안 한다."""

    def __init__(self, model: "DepthModel | None" = None) -> None:
        self.model = model or DepthModel()
        self._lock = threading.Lock()
        self._busy = False
        self.error: str | None = None
        self.runs = 0
        self.latest: tuple[np.ndarray, float] | None = None   # 가장 최근 깊이 맵과 시각(time.monotonic)

    @property
    def available(self) -> bool:
        return is_available()

    @property
    def busy(self) -> bool:
        return self._busy

    def submit(self, bgr: np.ndarray, job) -> bool:  # type: ignore[no-untyped-def]
        """job(depth: (392,518) float32) 를 백그라운드에서 부른다. 받아들였으면 True."""
        with self._lock:
            if self._busy or not self.available:
                return False
            self._busy = True
        bgr = bgr.copy()   # 캡처 버퍼가 재사용돼도 추론 중에 바뀌지 않게
        threading.Thread(target=self._run, args=(bgr, job), name="depth-infer", daemon=True).start()
        return True

    def _run(self, bgr, job) -> None:  # type: ignore[no-untyped-def]
        try:
            depth = self.model.predict(bgr)
            self.latest = (depth, time.monotonic())
            job(depth)
            self.error = None
            self.runs += 1
        except Exception as exc:  # Core ML 사용 불가·추론 오류: 기능만 잠시 쉬고 오류를 보여 준다
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            self._busy = False


def plane_roll_deg(fit: dict, frame_wh: tuple[int, int]) -> float:
    """깊이 평면(정규화 좌표 계수 A, B)의 카메라 롤(도): 등고선이 수평에서 기운 각도. compare_planes 의 roll_depth 와 같다."""
    W, H = frame_wh
    return float(np.degrees(np.arctan2(fit["A"] / W, fit["B"] / H)))


class DepthRoll:
    """깊이 모델로 잰 카메라 롤의 이동 중앙값. 몇 번 재서 서로 맞으면 바닥 평면의 좌우 기울기 a 를 고정하는 데 쓴다.

    a = -W·tan(roll): d = k·w + a·x − c 에서 접촉 굵기 w 의 등고선 기울기가 tan(roll) 이기 때문 (bench/pen/depth_prior.py)."""
    MIN_N = 3          # 이만큼 재서
    MAX_SPREAD = 2.5   # 서로 이 각도(도) 안이면 믿는다
    MAX_ABS = 20.0     # 이보다 기울었으면 평면이 아닌 걸 맞춘 것으로 본다
    MIN_INLIER = 0.55

    def __init__(self, interval: float = 2.0) -> None:
        self.interval = interval
        self.vals: list[float] = []
        self.last_t = -1e9
        self.rejected = 0

    def reset(self) -> None:
        self.vals.clear()
        self.last_t = -1e9

    def due(self, t: float) -> bool:
        return t - self.last_t >= self.interval

    def add(self, fit: dict | None, frame_wh: tuple[int, int]) -> None:
        if fit is None or fit["inlier_frac"] < self.MIN_INLIER:
            self.rejected += 1
            return
        r = plane_roll_deg(fit, frame_wh)
        if not np.isfinite(r) or abs(r) > self.MAX_ABS:
            self.rejected += 1
            return
        self.vals = (self.vals + [r])[-7:]

    @property
    def deg(self) -> float | None:
        if len(self.vals) < self.MIN_N:
            return None
        v = np.array(self.vals[-5:])
        return float(np.median(v)) if float(np.ptp(v)) <= self.MAX_SPREAD else None

    def a_px(self, frame_w: int) -> float | None:
        d = self.deg
        return None if d is None else float(-frame_w * np.tan(np.radians(d)))


# ---------------------------------------------------------------- 물체 마우스: 깊이 모델로 앞뒤 위치
def object_depth_position(depth: np.ndarray, obj_mask: np.ndarray, exclude: np.ndarray | None = None,
                          top_frac: float = 0.3, rows: tuple[float, float] | None = None) -> dict | None:
    """물체가 책상 앞뒤 어디쯤인지 0(책상 먼 쪽 가장자리)~1(가까운 쪽 가장자리)로. 깊이 모델의 값은 프레임마다 스케일·이동이 달라서
    같은 프레임의 책상 평면(화면 아래쪽에서 물체를 뺀 영역에 RANSAC)으로 정규화한다.
    책상의 먼 쪽·가까운 쪽 가장자리 행(rows)은 평면에 실제로 맞는 픽셀(내점)의 3~97% 행으로 잡는다 — 셔츠·벽처럼 평면에 안 맞는 곳은 뺀다.
    rows 를 주면(천천히 갱신되는 기준) 그 행으로 정규화해 프레임마다 흔들리지 않게 한다.
    물체 값은 마스크 아래쪽 절반(바닥에 닿은 쪽)의 중앙값. 들어올리면 평면보다 가까워 u 가 커진다.
    depth, obj_mask, exclude 는 같은 해상도(깊이 모델 출력). 믿을 수 없으면 None."""
    h, w = depth.shape
    if obj_mask.shape != (h, w) or int(obj_mask.sum()) < 30:
        return None
    ys, xs = np.nonzero(obj_mask)
    excl = obj_mask.astype(np.uint8)
    if exclude is not None:
        excl = excl | exclude.astype(np.uint8)
    excl = cv2.dilate(excl, np.ones((9, 9), np.uint8)) > 0
    region = np.zeros((h, w), bool)
    region[int(top_frac * h):] = True
    region &= ~excl
    fit = fit_depth_plane(depth, region)
    if fit is None or fit["inlier_frac"] < 0.35:
        return None
    gy, gx = np.mgrid[0:h, 0:w].astype(np.float32)
    plane = fit["A"] * (gx + .5) / w + fit["B"] * (gy + .5) / h + fit["C"]
    inl = region & (np.abs(plane - depth) < 0.06 * fit["span"])
    cnt = inl.sum(1)
    ok = np.nonzero(cnt >= 0.1 * w)[0]
    if ok.size < 0.1 * h:
        return None
    mine = (float(np.percentile(ok, 3)) + .5) / h, (float(np.percentile(ok, 97)) + .5) / h
    y_top, y_bot = rows if rows is not None else mine
    xc = (float(xs.mean()) + .5) / w
    at = lambda y: fit["A"] * xc + fit["B"] * y + fit["C"]  # noqa: E731
    span = at(y_bot) - at(y_top)
    if abs(span) < 0.05 * fit["span"] or y_bot - y_top < 0.1:
        return None            # 평면이 거의 안 기울었다: 앞뒤를 구분할 수 없다
    low = ys >= np.percentile(ys, 50)
    d_obj = float(np.median(depth[ys[low], xs[low]]))
    return {"u": float((d_obj - at(y_top)) / span), "rows": mine, "inlier_frac": fit["inlier_frac"]}


class ObjectDepth:
    """물체 마우스의 깊이 모델 앞뒤 위치 u (책상 먼 쪽 0 ~ 가까운 쪽 1). 백그라운드(~10Hz)에서 갱신한다.

    기준(책상 가장자리 행)은 천천히 갱신하는 이동평균이라 프레임마다 흔들리지 않는다 — 처음 몇 번의 측정으로 정하고, 이후에는
    조금씩 따라간다(주기적 자동 갱신). 카메라를 옮겨 기준이 크게 어긋나면(5번 연속) 자동으로 다시 잡고, 사용자가 버튼으로 다시 잡을 수도 있다."""
    MAX_AGE = 0.6
    REF_RATE = 0.05        # 측정 한 번당 기준을 따라가는 비율 (10Hz 에서 약 2초 시상수)
    MOVED = 0.06           # 기준 행이 이만큼(프레임 높이 비율) 어긋난 채 5번 이어지면 카메라가 움직인 것
    U_MIN, U_MAX = -0.6, 1.6

    def __init__(self, interval: float = 0.1) -> None:
        self.interval = interval
        self.last_t = -1e9
        self.value: float | None = None
        self.t_value = -1e9
        self.fail = 0
        self.rows: tuple[float, float] | None = None
        self.n_ref = 0
        self._moved = 0
        self.reference_resets = 0
        self.ref_generation = 0          # 기준을 새로 잡을 때마다 +1 (커서가 점프하지 않게 호출자가 커서를 리셋한다)

    def reset(self) -> None:
        """물체/모드가 바뀜: 값만 버린다 (기준 행은 책상에 대한 것이라 유지)."""
        self.value, self.t_value, self.last_t = None, -1e9, -1e9

    def reset_reference(self) -> None:
        """기준(책상 가장자리 행)을 처음부터 다시 잡는다 (사용자 버튼 또는 카메라가 움직였을 때)."""
        self.rows, self.n_ref, self._moved = None, 0, 0
        self.reference_resets += 1
        self.ref_generation += 1
        self.reset()

    def due(self, t: float) -> bool:
        return t - self.last_t >= self.interval

    def update(self, res: dict | None, t: float) -> None:
        if res is None:
            self.fail += 1
            return
        self.fail = 0
        mine = res.get("rows")
        if mine is not None:
            if self.rows is None:
                self.rows, self.n_ref = mine, 1
            else:
                far = max(abs(mine[0] - self.rows[0]), abs(mine[1] - self.rows[1]))
                self._moved = self._moved + 1 if far > self.MOVED else 0
                if self._moved >= 5:
                    self.reset_reference()
                    self.rows, self.n_ref = mine, 1
                    return
                k = self.REF_RATE if self.n_ref >= 5 else 0.3          # 처음에는 빨리 모은다
                self.rows = (self.rows[0] + k * (mine[0] - self.rows[0]), self.rows[1] + k * (mine[1] - self.rows[1]))
                self.n_ref += 1
        self.value, self.t_value = float(np.clip(res["u"], self.U_MIN, self.U_MAX)), t

    def scale(self, t: float) -> float | None:
        """깊이 커서(크기 자리)에 넣을 값 exp(u): 커서는 log(크기)를 쓰므로 u 가 그대로 세로 움직임이 된다."""
        return float(np.exp(self.value)) if self.value is not None and t - self.t_value <= self.MAX_AGE else None


def scene_map_images(logit: np.ndarray | None, size: tuple[int, int] | None = None, cells=None,
                     cell_thr: float = 0.15, out_w: int = 480) -> dict:
    """개발자 보기: 배경 모델 → 반투명 PNG. 빨강 = 전경(배경과 달라짐), 파랑 = 배경 그대로, 투명 = 모름(0).
    cells = (칸마다 바뀐 비율, 배경을 아는 칸) 이면 무효 판정 격자를 겹친다: 주황 테두리 = 바뀐 칸, 회색 = 모르는 칸(세지 않음),
    가는 흰 선 = 그대로인 칸. logit 이 None(무효)이어도 격자만 그린다 (왜 꺼졌는지 보이게)."""
    from .pen_floor import _png
    if logit is not None:
        h, w = logit.shape
    else:
        w, h = size or (16, 9)
    sh = max(8, round(h * out_w / w))
    rgba = np.zeros((sh, out_w, 4), np.uint8)
    fg_frac = None
    if logit is not None:
        lg = cv2.resize(logit.astype(np.float32), (out_w, sh), interpolation=cv2.INTER_AREA)
        a = np.clip(np.abs(lg) / 3.0, 0, 1)
        fg = lg > 0
        rgba[..., 2] = np.where(fg, 255, 40)          # BGR: 빨강
        rgba[..., 0] = np.where(fg, 40, 255)          # 파랑
        rgba[..., 1] = 40
        rgba[..., 3] = (a * np.where(fg, 200, 110)).astype(np.uint8)   # 배경은 옅게
        fg_frac = round(float((lg > 1).mean()), 3)
    grid = None
    if cells is not None:
        frac, ok = cells
        gh, gw = frac.shape
        changed = ok & (frac > cell_thr)
        for j in range(gh):
            for i in range(gw):
                x0, x1 = round(i * out_w / gw), round((i + 1) * out_w / gw) - 1
                y0, y1 = round(j * sh / gh), round((j + 1) * sh / gh) - 1
                if not ok[j, i]:
                    sub = rgba[y0:y1 + 1, x0:x1 + 1]
                    sub[..., :3] = (sub[..., :3] * 0.4 + 60).astype(np.uint8)
                    sub[..., 3] = np.maximum(sub[..., 3], 90)
                    cv2.rectangle(rgba, (x0, y0), (x1, y1), (160, 160, 160, 160), 1)
                elif changed[j, i]:
                    cv2.rectangle(rgba, (x0 + 1, y0 + 1), (x1 - 1, y1 - 1), (0, 165, 255, 255), 2)
                    cv2.putText(rgba, f"{int(100 * frac[j, i])}", (x0 + 4, y0 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.38,
                                (0, 165, 255, 255), 1, cv2.LINE_AA)
                else:
                    cv2.rectangle(rgba, (x0, y0), (x1, y1), (255, 255, 255, 70), 1)
        n_ok = int(ok.sum())
        grid = {"cols": gw, "rows": gh, "known": n_ok, "changed": int(changed.sum())}
    return {"size": [w, h], "overlay": _png(rgba), "fg_frac": fg_frac, "grid": grid}


def depth_map_images(depth: np.ndarray, out_w: int = 320, alpha: float = 0.6) -> dict:
    """개발자 보기: 깊이 맵을 색(가까움=밝은 노랑, 멈=어두운 보라)으로. 값은 프레임마다 상대적이라 2~98% 로 늘린다.
    image 는 불투명 PNG, overlay 는 카메라 영상 위에 겹칠 반투명 PNG."""
    from .pen_floor import _png
    lo, hi = (float(v) for v in np.percentile(depth, [2, 98]))
    g = np.clip((depth - lo) / max(hi - lo, 1e-9), 0, 1)
    h, w = depth.shape
    sh = max(8, round(h * out_w / w))
    color = cv2.applyColorMap(cv2.resize((255 * g).astype(np.uint8), (out_w, sh), interpolation=cv2.INTER_AREA), cv2.COLORMAP_INFERNO)
    rgba = np.dstack([color, np.full((sh, out_w), int(255 * alpha), np.uint8)])
    return {"size": [w, h], "image": _png(color), "overlay": _png(rgba), "lo": round(lo, 4), "hi": round(hi, 4)}
