"""Tier 1: 스트리밍 마스크 모델 (EfficientTAM-Ti), 모션 인식 메모리.

공식 video predictor 는 영상 전체를 미리 읽어야 해서 웹캠에 쓸 수 없다. 여기서는 기반 모델의
저수준 함수(forward_image, _track_step, _encode_memory_in_output)를 직접 불러 프레임을 하나씩 넣는다.

메모리 관리 (SAMURAI / DAM4SAM 아이디어를 물체 종류와 무관하게 적용)
- 후보 선택: 모델의 3개 후보 마스크 중 "예측 IoU × Tier 0 예측 박스와의 겹침" 이 가장 큰 것.
  모델 자신의 확신만으로 고르면 비슷한 다른 물체·배경으로 옮겨 가기 쉽다.
- 메모리 저장: 물체 점수 > 0, 예측 IoU 높음, 움직임 예측과 일치, 크게 가려지지 않음 일 때만.
  손에 쥔 프레임·흐린 프레임이 메모리를 오염시키지 않는다. 저장하지 않은 프레임의 번호는
  다음 프레임이 재사용하므로, 메모리 창은 항상 "최근의 좋은 프레임 6장" 이다.
- 앵커: 크기·모양이 등록 때와 많이 달라졌고 매우 확실한 프레임은 조건 프레임으로 올린다(최대 3).
  깊이 방향으로 크게 움직여도 외형 기억이 따라간다.
- 모든 GPU 작업은 gpu.py 의 단일 스레드에서만 한다.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import gpu

log = logging.getLogger(__name__)

CONFIG = "configs/efficienttam/efficienttam_ti_512x512.yaml"
CKPT = "efficienttam_ti_512x512.pt"
BIG = 10**9
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


@dataclass
class ObjectMemory:
    cond: dict[int, dict] = field(default_factory=dict)       # 조건 프레임 (등록 + 앵커)
    non_cond: dict[int, dict] = field(default_factory=dict)   # 최근 좋은 프레임
    next_idx: int = 1
    anchor_scales: list[float] = field(default_factory=list)  # 앵커의 log-scale (등록 = 0)
    # 자체 움직임 모델 (SAMURAI): Tier 0 와 독립이어야 Tier 0 의 오류를 따라가지 않는다
    boxes: list[tuple[float, tuple[float, float, float, float]]] = field(default_factory=list)  # (t, box 0..1)
    area0: float = 0.0          # 등록 마스크 면적 (정규화)
    areas: list[float] = field(default_factory=list)          # 최근 좋은 프레임 면적 (가림 판단용)

    def predict_box(self, t: float) -> tuple[float, float, float, float] | None:
        if not self.boxes:
            return None
        t1, b1 = self.boxes[-1]
        if len(self.boxes) < 2:
            return b1
        t0, b0 = self.boxes[-2]
        dt = max(t1 - t0, 1e-3)
        k = min((t - t1) / dt, 3.0)  # 너무 멀리 외삽하지 않는다
        return tuple(b1[i] + (b1[i] - b0[i]) * k for i in range(4))  # type: ignore[return-value]

    def expected_area(self) -> float:
        return float(np.median(self.areas[-5:])) if self.areas else self.area0

    @property
    def output_dict(self) -> dict:
        return {"cond_frame_outputs": self.cond, "non_cond_frame_outputs": self.non_cond}


@dataclass
class T1Result:
    mask_logits: np.ndarray    # (128, 128) float32, 모델 입력(정사각 리사이즈) 좌표
    object_score: float        # logit. > 0 이면 물체 있음
    iou: float                 # 선택한 후보의 예측 IoU (0..1)
    motion_iou: float          # Tier 0 예측 박스와의 겹침
    stored: bool
    anchored: bool


class StreamingTAM:
    """물체 여러 개를 한 모델로. 프레임당 이미지 인코딩은 한 번만 하고 물체마다 메모리를 따로 둔다."""

    def __init__(self) -> None:
        self.model = None
        self.mem: dict[int, ObjectMemory] = {}
        self.max_anchors = 3
        self.keep_non_cond = 16  # obj_ptr 가 최대 16 프레임까지 되돌아본다

    # -------------------------------------------------------------- 모델 (GPU 스레드)
    def _load(self):
        if self.model is None:
            from efficient_track_anything.build_efficienttam import build_efficienttam_video_predictor

            self.model = build_efficienttam_video_predictor(CONFIG, str(gpu.MODELS_DIR / CKPT), device=gpu.device())
            self.S = int(self.model.image_size)
        return self.model

    def _encode(self, frame_bgr: np.ndarray):
        import torch

        m = self._load()
        rgb = cv2.cvtColor(cv2.resize(frame_bgr, (self.S, self.S), interpolation=cv2.INTER_LINEAR), cv2.COLOR_BGR2RGB)
        x = (rgb.astype(np.float32) / 255.0 - MEAN) / STD
        img = torch.from_numpy(x.transpose(2, 0, 1)).unsqueeze(0).to(gpu.device())
        backbone = m.forward_image(img)
        _, vf, vp, fs = m._prepare_backbone_features(backbone)
        return vf, vp, fs

    @staticmethod
    def _compact(out: dict) -> dict:
        import torch

        mf = out["maskmem_features"]
        return {"maskmem_features": None if mf is None else mf.to(torch.bfloat16),
                "maskmem_pos_enc": out["maskmem_pos_enc"], "pred_masks": out["pred_masks"],
                "obj_ptr": out["obj_ptr"], "object_score_logits": out["object_score_logits"]}

    # -------------------------------------------------------------- API (GPU 스레드에서 호출됨)
    def add(self, oid: int, frame_bgr: np.ndarray, mask: np.ndarray) -> None:
        import torch

        m = self._load()
        with torch.inference_mode(), torch.autocast(gpu.device().type, dtype=torch.float16):
            vf, vp, fs = self._encode(frame_bgr)
            mt = torch.from_numpy(cv2.resize(mask.astype(np.float32), (self.S, self.S),
                                             interpolation=cv2.INTER_AREA) >= 0.5).float()[None, None]
            mt = mt.to(gpu.device())
            mem = ObjectMemory()
            out, sam, _, _ = m._track_step(0, True, vf, vp, fs, None, mt, mem.output_dict, BIG, False, None)
            _, _, _, _, high, obj_ptr, osl = sam
            out.update(pred_masks=sam[3], obj_ptr=obj_ptr, object_score_logits=osl)
            m._encode_memory_in_output(vf, fs, None, True, high, osl, out)
            mem.cond[0] = self._compact(out)
            mem.anchor_scales.append(0.0)
        H, W = mask.shape
        ys, xs = np.nonzero(mask)
        mem.area0 = float(mask.mean())
        mem.areas.append(mem.area0)
        mem.boxes.append((self._t, (xs.min() / W, ys.min() / H, (xs.max() + 1) / W, (ys.max() + 1) / H)))
        self.mem[oid] = mem

    _t: float = 0.0

    def set_time(self, t: float) -> None:
        self._t = t

    def remove(self, oid: int) -> None:
        self.mem.pop(oid, None)
    def reanchor(self, oid: int, frame_bgr: np.ndarray, mask: np.ndarray, t: float) -> None:
        """검증된 새 마스크(주기적 재분할)를 조건 프레임으로 넣는다. 등록 조건 프레임은 그대로 두고
        가장 오래된 앵커를 바꾸며, 최근 비조건 메모리는 비운다 (오염됐을 수 있으므로 새 닻에서 다시 쌓는다)."""
        import torch

        mem = self.mem.get(oid)
        if mem is None or not mask.any():
            return
        m = self._load()
        with torch.inference_mode(), torch.autocast(gpu.device().type, dtype=torch.float16):
            vf, vp, fs = self._encode(frame_bgr)
            mt = torch.from_numpy(cv2.resize(mask.astype(np.float32), (self.S, self.S),
                                             interpolation=cv2.INTER_AREA) >= 0.5).float()[None, None].to(gpu.device())
            idx = mem.next_idx
            out, sam, _, _ = m._track_step(idx, True, vf, vp, fs, None, mt, mem.output_dict, BIG, False, None)
            _, _, _, _, high, obj_ptr, osl = sam
            out.update(pred_masks=sam[3], obj_ptr=obj_ptr, object_score_logits=osl)
            m._encode_memory_in_output(vf, fs, None, True, high, osl, out)
        anchors = sorted(k for k in mem.cond if k != 0)
        if len(anchors) >= self.max_anchors:
            mem.cond.pop(anchors[0])
            if len(mem.anchor_scales) > 1:
                mem.anchor_scales.pop(1)
        mem.cond[idx] = self._compact(out)
        mem.anchor_scales.append(0.5 * math.log(max(float(mask.mean()), 1e-6) / max(mem.area0, 1e-6)))
        mem.non_cond.clear()
        mem.next_idx = idx + 1
        H, W = mask.shape
        ys, xs = np.nonzero(mask)
        mem.boxes = [(t, (xs.min() / W, ys.min() / H, (xs.max() + 1) / W, (ys.max() + 1) / H))]
        mem.areas = [float(mask.mean())]

    def step(self, frame_bgr: np.ndarray, ctx: dict[int, dict], t: float = 0.0) -> dict[int, T1Result]:
        """ctx[oid] = {"ls": Tier 0 log-scale (앵커 판단용)}. 위치 사전은 자체 움직임 모델만 쓴다."""
        import torch

        m = self._load()
        res: dict[int, T1Result] = {}
        with torch.inference_mode(), torch.autocast(gpu.device().type, dtype=torch.float16):
            vf, vp, fs = self._encode(frame_bgr)
            for oid, c in ctx.items():
                mem = self.mem.get(oid)
                if mem is not None:
                    res[oid] = self._step_one(m, mem, vf, vp, fs, c, t)
        return res

    def _step_one(self, m, mem: ObjectMemory, vf, vp, fs, c: dict, t: float) -> T1Result:
        idx = mem.next_idx
        out, sam, _, _ = m._track_step(idx, False, vf, vp, fs, None, None, mem.output_dict, BIG, False, None)
        low_multi, high_multi, ious, low, high, obj_ptr, osl = sam
        ious_np = ious.float()[0].cpu().numpy()
        osl_f = float(osl.float().max())
        # --- 후보 선택 (SAMURAI): 0.75·예측 IoU + 0.25·자체 움직임 예측과의 박스 겹침
        box = mem.predict_box(t)
        k = low_multi.shape[1]
        lm = low_multi.float()[0].cpu().numpy()  # (k, 128, 128)
        motion = np.ones(k, np.float32)
        if box is not None:
            for j in range(k):
                motion[j] = _mask_box_iou(lm[j] > 0, box, 1.0, 1.0)
        score = 0.75 * ious_np[:k] + 0.25 * motion
        j = int(np.argmax(score))
        if k > 1 and j != int(np.argmax(ious_np[:k])):
            # 모델 기본 선택과 다르면 해당 후보로 교체 (메모리·포인터도 그 후보 기준)
            low = low_multi[:, j : j + 1]
            high = high_multi[:, j : j + 1]
        mask_logits = low.float()[0, 0].cpu().numpy()
        iou_sel, mot_sel = float(ious_np[j]), float(motion[j])
        sel = mask_logits > 0
        area = float(sel.mean())
        area_ratio = area / max(mem.expected_area(), 1e-6)
        # --- 메모리 저장 여부: 확실 + 움직임 일치 + 갑자기 작아지지 않음(가림) + 갑자기 커지지 않음(번짐)
        present = osl_f > 0 and area > 0
        good = present and iou_sel >= 0.6 and mot_sel >= 0.3 and 0.6 <= area_ratio <= 1.6
        if present and iou_sel >= 0.5 and mot_sel >= 0.2:
            ys, xs = np.nonzero(sel)
            S = sel.shape[0]
            mem.boxes.append((t, (xs.min() / S, ys.min() / S, (xs.max() + 1) / S, (ys.max() + 1) / S)))
            del mem.boxes[:-4]
        stored = anchored = False
        if good:
            out.update(pred_masks=low, obj_ptr=obj_ptr, object_score_logits=osl)
            m._encode_memory_in_output(vf, fs, None, True, high, osl, out)
            comp = self._compact(out)
            mem.non_cond[idx] = comp
            mem.next_idx += 1
            stored = True
            mem.areas.append(area)
            del mem.areas[:-8]
            for old in [i for i in mem.non_cond if i < mem.next_idx - self.keep_non_cond]:
                del mem.non_cond[old]
            # 앵커: 매우 확실 + 크기가 기존 앵커들과 충분히 다름 (크기는 모델 자신의 면적으로 판단)
            ls = 0.5 * math.log(max(area, 1e-6) / max(mem.area0, 1e-6))
            if (iou_sel >= 0.85 and osl_f > 3 and mot_sel >= 0.6 and 0.8 <= area_ratio <= 1.25
                    and min(abs(ls - a) for a in mem.anchor_scales) > math.log(1.35)):
                if len(mem.anchor_scales) > self.max_anchors:  # 등록(0) 제외 가장 오래된 앵커 교체
                    oldest = sorted(k2 for k2 in mem.cond if k2 != 0)[0]
                    mem.cond.pop(oldest)
                    mem.anchor_scales.pop(1)
                mem.cond[idx] = comp
                mem.non_cond.pop(idx, None)
                mem.anchor_scales.append(ls)
                anchored = True
        return T1Result(mask_logits, osl_f, iou_sel, mot_sel, stored, anchored)


def _mask_box_iou(m128: np.ndarray, box, W: float, H: float) -> float:
    ys, xs = np.nonzero(m128)
    if xs.size == 0:
        return 0.0
    sx, sy = W / m128.shape[1], H / m128.shape[0]
    b = (xs.min() * sx, ys.min() * sy, (xs.max() + 1) * sx, (ys.max() + 1) * sy)
    ix = max(0.0, min(b[2], box[2]) - max(b[0], box[0]))
    iy = max(0.0, min(b[3], box[3]) - max(b[1], box[1]))
    inter = ix * iy
    union = (b[2] - b[0]) * (b[3] - b[1]) + (box[2] - box[0]) * (box[3] - box[1]) - inter
    return float(inter / union) if union > 0 else 0.0


def logits_to_mask(logits: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """(128,128) 정사각 좌표 로짓 → 프레임 크기 bool 마스크."""
    up = cv2.resize(logits, size, interpolation=cv2.INTER_LINEAR)
    return up > 0
