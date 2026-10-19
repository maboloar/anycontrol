"""정지 떨림 지표. 물체가 멈춰 있을 때 추적 출력이 얼마나 흔들리고 흘러가는가.

series 는 프레임별 dict 목록 (아래 키는 run.py 가 채운다):
    t, cx, cy, ls, th   스무딩된 출력 포즈 (원본 프레임 좌표)
    rx, ry              칼만 원시 포즈 (One Euro 이전)
    mcx, mcy            출력 마스크 중심 (작업 해상도로 줄인 마스크, 원본 좌표로 환산)
    iou                 직전 프레임 마스크와의 IoU
    area                마스크 면적 비율 (프레임 대비)
    fx, fy              마스크로 잰 닿은 점 (mask_foot, 종이 보정 시 커서가 쓰는 값)
    curx, cury          앱의 MouseController 가 낸 커서 위치 (화면 비율 0..1)
    visible             보이는 상태인가

모든 지표는 '작을수록 좋다'(iou 와 jump 제외).
"""
from __future__ import annotations

import math

import numpy as np


def _arr(series: list[dict], key: str) -> np.ndarray:
    return np.array([s[key] for s in series if s.get(key) is not None and s.get("visible", True)], float)


def path_length(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.hypot(np.diff(x), np.diff(y)).sum()) if len(x) > 1 else 0.0


def drift(t: np.ndarray, x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """직선 적합 기울기로 본 흐름 속도(px/분)와 전체 이동 폭(최대-최소, px)."""
    if len(t) < 3:
        return 0.0, 0.0
    sx = np.polyfit(t, x, 1)[0]
    sy = np.polyfit(t, y, 1)[0]
    span = math.hypot(float(np.ptp(x)), float(np.ptp(y)))
    return float(math.hypot(sx, sy) * 60.0), span


def accel_rms(x: np.ndarray, y: np.ndarray) -> float:
    """2차 차분 RMS (px/프레임²). 느린 실제 이동(등속)은 0 이고 프레임마다 튀는 잡음만 남는다."""
    if len(x) < 3:
        return 0.0
    return float(np.sqrt(np.mean(np.diff(x, 2) ** 2 + np.diff(y, 2) ** 2)))


def still_summary(series: list[dict], size: float, warmup: int = 0, truth: list | None = None,
                  screen: tuple[int, int] = (1920, 1080)) -> dict:
    """정지 구간 요약. size = 물체 크기(px), 정규화한 값은 크기 대비 비율."""
    s = series[warmup:]
    t = _arr(s, "t")
    out: dict = {"frames": len(s), "visible_frac": round(float(np.mean([x.get("visible", True) for x in s])) if s else 0, 3)}
    if len(t) < 5:
        return out
    cx, cy = _arr(s, "cx"), _arr(s, "cy")
    rx, ry = _arr(s, "rx"), _arr(s, "ry")
    mcx, mcy = _arr(s, "mcx"), _arr(s, "mcy")
    fx, fy = _arr(s, "fx"), _arr(s, "fy")
    ious = _arr(s, "iou")
    curx, cury = _arr(s, "curx"), _arr(s, "cury")
    dur = float(t[-1] - t[0]) or 1.0
    rate = lambda x, y: round(path_length(x, y) / dur, 3)   # noqa: E731  (px/s: 가만히 있을 때 0 이어야 한다)
    std = lambda x, y: round(float(math.hypot(np.std(x), np.std(y))), 3)  # noqa: E731
    dr, span = drift(t, cx, cy)
    out.update({
        "pose_std_px": std(cx, cy),
        "pose_path_px_s": rate(cx, cy),
        "raw_std_px": std(rx, ry) if len(rx) else None,
        "mask_center_std_px": std(mcx, mcy) if len(mcx) else None,
        "foot_std_px": std(fx, fy) if len(fx) else None,
        "foot_path_px_s": rate(fx, fy) if len(fx) else None,
        "accel_rms_px": round(accel_rms(cx, cy), 4),
        "raw_accel_px": round(accel_rms(rx, ry), 4) if len(rx) else None,
        "cursor_path_px_s": round(path_length(curx * screen[0], cury * screen[1]) / dur, 2) if len(curx) else None,
        "cursor_drift_px": round(float(math.hypot((curx[-1] - curx[0]) * screen[0], (cury[-1] - cury[0]) * screen[1])), 2)
        if len(curx) else None,
        "drift_px_min": round(dr, 3),
        "excursion_px": round(span, 3),
        "pose_std_rel": round(std(cx, cy) / max(size, 1.0), 5),
        "iou_mean": round(float(np.mean(ious)), 4) if len(ious) else None,
        "iou_p05": round(float(np.percentile(ious, 5)), 4) if len(ious) else None,
        "jump_frames": int(np.sum(ious < 0.9)) if len(ious) else 0,    # 윤곽이 확 바뀐 프레임 수
    })
    if truth is not None:
        tr = np.array(truth[warmup:warmup + len(s)], float)
        ok = [i for i, x in enumerate(s) if x.get("visible", True) and x["cx"] is not None]
        if len(ok) == len(tr) and len(tr) > 2:
            err = np.hypot(cx - cx[0] - (tr[:, 0] - tr[0, 0]), cy - cy[0] - (tr[:, 1] - tr[0, 1]))
            out["truth_err_mean_px"] = round(float(err.mean()), 3)
            out["truth_err_max_px"] = round(float(err.max()), 3)
    return out


def response_delay(series: list[dict], onset: int, shift_per_frame: float, frames_moved: int) -> dict:
    """정지 뒤 일정 속도로 움직이기 시작했을 때의 반응.

    delay_frames: 실제 이동량의 50% 에 처음 도달한 프레임 수 (onset 기준). 정지 잠금이 풀리는 데 걸리는 시간.
    end_lag_px:   이동이 끝난 시점에 출력 포즈가 실제보다 얼마나 뒤처졌나.
    """
    base = [s for s in series[max(0, onset - 15):onset] if s.get("visible", True) and s["cx"] is not None]
    if not base:
        return {"delay_frames": None, "end_lag_px": None}
    x0 = float(np.mean([s["cx"] for s in base]))
    delay = None
    for k in range(frames_moved):
        i = onset + k
        if i >= len(series) or not series[i].get("visible", True) or series[i]["cx"] is None:
            continue
        true = shift_per_frame * (k + 1)
        if series[i]["cx"] - x0 >= 0.5 * true:
            delay = k + 1
            break
    end = onset + frames_moved - 1
    lag = None
    if end < len(series) and series[end].get("visible", True) and series[end]["cx"] is not None:
        lag = round(shift_per_frame * frames_moved - (series[end]["cx"] - x0), 3)
    return {"delay_frames": delay, "end_lag_px": lag}


def format_table(rows: dict[str, dict]) -> str:
    cols = ["accel_rms_px", "raw_accel_px", "pose_std_px", "mask_center_std_px", "foot_std_px", "cursor_path_px_s",
            "cursor_drift_px", "drift_px_min", "iou_mean", "jump_frames", "truth_err_mean_px", "delay_frames", "end_lag_px"]
    w = max([len(k) for k in rows] + [10])
    head = f"{'':{w}s} " + " ".join(f"{c.replace('_px','').replace('_s','')[:11]:>11s}" for c in cols)
    lines = [head]
    for name, r in rows.items():
        cells = []
        for c in cols:
            v = r.get(c)
            cells.append(f"{'-':>11s}" if v is None else f"{v:11.3f}" if isinstance(v, float) else f"{v:11d}")
        lines.append(f"{name:{w}s} " + " ".join(cells))
    return "\n".join(lines)
