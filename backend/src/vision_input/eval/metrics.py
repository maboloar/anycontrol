"""추적 지표.

프레임별 판정
- 물체가 충분히 보이는 프레임(visible_frac >= 0.25):
    성공 = 예측 전체(amodal) 박스 또는 보이는 박스가 정답과 IoU >= 0.5
- 거의 안 보이는 프레임(가림·이탈): 예측이 "보인다"(tracking/grasped)면서
  정답 물체와 겹치지 않으면 오검출(false positive). 상태 유지(occluded)는 정상.
- 방해물로 옮겨붙음(hijack): 예측 박스가 정답보다 방해물과 더 겹침

요약
- success: 가시 프레임 성공률
- robust: 가시 프레임에서 "보인다"고 판정한 비율 (놓침 없이 유지)
- fp_rate: 비가시 프레임 오검출률
- hijacks: 방해물로 옮겨붙은 프레임 수
- recovery_frames: 가림·이탈이 끝나고 다시 성공하기까지 걸린 프레임 (평균, 복구 못 하면 구간 길이)
- center_err: 성공 프레임의 중심 오차 / 물체 크기 (정규화)
- scale_err: |log(scale_pred / scale_gt)| 평균 (깊이 축)
- jitter: 정답이 거의 정지한 구간의 예측 중심 표준편차 / 물체 크기
- occl_jump: 손이 붙거나 떨어지는 순간 전후 축 값 변화 (가림 때문에 값이 튀는지)
- ms_p50 / ms_p95: step 처리 시간
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..tracking.api import Box, TrackOutput, box_iou

VISIBLE_MIN = 0.25


def _box_size(b: Box) -> float:
    return float(np.sqrt(max(1.0, (b[2] - b[0]) * (b[3] - b[1]))))


def _center(b: Box) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


@dataclass
class FrameRecord:
    visible: bool
    in_view: bool
    success: bool
    said_visible: bool
    false_positive: bool
    hijack: bool
    center_err: float | None
    scale_ratio: float | None
    gt_center: tuple[float, float]
    pred_center: tuple[float, float] | None
    gt_size: float
    hand_frac: float
    ms: float


@dataclass
class SequenceScore:
    name: str
    frames: list[FrameRecord] = field(default_factory=list)

    def add(self, gt_target: dict, distractors: list[dict], hand_frac: float, out: TrackOutput | None,
            ms: float, init_scale_px: float) -> None:
        vis = gt_target["visible_frac"] >= VISIBLE_MIN and gt_target["visible_box"] is not None
        gt_amodal = gt_target["amodal_box"]
        gt_vis = gt_target["visible_box"]
        said = out is not None and out.state.visible and (out.box is not None or out.pose is not None)
        pred_box = None
        if out is not None:
            if out.pose is not None and out.box is not None:
                pred_box = out.box
            elif out.box is not None:
                pred_box = out.box
        # amodal 박스 예측: pose 가 있으면 보이는 박스 대신 쓴다
        pred_amodal = out.debug.get("amodal_box") if out is not None else None
        iou = max(box_iou(pred_box, gt_vis), box_iou(pred_box, gt_amodal),
                  box_iou(pred_amodal, gt_amodal)) if said else 0.0
        success = vis and said and iou >= 0.5
        overlap_gt = max(box_iou(pred_box, gt_amodal), box_iou(pred_amodal, gt_amodal)) if said else 0.0
        fp = (not vis) and said and overlap_gt < 0.1
        hijack = False
        if said and distractors:
            best_d = max(box_iou(pred_box, d["box"]) for d in distractors)
            hijack = best_d > 0.3 and best_d > overlap_gt
        size = _box_size(gt_amodal) if gt_amodal else 1.0
        gc = (gt_target["cx"], gt_target["cy"])
        pc = None
        if out is not None and out.pose is not None:
            pc = (out.pose.cx, out.pose.cy)
        elif pred_box is not None:
            pc = _center(pred_box)
        cerr = None
        if success and pc is not None:
            cerr = float(np.hypot(pc[0] - gc[0], pc[1] - gc[1]) / size)
        sratio = None
        if success and out is not None and out.pose is not None and gt_target.get("scale"):
            sratio = float(out.pose.scale / gt_target["scale"])
        self.frames.append(FrameRecord(vis, gt_target["in_view"], success, said, fp, hijack, cerr, sratio,
                                       gc, pc if said else None, size, hand_frac, ms))

    def summary(self) -> dict[str, float | int | str | None]:
        fr = self.frames
        vis = [f for f in fr if f.visible]
        invis = [f for f in fr if not f.visible]
        ms = np.array([f.ms for f in fr]) if fr else np.zeros(1)
        cerr = [f.center_err for f in fr if f.center_err is not None]
        sr = [abs(np.log(f.scale_ratio)) for f in fr if f.scale_ratio]
        return {
            "name": self.name,
            "frames": len(fr),
            "success": _ratio(sum(f.success for f in vis), len(vis)),
            "robust": _ratio(sum(f.said_visible for f in vis), len(vis)),
            "fp_rate": _ratio(sum(f.false_positive for f in invis), len(invis)),
            "hijacks": int(sum(f.hijack for f in fr)),
            "recovery_frames": self._recovery(),
            "center_err": None if not cerr else round(float(np.mean(cerr)), 4),
            "scale_err": None if not sr else round(float(np.mean(sr)), 4),
            "jitter": self._jitter(),
            "wobble": self._wobble(),
            "occl_jump": self._occlusion_jump(),
            "ms_p50": round(float(np.percentile(ms, 50)), 2),
            "ms_p95": round(float(np.percentile(ms, 95)), 2),
        }

    def _recovery(self) -> float | None:
        """비가시 구간이 끝난 뒤 첫 성공까지의 프레임 수."""
        fr, gaps, i = self.frames, [], 0
        while i < len(fr):
            if not fr[i].visible:
                j = i
                while j < len(fr) and not fr[j].visible:
                    j += 1
                if j - i >= 3 and j < len(fr):  # 3프레임 이상 비가시 구간만
                    k = j
                    while k < len(fr) and fr[k].visible and not fr[k].success:
                        k += 1
                    gaps.append(k - j)
                i = j
            else:
                i += 1
        return None if not gaps else round(float(np.mean(gaps)), 2)

    def _jitter(self) -> float | None:
        """정답이 5프레임 동안 물체 크기의 0.5% 미만으로 움직인 구간에서 예측 떨림."""
        fr = self.frames
        vals = []
        for i in range(len(fr) - 5):
            win = fr[i : i + 5]
            if not all(f.success and f.pred_center for f in win):
                continue
            g = np.array([f.gt_center for f in win])
            size = win[0].gt_size
            if np.ptp(g, 0).max() / size > 0.005:
                continue
            p = np.array([f.pred_center for f in win])
            vals.append(float(np.std(p - g, 0).max() / size))
        return None if not vals else round(float(np.mean(vals)), 5)

    def _wobble(self) -> float | None:
        """떨림: 예측 중심의 2차 차분 크기 / 물체 크기 (연속 3프레임 모두 보일 때).

        실제 움직임의 2차 차분(가속)은 60fps 에서 매우 작으므로, 이 값의 대부분은 추정 잡음이다.
        정답이 매 프레임 있으면 정답의 2차 차분을 빼서 실제 가속을 제외한다.
        """
        fr, vals = self.frames, []
        for i in range(1, len(fr) - 1):
            a, b, c = fr[i - 1], fr[i], fr[i + 1]
            if not (a.pred_center and b.pred_center and c.pred_center):
                continue
            d2 = np.hypot(a.pred_center[0] - 2 * b.pred_center[0] + c.pred_center[0],
                          a.pred_center[1] - 2 * b.pred_center[1] + c.pred_center[1])
            g2 = np.hypot(a.gt_center[0] - 2 * b.gt_center[0] + c.gt_center[0],
                          a.gt_center[1] - 2 * b.gt_center[1] + c.gt_center[1])
            vals.append(max(0.0, d2 - g2) / b.gt_size)
        return None if not vals else round(float(np.mean(vals)), 5)

    def _occlusion_jump(self) -> float | None:
        """손 가림 비율이 크게 바뀌는 프레임 전후로, 정답 변화 대비 예측 변화의 초과분."""
        fr, jumps = self.frames, []
        for i in range(1, len(fr)):
            a, b = fr[i - 1], fr[i]
            if abs(b.hand_frac - a.hand_frac) < 0.2 or not (a.pred_center and b.pred_center):
                continue
            dp = np.hypot(b.pred_center[0] - a.pred_center[0], b.pred_center[1] - a.pred_center[1])
            dg = np.hypot(b.gt_center[0] - a.gt_center[0], b.gt_center[1] - a.gt_center[1])
            jumps.append(max(0.0, dp - dg) / b.gt_size)
        return None if not jumps else round(float(np.mean(jumps)), 4)


def _ratio(a: int, b: int) -> float | None:
    return None if b == 0 else round(a / b, 4)


def aggregate(summaries: list[dict]) -> dict[str, float | None]:
    keys = ["success", "robust", "fp_rate", "recovery_frames", "center_err", "scale_err", "jitter",
            "wobble", "occl_jump", "ms_p50", "ms_p95"]
    out: dict[str, float | None] = {}
    for k in keys:
        vals = [s[k] for s in summaries if s.get(k) is not None]
        out[k] = None if not vals else round(float(np.mean(vals)), 4)
    out["hijacks"] = float(sum(s["hijacks"] for s in summaries))
    out["sequences"] = float(len(summaries))
    return out
