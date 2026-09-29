"""본 트래커 (ViTracker).

현재 단계(Task 5): Tier 0 (점 추적 + 영역 색 모델) + 칼만 + 상태 기계.
Task 6~8 에서 Tier 1(마스크 모델 보정), 손 처리, 재식별이 같은 ObjectTrack 에 측정으로 더해진다.

좌표: 내부 계산은 작업 해상도(폭 ≤ WORK_WIDTH), 출력은 원본 프레임 좌표.
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field

import cv2
import numpy as np

from .api import Box, InitPrompt, Pose, RefinedMask, TrackOutput, TrackState, mask_to_box
from .kalman import PoseKalman, pose_meas
from .measure import measure_mask
from .reacquire import ReacquireConfig, ShapeMemory, make_memory
from .reacquire import search as reacq_search
from .smooth import PoseSmoother, SmoothConfig
from .tier0 import (
    UNSEEN_PROB,
    ColorModel,
    Motion,
    _lab_index,
    refine_mask,
    ring_mask,
    sample_points,
    similarity_about,
    similarity_params,
    track_points,
    warp_mask,
)

WORK_WIDTH = 640
log = logging.getLogger(__name__)


@dataclass
class TrackerConfig:
    # 상태 기계 (모두 상대값 / 초 단위라 fps·물체와 무관)
    vis_occluded: float = 0.2        # 보이는 비율이 이보다 낮으면 가림 후보
    conf_track: float = 0.35         # 이 이상이면 추적 중
    frames_to_occlude: int = 3
    frames_to_recover: int = 2
    occluded_to_lost_s: float = 2.0
    # 점 추적
    resample_every: int = 8
    min_points_frac: float = 0.4
    # 영역 모델
    fg_rate: float = 0.05            # 신뢰 출처(Tier 1)에서 물체 색을 배우는 속도
    bg_rate: float = 0.02
    roi_margin: float = 0.6          # 예측 박스 주변 여유 (물체 크기 배)
    shape_slack: float = 0.12        # 형태 제약 여유 (물체 크기 배): 변형·포즈 오차 허용
    # Tier 1 (마스크 모델)
    tier1: str = "auto"              # auto | async | sim | off.  auto = 모델이 있으면 async
    tier1_base_ms: float = 16.0      # sim 모드 지연 모델: 인코딩 + 물체당 비용 (M3 실측)
    tier1_obj_ms: float = 45.0
    refresh_hz: float = .5            # 영상 메모리와 별개인 재분할. 기본 2초에 한 번.
    smooth: bool = True              # 출력 One Euro 필터
    smooth_min_cutoff: float = 1.2
    smooth_beta: float = 1.5
    t1_sigma_k: float = 1.0          # Tier 1 보정 측정 잡음 배율 (클수록 여러 번에 나눠 부드럽게 보정)
    region_sigma: float = 1.0        # 영역(마스크 중심) 측정 잡음 배율
    # 정지 판정 문턱 (작업 해상도 px / log-scale / 도). 점 추적 잡음 수준
    still_px: float = 0.35
    still_scale: float = 0.003
    still_deg: float = 0.15
    # 손 (set_occluders 로 손 영역을 받을 때만)
    hand_coupling: bool = True       # 크게 덮은 손의 움직임으로 포즈 옮기기
    # 방해물 스캔 주기 (프레임). 0 이하면 끔 (기본). 켜면 합성 tune 에서 twin 옮겨붙음은 157→146 으로 조금 줄지만
    # 다시 나타난 물체까지 방해물로 기억해 복구를 막는 경우가 생겨(light-full_occlusion 0.96→0.47) 기본으로 끈다.
    # 다른 추적 물체의 위치는 이 설정과 무관하게 항상 방해물로 본다 (다중 물체끼리 옮겨붙지 않게).
    distractor_every: int = 0
    # 모양 기억 재획득: 놓친(LOST/OCCLUDED) 물체를 화면 전체에서 등록 때 기억한 모양으로 다시 찾는다 (reacquire.py).
    # 추적 중(TRACKING)에는 아무것도 하지 않는다. enabled=False 면 이 기능 이전과 같은 결과.
    reacq: ReacquireConfig = field(default_factory=ReacquireConfig)


@dataclass
class ObjectTrack:
    oid: int
    k: float                          # work/full
    template: np.ndarray              # 등록 마스크 (작업 해상도)
    c0: tuple[float, float]
    area0: float
    elong0: float
    angle0: float
    box_rel: np.ndarray               # 등록 박스 꼭짓점 - 중심 (4x2)
    kf: PoseKalman
    color: ColorModel
    mask: np.ndarray                  # 현재 보이는 마스크 (작업 해상도)
    points: np.ndarray
    state: TrackState = TrackState.TRACKING
    t: float = 0.0
    t_seen: float = 0.0
    bad: int = 0
    good: int = 0
    since_sample: int = 0
    aspect: float = 1.0
    angle_cont: float = 0.0           # 영역 각도 펼침용
    conf: float = 1.0
    disc0: float = 0.0                # 등록 시 국소 색 대비 (마스크 안 물체확률 - 주변 고리 물체확률)
    p_in0: float = 0.8
    p_out0: float = 0.2
    region_conf: float = 0.0
    t1_disagree: int = 0
    t1_absent: int = 0
    t1_vis: float | None = None       # Tier 1 가 본 가시 비율 (가림 추정)
    smoother: PoseSmoother = field(default_factory=PoseSmoother)
    teleported: bool = False
    still_frames: int = 0
    debug: dict = field(default_factory=dict)
    kind: str = "object"
    # 정밀 마스크 (kind == "pen"): 가장 최근 Tier 1 마스크(원본 해상도)와, 그 마스크 시각에 해당하는 포즈
    # (보정 이후 칼만 포즈에서 그 뒤의 움직임을 뺀 값). 지금 포즈와의 차이 = 마스크를 지금으로 옮기는 변환.
    t1_mask: np.ndarray | None = None
    t1_ref: tuple[float, float, float, float] | None = None
    t1_t: float = 0.0
    distractors: list = field(default_factory=list)  # 같은 색 다른 덩어리 {"x","y","vx","vy","t","miss"}
    hand_frac: float = 0.0            # 손이 덮은 비율 (amodal 기준)
    hand_c: tuple[float, float] | None = None  # 물체 근처 손 영역 중심 (쥠 결합)
    anchor_mask: np.ndarray | None = None
    anchor_color: np.ndarray | None = None
    shape: ShapeMemory | None = None  # 등록 시 기억한 모양 (다시 선택할 때만 바뀐다)
    reacq_next: float = 0.0           # 다음 재획득 탐색 시각
    reacq_hit: tuple[float, float] | None = None  # 직전 재획득 합격 위치 (연속 확인용)
    reacq_hits: int = 0

    @property
    def size0(self) -> float:
        return math.sqrt(self.area0)

    def size_now(self) -> float:
        return self.size0 * math.exp(self.kf.x[2])


@dataclass
class _T1Job:
    t: float                                   # 작업에 쓴 프레임 시각
    poses: dict[int, tuple[float, float, float, float]]  # 그 시각 Tier 0 포즈
    idx: np.ndarray                            # 그 프레임의 Lab 색 인덱스 (색 학습용)
    ready_t: float = 0.0                       # sim 모드: 이 시각 이후에 결과를 반영
    results: dict | None = None
    future: object | None = None
    generation: int = 0


class ViTracker:
    name = "vi"

    def __init__(self, config: TrackerConfig | None = None) -> None:
        self.cfg = config or TrackerConfig()
        self.tracks: dict[int, ObjectTrack] = {}
        self.prev_gray: np.ndarray | None = None
        self.k = 1.0
        self.t_prev: float | None = None
        mode = self.cfg.tier1
        if mode != "off":
            from . import gpu
            if not gpu.ml_available():
                mode = "off"
            elif mode == "auto":
                mode = "async"
        self.t1_mode = mode
        self.tam = None
        if mode != "off":
            from .tier1 import StreamingTAM
            self.tam = StreamingTAM()
        self.t1_jobs: list[_T1Job] = []
        self.t1_next = 0.0
        self.offloaded_ms = 0.0  # 하네스용: hot loop 밖(GPU 스레드)에서 돌 작업 시간 누적
        self._occ_full: np.ndarray | None = None   # 손 영역 (원본 해상도 bool). set_occluders 로 매 프레임
        self._occ: np.ndarray | None = None
        self._others: np.ndarray | None = None      # 다른 추적 물체들의 보이는 영역 (작업 해상도)
        self.t1_stats = {"jobs": 0, "applied": 0, "resets": 0, "errors": 0, "reacq": 0, "reacq_ok": 0}
        self._reacq_jobs: list[dict] = []
        self.t1_error: str | None = None
        self.refresh_enabled = self.cfg.tier1 != "off"
        self.refresh_job: _T1Job | None = None
        self.refresh_next = 0.
        self.refresh_ms = 0.
        self.refresh_backend: str | None = None
        self.refresh_stats = {"jobs": 0, "applied": 0, "rejected": 0, "errors": 0}
        self.refresh_error: str | None = None
        self._generation = 0

    def set_occluders(self, mask: np.ndarray | None) -> None:
        """다음 step 에 쓸 손(가리는 것) 영역. None 이면 손 정보 없음 (손 검출이 꺼졌거나 손이 없음).

        손 위의 점·픽셀은 물체 측정에서 빼고, 물체를 크게 덮은 손은 '쥠' 으로 보고 손의 움직임으로 포즈를 옮긴다."""
        self._occ_full = mask

    def resume(self, t: float) -> None:
        """정지 시간 동안의 속도를 외삽하지 않고 실제 새 프레임부터 이어 간다."""
        self.t_prev = t
        for tr in self.tracks.values():
            tr.t = tr.t_seen = t
            tr.kf.x[4:] = 0
            tr.smoother.reset()
        self._generation += 1  # 정지 전 결과는 기다리되 재개 후 포즈에 적용하지 않는다.

    def configure_refresh(self, enabled: bool, hz: float) -> None:
        self.refresh_enabled, self.cfg.refresh_hz = enabled, hz
        self.refresh_next = 0.
        self._generation += 1

    @property
    def refresh_effective_hz(self) -> float:
        cost = 40. * len(self.tracks) if self.t1_mode == "sim" else self.refresh_ms
        return min(self.cfg.refresh_hz, .15 * 1000 / max(cost, 1.))

    # ---------------------------------------------------------------- 공통 전처리
    def _prep(self, frame: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        h, w = frame.shape[:2]
        self._full_size = (w, h)
        self.k = min(1.0, WORK_WIDTH / w)
        small = frame if self.k == 1.0 else cv2.resize(frame, (round(w * self.k), round(h * self.k)),
                                                       interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        return small, gray, _lab_index(small)

    # ---------------------------------------------------------------- Tracker API
    def add(self, frame: np.ndarray, obj_id: int, prompt: InitPrompt) -> TrackOutput:
        small, gray, idx = self._prep(frame)
        hw, ww = gray.shape
        if prompt.mask is not None:
            m = cv2.resize(prompt.mask.astype(np.uint8), (ww, hw), interpolation=cv2.INTER_NEAREST).astype(bool)
        else:
            # 박스만 받으면 앱과 같은 등록 분할기로 마스크를 만든다 (하네스가 실제 사용과 같은 조건이 되도록)
            from .register import RegistrationError, register
            from .segment import default_segmenter

            try:
                m = register(small, default_segmenter(), box=tuple(v * self.k for v in prompt.box)).mask
            except RegistrationError:
                b = np.array(prompt.box) * self.k
                m = np.zeros((hw, ww), bool)
                m[int(b[1]):int(b[3]), int(b[0]):int(b[2])] = True
        meas = measure_mask(m)
        if meas is None:
            raise ValueError("empty mask")
        color = ColorModel()
        size = meas.size
        color.fit(idx, m, ring_mask(m, int(size * 0.5)))
        x1, y1, x2, y2 = meas.box
        box_rel = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]]) - np.array([meas.cx, meas.cy])
        tr = ObjectTrack(obj_id, self.k, m, (meas.cx, meas.cy), meas.area, meas.elongation, meas.angle, box_rel,
                         PoseKalman(meas.cx, meas.cy, size), color, m.copy(), sample_points(gray, m, None))
        tr.t = tr.t_seen = self.t_prev or 0.0
        tr.kind = prompt.kind
        if tr.kind == "pen":  # 등록 마스크가 첫 정밀 마스크
            full = prompt.mask if prompt.mask is not None else m
            fh, fw = frame.shape[:2]
            if full.shape != (fh, fw):
                full = cv2.resize(full.astype(np.uint8), (fw, fh), interpolation=cv2.INTER_NEAREST).astype(bool)
            tr.t1_mask, tr.t1_ref, tr.t1_t = full.astype(bool), tr.kf.pose, tr.t
        prob = color.prob(idx)
        ring = ring_mask(m, int(size * 0.25))
        tr.p_in0 = float(prob[m].mean())
        tr.anchor_mask, tr.anchor_color = m.copy(), color.table.copy()
        tr.shape = make_memory(m, idx, ColorModel.NB)  # 모양 기억 (추적 중에는 바꾸지 않는다)
        tr.reacq_next = tr.t
        tr.p_out0 = float(prob[ring].mean()) if ring.any() else 0.5
        tr.disc0 = float(np.clip(tr.p_in0 - tr.p_out0, 0, 1))
        tr.smoother = PoseSmoother(SmoothConfig(min_cutoff=self.cfg.smooth_min_cutoff, beta=self.cfg.smooth_beta))
        self.tracks[obj_id] = tr
        if self.tam is not None:
            from . import gpu
            self.tam.set_time(tr.t)
            gpu.run(self.tam.add, obj_id, small, m)
        self.prev_gray = gray if self.prev_gray is None or self.prev_gray.shape != gray.shape else self.prev_gray
        return self._output(tr)

    def reselect(self, frame: np.ndarray, obj_id: int, prompt: InitPrompt) -> TrackOutput:
        """같은 id 로 새 마스크를 다시 등록한다 (모양 다시 기억): 모양 기억·색 모델·기준 외형·포즈를 새로 만들고
        Tier 1 메모리를 새 마스크로 다시 고정하며 상태는 TRACKING. 마스크가 비어 있으면 ValueError, 없는 id 면
        KeyError 이고 둘 다 아무것도 바꾸지 않는다."""
        if obj_id not in self.tracks:
            raise KeyError(obj_id)
        old = self.tracks[obj_id]
        out = self.add(frame, obj_id, prompt)  # 빈 마스크면 상태를 바꾸기 전에 ValueError
        new = self.tracks[obj_id]
        new.distractors = old.distractors
        # 예전 트랙으로 시작한 비동기 결과가 새 트랙에 섞이지 않게 버린다
        for job in self.t1_jobs:
            job.poses.pop(obj_id, None)
        if self.refresh_job is not None:
            self.refresh_job.poses.pop(obj_id, None)
        self._reacq_jobs = [j for j in self._reacq_jobs if j["oid"] != obj_id]
        return out

    def remove(self, obj_id: int) -> None:
        self.tracks.pop(obj_id, None)
        self._reacq_jobs = [j for j in self._reacq_jobs if j["oid"] != obj_id]
        if self.tam is not None:
            from . import gpu
            gpu.submit(self.tam.remove, obj_id)

    def learn_object_colors(self, obj_id: int, idx: np.ndarray, mask: np.ndarray) -> None:
        """신뢰할 수 있는 마스크(등록·Tier 1)로만 물체 색을 갱신한다."""
        tr = self.tracks.get(obj_id)
        if tr is not None:
            tr.color.fit(idx, mask, None, rate_fg=self.cfg.fg_rate, rate_bg=0.0)

    def step(self, frame: np.ndarray, t: float) -> dict[int, TrackOutput]:
        small, gray, idx = self._prep(frame)
        self._occ = None
        if self._occ_full is not None:
            self._occ = cv2.resize(self._occ_full.astype(np.uint8), gray.shape[::-1],
                                   interpolation=cv2.INTER_NEAREST).astype(bool)
            self._occ_full = None  # 한 프레임만 유효 (오래된 손 위치를 쓰지 않게)
        prev = self.prev_gray if self.prev_gray is not None and self.prev_gray.shape == gray.shape else gray
        self._t1_collect(t)  # 도착한 Tier 1 결과를 먼저 반영 (이번 프레임 Tier 0 가 보정된 상태에서 시작)
        self._refresh_collect(t)
        out = {}
        for tr in self.tracks.values():
            # 물체끼리 배타: 다른 물체가 보이는 영역은 이 물체의 점·마스크에서 뺀다 (겹쳤다 갈라질 때 옮겨붙지 않게)
            ms = [o.mask for o in self.tracks.values()
                  if o is not tr and o.state.visible and o.mask.shape == gray.shape]
            self._others = np.logical_or.reduce(ms) if ms else None
            self._step_one(tr, prev, gray, idx, t)
            out[tr.oid] = self._output(tr)
        self._refresh_submit(small, idx, t)
        self._t1_submit(small, idx, t)
        if self.cfg.reacq.enabled:
            self._reacq_collect(t)
            self._reacq_submit(small, idx, t)
        self.prev_gray = gray
        self.t_prev = t
        return out

    # ---------------------------------------------------------------- Tier 1 연동
    def _t1_submit(self, small: np.ndarray, idx: np.ndarray, t: float) -> None:
        if self.tam is None or not self.tracks or self.refresh_job is not None:
            return
        ctx, poses = {}, {}
        for tr in self.tracks.values():
            ctx[tr.oid] = {"ls": float(tr.kf.x[2])}
            poses[tr.oid] = tr.kf.pose
        from . import gpu
        if self.t1_mode == "async":
            if any(j.future is not None for j in self.t1_jobs):
                return  # 이전 작업이 아직 도는 중: 항상 최신 프레임만
            job = _T1Job(t, poses, idx, generation=self._generation)
            job.future = gpu.submit(self.tam.step, small.copy(), ctx, t)
            self.t1_jobs.append(job)
        else:  # sim: 결정적 평가. 지금 계산하고, 실측 지연만큼 뒤에 반영한다
            if t < self.t1_next:
                return
            lat = (self.cfg.tier1_base_ms + self.cfg.tier1_obj_ms * len(ctx)) / 1000.0
            job = _T1Job(t, poses, idx, ready_t=t + lat, generation=self._generation)
            import time as _time
            s = _time.perf_counter()
            job.results = gpu.run(self.tam.step, small, ctx, t)
            self.offloaded_ms += (_time.perf_counter() - s) * 1000  # 실사용에선 GPU 스레드에서 돈다
            self.t1_jobs.append(job)
            self.t1_next = t + lat
        self.t1_stats["jobs"] += 1

    def _t1_collect(self, t: float) -> None:
        keep = []
        for job in self.t1_jobs:
            if job.future is not None:
                if not job.future.done():  # type: ignore[attr-defined]
                    keep.append(job)
                    continue
                try:
                    job.results = job.future.result()  # type: ignore[attr-defined]
                    self.t1_error = None
                except Exception as exc:
                    job.results = {}
                    self.t1_stats["errors"] += 1
                    self.t1_error = str(exc)
                    log.exception("EfficientTAM correction failed")
                job.future = None
            elif t < job.ready_t:
                keep.append(job)
                continue
            if job.generation != self._generation:
                continue
            for oid, r in (job.results or {}).items():
                tr = self.tracks.get(oid)
                if tr is not None and oid in job.poses:
                    pre = tr.kf.pose
                    self._t1_fuse(tr, r, job)
                    if tr.kind == "pen":
                        self._t1_keep_refined(tr, r, job, pre)
        self.t1_jobs = keep

    def _refresh_submit(self, small: np.ndarray, idx: np.ndarray, t: float) -> None:
        if (not self.refresh_enabled or self.refresh_job is not None or self.t1_jobs
                or t < self.refresh_next or not self.tracks):
            return
        from . import gpu
        from .refresh import RefreshAnchor, resegment
        from .segment import default_segmenter
        anchors, poses = {}, {}
        for tr in self.tracks.values():
            if tr.hand_frac > .35 or tr.anchor_mask is None or tr.anchor_color is None:
                continue  # 가림 프레임으로 기준 외형을 오염시키지 않는다.
            prior = self._amodal_mask(tr)
            forbidden = np.zeros_like(prior)
            if self._occ is not None:
                forbidden |= self._occ
            for other in self.tracks.values():
                if other is not tr and other.state.visible:
                    forbidden |= other.mask
            anchors[tr.oid] = RefreshAnchor(prior.copy(), forbidden, tr.anchor_mask, tr.anchor_color, tr.p_in0)
            poses[tr.oid] = tr.kf.pose
        self.refresh_next = t + 1 / max(self.refresh_effective_hz, .01)
        if not anchors:
            return
        self.refresh_job = _T1Job(t, poses, idx.copy(), generation=self._generation)
        args = (default_segmenter(), small.copy(), idx.copy(), anchors)
        if self.t1_mode == "sim":
            # 평가에서도 재분할 반영 시점이 실행 속도/스레드 스케줄에 좌우되지 않게 한다.
            import concurrent.futures as cf
            import time
            start = time.perf_counter()
            self.refresh_job.future = cf.Future()
            try:
                self.refresh_job.future.set_result(gpu.run(resegment, *args))
            except Exception as exc:
                self.refresh_job.future.set_exception(exc)
            self.offloaded_ms += (time.perf_counter() - start) * 1000
            self.refresh_job.ready_t = t + .04 * len(anchors)
        else:
            self.refresh_job.future = gpu.submit(resegment, *args)
        self.refresh_stats["jobs"] += 1

    def _refresh_collect(self, t: float) -> None:
        job = self.refresh_job
        if job is None or not job.future.done() or t < job.ready_t:
            return
        self.refresh_job = None
        try:
            results, duration, backend = job.future.result()
            self.refresh_ms = duration if not self.refresh_ms else .7 * self.refresh_ms + .3 * duration
            self.refresh_backend, self.refresh_error = backend, None
            budget_ms = 40. * len(job.poses) if self.t1_mode == "sim" else self.refresh_ms
            self.refresh_next = max(self.refresh_next, t + budget_ms / 1000 / .15)
        except Exception as exc:
            self.refresh_stats["errors"] += 1
            self.refresh_error = str(exc)
            self.refresh_next = max(self.refresh_next, t + 5.)
            log.exception("periodic segmentation failed")
            return
        if job.generation != self._generation or not self.refresh_enabled or t - job.t > 3.:
            return
        for oid, result in results.items():
            tr = self.tracks.get(oid)
            if tr is None:
                continue
            if result is None or tr.hand_frac > .35:
                self.refresh_stats["rejected"] += 1
                continue
            mask, confidence = result
            meas = measure_mask(mask)
            if meas is None:
                continue
            old = job.poses[oid]
            now = tr.kf.pose
            dls, dth = now[2] - old[2], now[3] - old[3]
            M = similarity_about(old[0], old[1], math.exp(dls), dth, now[0] - old[0], now[1] - old[1])
            shifted = warp_mask(mask, M)
            # 보정 마스크 중심도 비동기 작업 이후 움직임만큼 옮긴다.
            center = M @ np.array([meas.cx, meas.cy, 1.])
            ls = .5 * math.log(meas.area / tr.area0) + dls
            angle = old[3]
            if tr.elong0 > 1.3 and meas.angle_valid:
                angle += ((meas.angle - tr.angle0 - old[3] + 90) % 180 - 90)
            angle += dth
            tracking = tr.state == TrackState.TRACKING
            ratio = meas.area / max(tr.area0 * math.exp(2 * old[2]), 1.)
            complete = .8 <= ratio <= 1.25 and tr.hand_frac < .05
            size = tr.size0 * math.exp(now[2])
            moved = math.hypot(center[0] - now[0], center[1] - now[1]) > .35 * size
            if (confidence < (.7 if tracking else .85) or not .5 <= ratio <= 1.6
                    or tracking and (not complete or moved)):
                self.refresh_stats["rejected"] += 1
                continue
            if tracking:
                # 정상 추적은 관측으로 조금씩 보정한다. 부분 윤곽·쌍둥이 물체로 순간이동하지 않는다.
                accepted = tr.kf.update(pose_meas(float(center[0]), float(center[1]), ls, angle,
                                                 1. + .05 * size, sigma_ls=.03, sigma_th=3., name="refresh"))
                if not accepted:
                    self.refresh_stats["rejected"] += 1
                    continue
            else:
                tr.kf.reset_pose(float(center[0]), float(center[1]), ls if complete else now[2],
                                 angle if complete else now[3])
                tr.points = np.zeros((0, 2), np.float32)
                tr.state, tr.bad, tr.good, tr.t1_disagree = TrackState.TRACKING, 0, 0, 0
                tr.teleported = True
            tr.mask = shifted
            tr.conf, tr.t_seen = confidence, t
            # 최초 형태/색/TAM 기억은 보존. 신뢰할 수 있는 영상 관측의 기존 Tier1 갱신만 허용한다.
            self.refresh_stats["applied"] += 1

    def _t1_keep_refined(self, tr: ObjectTrack, r, job: _T1Job, pre: tuple[float, float, float, float]) -> None:
        """정밀 마스크 보관. 모델이 물체를 봤으면(가림 여부와 무관) 원본 해상도로 저장한다.

        마스크 시각의 포즈 = 보정 후 포즈 - (작업 이후 Tier 0 움직임). 이후 프레임은 이 포즈와 지금 포즈의 차이만큼
        마스크를 옮겨 쓴다. 그 사이 Tier 0 오차는 다음 Tier 1 결과(약 60ms 뒤)가 다시 끊어 준다."""
        from .tier1 import logits_to_mask

        if not (r.object_score > 0 and r.iou >= 0.5) or self._full_size is None:
            return
        mask = logits_to_mask(r.mask_logits, self._full_size)
        if mask.sum() < 20:
            return
        s = job.poses[tr.oid]
        delta = [pre[i] - s[i] for i in range(4)]
        post = tr.kf.pose
        tr.t1_mask = mask
        tr.t1_ref = tuple(post[i] - delta[i] for i in range(4))  # type: ignore[assignment]
        tr.t1_t = job.t

    def _refined(self, tr: ObjectTrack) -> RefinedMask | None:
        if tr.t1_mask is None or tr.t1_ref is None:
            return None
        k = tr.k
        cx, cy, ls, th = tr.kf.pose
        rx, ry, rls, rth = tr.t1_ref
        M = similarity_about(rx / k, ry / k, math.exp(ls - rls), th - rth, (cx - rx) / k, (cy - ry) / k)
        return RefinedMask(tr.t1_mask, M, max(0.0, tr.t - tr.t1_t))

    def _t1_fuse(self, tr: ObjectTrack, r, job: _T1Job) -> None:
        from .tier1 import logits_to_mask

        H, W = tr.mask.shape
        mask = logits_to_mask(r.mask_logits, (W, H))
        present = r.object_score > 0 and r.iou >= 0.4 and mask.sum() >= 6
        tr.debug["t1"] = f"{r.object_score:.1f}/{r.iou:.2f}/{r.motion_iou:.2f}"
        if not present:
            tr.t1_absent += 1
            tr.t1_vis = 0.0
            # 모델이 "없다"고 하고 Tier 0 의 색 근거도 약하면 가림으로 본다
            if tr.state == TrackState.TRACKING and tr.t1_absent >= 2 and tr.region_conf < 0.3:
                tr.state, tr.good = TrackState.OCCLUDED, 0
            return
        tr.t1_absent = 0
        meas = measure_mask(mask)
        if meas is None:
            return
        cx_s, cy_s, ls_s, th_s = job.poses[tr.oid]
        cx_n, cy_n, ls_n, th_n = tr.kf.pose
        dx, dy, dls, dth = cx_n - cx_s, cy_n - cy_s, ls_n - ls_s, th_n - th_s  # 작업 이후 Tier 0 움직임
        expected = tr.area0 * math.exp(2 * ls_s)
        vis = meas.area / max(expected, 1.0)
        tr.t1_vis = vis
        # 모델 마스크는 가리는 손을 이미 뺀다 → 예상보다 크면 가림이 아니라 크기가 커진 것 (당김).
        # 예상보다 많이 작으면 가림일 수 있으므로 크기는 쓰지 않는다.
        complete = vis > 0.75 and (vis < 1.35 or r.iou >= 0.7)
        # 모양 기반 전체 포즈 (온전히 보일 때) 또는 위치만 (일부만 보일 때)
        ls_m = 0.5 * math.log(meas.area / tr.area0) if complete else None
        th_m = None
        if complete and tr.elong0 > 1.3 and meas.angle_valid:
            d = (meas.angle - tr.angle0) - th_s
            th_m = th_s + ((d + 90) % 180 - 90)
        size = tr.size0 * math.exp(ls_n)
        # Tier 0 가 그 시각에 믿던 위치와 모델 마스크가 얼마나 겹치나
        sub_box = self._corners_box(tr, (cx_s, cy_s, ls_s, th_s))
        agree = _iou(meas.box, sub_box)
        strong = r.iou >= 0.7 and r.object_score > 1.0 and vis >= 0.5
        shifted = warp_mask(mask, np.array([[1, 0, dx], [0, 1, dy]], np.float64))
        if tr.state != TrackState.TRACKING or agree < 0.3:
            # 불일치: 모델이 확실하면 모델을 믿는다 (추적 중이면 두 번 연속일 때만)
            if not strong:
                return
            # 단, 모델이 가리키는 곳이 기억한 방해물(같은 색 다른 물체)이면 옮기지 않는다
            if self._near_distractor(tr, (meas.cx + dx, meas.cy + dy), 0.6 * size):
                return
            if tr.state == TrackState.TRACKING:
                tr.t1_disagree += 1
                if tr.t1_disagree < 2:
                    return
            ls_new = ls_m + dls if ls_m is not None else tr.kf.x[2]
            th_new = th_m + dth if th_m is not None else tr.kf.x[3]
            if complete:
                cx_new, cy_new = meas.cx + dx, meas.cy + dy
            else:  # 일부만 보이면 보이는 부분이 전체 안에 들도록 가까운 쪽으로만 옮긴다
                cx_new, cy_new = meas.cx + dx, meas.cy + dy
            tr.kf.reset_pose(cx_new, cy_new, ls_new, th_new)
            tr.teleported = True
            tr.state, tr.bad, tr.good, tr.t1_disagree = TrackState.TRACKING, 0, 0, 0
            tr.mask = shifted
            tr.points = np.zeros((0, 2), np.float32)
            tr.t_seen = self.t_prev or tr.t
            self.t1_stats["resets"] += 1
            return
        tr.t1_disagree = 0
        # 모델 마스크는 128×128 격자라 작업 해상도에서 칸 하나가 약 4~5px. 중심·크기 잡음을 현실적으로 잡는다.
        cell = max(W, H) / 128.0
        sig = self.cfg.t1_sigma_k * (0.5 * cell + 0.03 * size) * (1.0 if complete else 4.0) / max(0.5, r.iou)
        sig_ls = 0.02 + 0.6 * cell / max(size, 1.0)
        tr.kf.update(pose_meas(meas.cx + dx, meas.cy + dy,
                               None if ls_m is None else ls_m + dls, None if th_m is None else th_m + dth,
                               sig, sigma_ls=sig_ls, sigma_th=3.0, name="t1"), gate=False)
        tr.mask = shifted
        tr.since_sample = self.cfg.resample_every  # 다음 프레임에 점을 새 마스크에서 다시 뿌린다
        self.t1_stats["applied"] += 1
        # 확실하고 온전히 보일 때만 물체 색·주변 색을 배운다 (신뢰 출처)
        if complete and r.iou >= 0.75 and r.object_score > 2 and 0.85 < vis < 1.2 and r.motion_iou >= 0.5:
            ring = ring_mask(mask, int(size * 0.4))
            tr.color.fit(job.idx, mask, ring, rate_fg=self.cfg.fg_rate, rate_bg=0.1)

    def _corners_box(self, tr: ObjectTrack, pose) -> tuple[float, float, float, float]:
        cx, cy, ls, th = pose
        a = math.radians(th)
        R = math.exp(ls) * np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        c = tr.box_rel @ R.T + np.array([cx, cy])
        return float(c[:, 0].min()), float(c[:, 1].min()), float(c[:, 0].max()), float(c[:, 1].max())

    # ---------------------------------------------------------------- 모양 기억 재획득
    def _reacq_submit(self, small: np.ndarray, idx: np.ndarray, t: float) -> None:
        """놓친 물체 하나를 골라 화면 전체 탐색을 GPU 스레드에 맡긴다 (한 번에 하나, 프레임 스레드는 복사만 한다)."""
        rc = self.cfg.reacq
        if self.tam is None or self._reacq_jobs or not self.tracks:
            return
        from .segment import ModelSegmenter, default_segmenter
        seg = default_segmenter()
        if not isinstance(seg, ModelSegmenter):
            return
        lost = [tr for tr in self.tracks.values()
                if tr.state in (TrackState.OCCLUDED, TrackState.LOST) and tr.shape is not None
                and t >= tr.reacq_next and tr.hand_frac < 0.3]
        if not lost:
            return
        tr = min(lost, key=lambda o: o.reacq_next)  # 가장 오래 기다린 물체부터
        tr.reacq_next = t + rc.period_s
        # 다른 추적 중인 물체의 영역 (그 물체로 옮겨붙지 않게)
        exclude = [o.mask.copy() for o in self.tracks.values()
                   if o is not tr and o.state == TrackState.TRACKING and o.mask.any()]
        args = (small.copy(), idx, tr.color.table.copy(), tr.shape, math.exp(float(tr.kf.x[2])),
                0.5 * (tr.p_in0 + tr.p_out0), rc, exclude)
        job: dict = {"oid": tr.oid, "tr": tr, "t": t, "frame": args[0], "generation": self._generation}

        def run(frame, idx_, table, mem, scale, thr, cfg, excl):  # type: ignore[no-untyped-def]
            def segment(f, box):  # type: ignore[no-untyped-def]
                r = seg._segment(f, box, None)
                return r.masks, r.scores
            return reacq_search(frame, idx_, table[idx_], mem, scale, thr, cfg, segment, excl)

        from . import gpu
        if self.t1_mode == "async":
            job["future"] = gpu.submit(run, *args)
        else:
            import time as _time
            s = _time.perf_counter()
            try:
                job["result"] = gpu.run(run, *args)
            except Exception:
                job["result"] = None
                log.exception("shape reacquisition failed")
            self.offloaded_ms += (_time.perf_counter() - s) * 1000
            job["ready"] = t + rc.sim_ms / 1000
        self._reacq_jobs.append(job)
        self.t1_stats["reacq"] += 1

    def _reacq_collect(self, t: float) -> None:
        keep = []
        for job in self._reacq_jobs:
            fut = job.get("future")
            if fut is not None:
                if not fut.done():
                    keep.append(job)
                    continue
                try:
                    job["result"] = fut.result()
                except Exception:
                    job["result"] = None
                    log.exception("shape reacquisition failed")
            elif t < job["ready"]:
                keep.append(job)
                continue
            if job["generation"] != self._generation:
                continue  # 정지·소스 변경 전 결과는 쓰지 않는다
            tr = self.tracks.get(job["oid"])
            if tr is job["tr"]:
                self._reacq_fuse(tr, job)
        self._reacq_jobs = keep

    def _reacq_fuse(self, tr: ObjectTrack, job: dict) -> None:
        """합격하고 닮은 후보와 헷갈리지 않으며 같은 곳에서 연속 확인되면 그 마스크로 복구한다.
        그 사이 이미 다시 추적 중이면(다른 경로로 복구) 아무것도 바꾸지 않는다."""
        res = job.get("result")
        if tr.state == TrackState.TRACKING:
            tr.reacq_hit, tr.reacq_hits = None, 0
            return
        meas = None if res is None or res.ambiguous else measure_mask(res.mask)
        if meas is None:
            tr.reacq_hit, tr.reacq_hits = None, 0
            return
        size = math.sqrt(meas.area)
        if tr.reacq_hit is not None and math.hypot(meas.cx - tr.reacq_hit[0], meas.cy - tr.reacq_hit[1]) < 0.5 * size:
            tr.reacq_hits += 1
        else:
            tr.reacq_hits = 1
        tr.reacq_hit = (meas.cx, meas.cy)
        tr.debug["reacq"] = f"{res.score.iou:.2f}/{res.score.hu:.2f}/{res.score.color:.2f}x{tr.reacq_hits}"
        if tr.reacq_hits < self.cfg.reacq.confirm:
            tr.reacq_next = min(tr.reacq_next, job["t"] + 0.5 * self.cfg.reacq.period_s)  # 확인은 빨리
            return
        ls = 0.5 * math.log(meas.area / tr.area0)
        th = float(tr.kf.x[3])
        if tr.elong0 > 1.3 and meas.angle_valid:
            d = (meas.angle - tr.angle0) - th
            th += (d + 90) % 180 - 90
        tr.kf.reset_pose(meas.cx, meas.cy, ls, th)
        tr.teleported = True
        tr.points = np.zeros((0, 2), np.float32)
        tr.state, tr.bad, tr.good, tr.t1_disagree, tr.t1_absent = TrackState.TRACKING, 0, 0, 0, 0
        tr.mask = res.mask
        tr.since_sample = self.cfg.resample_every
        tr.t_seen = tr.t
        tr.reacq_hit, tr.reacq_hits = None, 0
        self.t1_stats["reacq_ok"] += 1
        if self.tam is not None:  # Tier 1 메모리를 찾은 마스크로 다시 고정
            from . import gpu
            if self.t1_mode == "async":
                gpu.submit(self.tam.reanchor, tr.oid, job["frame"], res.mask, job["t"])
            else:
                gpu.run(self.tam.reanchor, tr.oid, job["frame"], res.mask, job["t"])

    def close(self) -> None:
        """하네스·서버 종료 시 대기 중 작업을 기다린다 (GPU 스레드가 죽은 객체를 만지지 않게)."""
        futs = [j.future for j in [*self.t1_jobs, *([self.refresh_job] if self.refresh_job else [])]]
        futs += [j.get("future") for j in self._reacq_jobs]
        for f in futs:
            if f is not None:
                try:
                    f.result(timeout=2)  # type: ignore[attr-defined]
                except Exception:
                    pass
        self.t1_jobs.clear()
        self._reacq_jobs.clear()

    # ---------------------------------------------------------------- 한 물체
    def _step_one(self, tr: ObjectTrack, prev: np.ndarray, gray: np.ndarray, idx: np.ndarray, t: float) -> None:
        cfg = self.cfg
        dt = max(1e-3, t - tr.t) if tr.t else 1 / 30
        tr.t = t
        occluded = tr.state in (TrackState.OCCLUDED, TrackState.LOST, TrackState.SEARCHING)
        cx0, cy0, ls0, th0 = tr.kf.pose
        tr.kf.predict(dt, damping=4.0 if occluded else 0.0)
        cxp, cyp, lsp, thp = tr.kf.pose
        size = tr.size0 * math.exp(lsp)
        M_pred = similarity_about(cx0, cy0, math.exp(lsp - ls0), thp - th0, cxp - cx0, cyp - cy0)

        # 1) 점 추적 (보이는 동안만)
        motion = Motion(None, 0, 0, 0, np.zeros((0, 2), np.float32))
        # 가림 중에도 남은 점은 계속 따라간다 (손가락 사이로 보이는 부분이 움직임을 알려 준다)
        occ = self._occ
        hand_frac = 0.0
        if occ is not None:
            am = self._amodal_mask(tr)
            hand_frac = float((am & occ).sum() / max(am.sum(), 1))
        tr.hand_frac = hand_frac
        if len(tr.points) >= 4:
            guess = cv2.transform(tr.points.reshape(-1, 1, 2), M_pred).reshape(-1, 2)
            excl = occ if self._others is None else (self._others if occ is None else occ | self._others)
            if excl is not None:  # 손·다른 물체로 들어간 점은 그쪽을 따라가므로 뺀다
                H0, W0 = excl.shape
                gi = np.clip(guess.astype(int), 0, [W0 - 1, H0 - 1])
                keep = ~excl[gi[:, 1], gi[:, 0]]
                tr.points, guess = tr.points[keep], guess[keep]
        if len(tr.points) >= 4:
            motion = track_points(prev, gray, tr.points, guess, size)
        lk_ok = motion.M is not None and motion.inliers >= max(5, 0.2 * motion.sampled)
        lk_conf = 0.0
        sep = tr.disc0  # 등록 시점 국소 대비: 색이 이 물체를 주변과 구분해 주는가
        pts_obj = 1.0
        if lk_ok and len(motion.points):
            # 점이 정말 물체 위에 있는가. 두 가지 실패를 막는다.
            # - 배경 고착: 배경에 뿌려진 점이 "안 움직임"을 자신 있게 말함
            # - 가리는 것 추종: 손 위의 점이 손을 따라감
            # 물체 색 확률이 '물체에서 본 적 없는 색' 수준(UNSEEN_PROB)을 넘어야 물체 점으로 센다.
            # 색 대비가 큰 물체는 더 엄격하게 (배경색과도 구분되므로).
            H0, W0 = gray.shape
            xi = np.clip(motion.points[:, 0].astype(int), 0, W0 - 1)
            yi = np.clip(motion.points[:, 1].astype(int), 0, H0 - 1)
            thr = 0.4 if sep > 0.3 else UNSEEN_PROB + 0.1
            pts_obj = float((tr.color.prob(idx[yi, xi]) > thr).mean())
            if pts_obj < 0.35:
                lk_ok = False
        if lk_ok:
            s, ang = similarity_params(motion.M)  # type: ignore[arg-type]
            c = motion.M @ np.array([cx0, cy0, 1.0])  # type: ignore[operator]
            # 정지 판정 (zero-velocity update): 추정 잡음 수준 이하의 움직임은 0 으로 본다.
            # 그대로 쓰면 가만히 있어도 잡음이 매 프레임 쌓여 중심이 떠다닌다 (random walk).
            moved = math.hypot(c[0] - cx0, c[1] - cy0)
            if moved < cfg.still_px and abs(math.log(s)) < cfg.still_scale and abs(ang) < cfg.still_deg:
                c, s, ang = np.array([cx0, cy0]), 1.0, 0.0
                tr.still_frames += 1
            else:
                tr.still_frames = 0
            lk_conf = min(1.0, motion.inliers / 12) * min(1.0, motion.ratio / 0.6) * min(1.0, pts_obj / 0.7)
            sig = (0.6 + 2.5 * (1 - lk_conf)) * max(1.0, size / 100)
            # 점 추적은 "프레임 간 상대 이동"이므로 측정이 아니라 예측(프로세스)으로 쓴다.
            # 절대 측정처럼 넣으면 필터가 누적 드리프트를 과신해 Tier 1 의 절대 보정이 묻힌다.
            tr.kf.propagate(np.array([c[0], c[1], ls0 + math.log(s), th0 + ang]), dt,
                            np.array([sig, sig, 0.01 + 0.04 * (1 - lk_conf), 0.5 + 3 * (1 - lk_conf)]))

        # 1') 쥠 결합: 손이 물체를 크게 덮었는데 점 추적이 없으면, 물체 근처 손 영역 중심의 움직임으로 포즈를 옮긴다.
        # 물체를 쥔 손은 물체와 함께 움직인다 (강체 결합 가정). 불확실성은 점 추적보다 크게 둔다.
        coupled = False
        if occ is not None and hand_frac >= 0.3 and cfg.hand_coupling:
            kd0 = max(3, int(0.3 * size)) | 1
            near = cv2.dilate(self._amodal_mask(tr).astype(np.uint8), np.ones((kd0, kd0), np.uint8)).astype(bool) & occ
            ys_h, xs_h = np.nonzero(near)
            if xs_h.size > 20:
                hc = (float(xs_h.mean()), float(ys_h.mean()))
                if tr.hand_c is not None and not lk_ok and hand_frac >= 0.5:
                    dxh, dyh = hc[0] - tr.hand_c[0], hc[1] - tr.hand_c[1]
                    sg = 1.5 * max(1.0, size / 100)
                    tr.kf.propagate(np.array([cx0 + dxh, cy0 + dyh, ls0, th0]), dt, np.array([sg, sg, 0.03, 2.0]))
                    coupled = True
                tr.hand_c = hc
            else:
                tr.hand_c = None
        else:
            tr.hand_c = None

        # 2) 영역 모델 (ROI 안에서만)
        H, W = gray.shape
        cxq, cyq, lsq, thq = tr.kf.pose
        size_q = tr.size0 * math.exp(lsq)
        margin = size_q * (cfg.roi_margin + (1.5 if occluded else 0.0))
        corners = self._amodal_corners(tr)
        x1 = int(max(0, corners[:, 0].min() - margin)); x2 = int(min(W, corners[:, 0].max() + margin))
        y1 = int(max(0, corners[:, 1].min() - margin)); y2 = int(min(H, corners[:, 1].max() + margin))
        region_conf, vis_frac, agree = 0.0, 0.0, 0.0
        new_mask = np.zeros_like(tr.mask)
        if x2 - x1 > 4 and y2 - y1 > 4:
            # 형태 제약: 보이는 마스크는 등록 모양을 현재 포즈에 놓은 영역(+여유)을 넘을 수 없다.
            # 쥔 손·팔이 물체와 색이 비슷해도 마스크가 번지지 않는다 (물체는 대체로 강체).
            amodal = self._amodal_mask(tr)
            kd = max(3, int(size_q * cfg.shape_slack)) | 1
            allowed = cv2.dilate(amodal.astype(np.uint8), np.ones((kd, kd), np.uint8)).astype(bool)
            # 사전 = 등록 모양을 현재 포즈에 놓은 것 (amodal). 직전 마스크를 누적 워프하면 조금씩 깎여 줄어든다.
            # 보이는 마스크 = amodal 중 물체 색인 곳 → 가리는 것(물체에서 본 적 없는 색)이 빠진다.
            prior = amodal[y1:y2, x1:x2]
            prob = tr.color.prob(idx[y1:y2, x1:x2])
            w_color = 0.6 + 1.0 * tr.disc0
            if prior.sum() >= 6:
                m_roi, agree = refine_mask(prob, prior, size_q, ~allowed[y1:y2, x1:x2], w_color)
                new_mask[y1:y2, x1:x2] = m_roi
            if occ is not None:
                new_mask &= ~occ
            if self._others is not None:
                new_mask &= ~self._others
            meas = measure_mask(new_mask)
            expected = tr.area0 * math.exp(2 * lsq)
            if meas is not None:
                vis_frac = min(1.5, meas.area / max(expected, 1.0))
                # 판별력: 마스크 안 vs 주변 고리의 물체 확률 차이 (주변이 복잡해도 국소적으로 판단)
                m_roi = new_mask[y1:y2, x1:x2]
                ring = ring_mask(m_roi, int(size_q * 0.25)) & ~allowed[y1:y2, x1:x2]
                p_in = float(prob[m_roi].mean())
                p_out = float(prob[ring].mean()) if ring.any() else 0.5
                region_conf = float(np.clip((p_in - p_out) / 0.45, 0, 1)) * min(1.0, vis_frac / 0.6)
                complete = 0.75 < vis_frac < 1.35
                if complete and region_conf > 0.2:
                    # 온전히 보이는 물체의 마스크 중심은 매우 안정적이다(실측 0.1px). 점 추적의 누적 오차를
                    # 이 절대 측정으로 매 프레임 붙잡아 둔다.
                    ls_r = 0.5 * math.log(meas.area / tr.area0)
                    th_r = None
                    if tr.elong0 > 1.3 and meas.angle_valid:
                        d = (meas.angle - tr.angle0) - thq
                        d = (d + 90) % 180 - 90  # 180° 모호성: 예측에 가장 가까운 쪽
                        th_r = thq + d
                        tr.aspect = 0.8 * tr.aspect + 0.2 * (meas.elongation / tr.elong0)
                    # 가중치를 올리면 정지 떨림은 줄지만 손에 쥔 구간에서 정확도가 떨어진다(실측 0.978→0.884).
                    # 점 추적이 있을 때는 약하게 두고, 정지 떨림은 정지 판정(ZUPT)으로 해결한다.
                    sig = cfg.region_sigma * (1.0 + 6 * (1 - region_conf)) * max(1.0, size_q / 100) \
                        * (3.0 if lk_ok else 1.0)
                    tr.kf.update(pose_meas(meas.cx, meas.cy, ls_r, th_r, sig,
                                           sigma_ls=0.03 + 0.1 * (1 - region_conf) + (0.05 if lk_ok else 0),
                                           sigma_th=3 + 8 * (1 - region_conf), name="region"))
                elif region_conf > 0.2 and not lk_ok and not occluded:
                    # 일부만 보임: 위치만 약하게 (보이는 부분 중심은 전체 중심과 다를 수 있음)
                    tr.kf.update(pose_meas(meas.cx, meas.cy, None, None, 0.35 * size_q, name="region_partial"))

        # 3) 상태 기계
        # 두 신호 중 하나라도 확실하면 보인다 (영역이 조명·배경 때문에 약해도 점 추적이 받쳐 준다).
        # 단, 색으로 물체를 잘 구분할 수 있는데 예측 위치에 물체 색이 거의 없으면 점 추적도 믿지 않는다.
        contradiction = sep > 0.35 and region_conf < 0.08 and agree < 0.25
        if contradiction:
            lk_conf *= 0.3
        conf = max(lk_conf, region_conf)
        tr.conf = conf
        tr.region_conf = region_conf
        # 손이 덮은 만큼은 '안 보이는 게 정상' 이다: 보이는 비율은 손이 안 덮은 부분 기준으로 판단
        vis_ok = vis_frac >= cfg.vis_occluded * max(0.2, 1.0 - hand_frac)
        visible_now = (lk_conf >= 0.5) or (region_conf >= cfg.conf_track and vis_ok)
        grasped = hand_frac >= 0.5 and (coupled or lk_ok or region_conf > 0.2)
        if grasped and tr.state == TrackState.TRACKING:
            visible_now = True  # 쥔 채로 움직이는 중: 가림으로 넘기지 않는다 (재탐색이 엉뚱한 곳으로 옮기는 것 방지)

        # 3') 색 기반 재탐색: 확신이 없으면 넓은 범위에서 "예상 크기의 물체 색 덩어리"를 찾는다
        # 재탐색 결과는 "예측 위치 이동"일 뿐이고, 보인다는 판정은 다음 프레임 영역 검사가 한다.
        # 우연히 비슷한 색 덩어리로 옮겨 가지 않도록, 같은 곳에서 연속 2번 찾았을 때만 옮긴다.
        found = None
        want = (contradiction or tr.state in (TrackState.OCCLUDED, TrackState.LOST) or not visible_now) and not grasped
        if want and sep > 0.35:
            cand = self._color_search(tr, idx, size_q)
            prev_c = tr.debug.get("_cand")
            if cand is not None and prev_c is not None and \
                    math.hypot(cand[0] - prev_c[0], cand[1] - prev_c[1]) < 0.5 * size_q:
                found = cand
                tr.kf.reset_pose(found[0], found[1], tr.kf.x[2], tr.kf.x[3])
                tr.teleported = True
                tr.points = np.zeros((0, 2), np.float32)
            tr.debug["_cand"] = cand
        else:
            tr.debug["_cand"] = None
        if tr.state == TrackState.TRACKING:
            tr.bad = 0 if visible_now else tr.bad + 1
            if tr.bad >= cfg.frames_to_occlude:
                tr.state = TrackState.OCCLUDED
                tr.good = 0
        else:
            # 복구는 영역(색+형태) 검사로만: 점 추적은 가리는 것을 따라갈 수 있어 복구 근거로 쓰지 않는다
            recovered = found is None and region_conf > 0.3 and 0.4 < vis_frac < 1.6
            tr.good = tr.good + 1 if recovered else 0
            if tr.good >= cfg.frames_to_recover:
                tr.state, tr.bad = TrackState.TRACKING, 0
                tr.points = np.zeros((0, 2), np.float32)  # 새로 뿌린다
                meas = measure_mask(new_mask)
                if meas is not None and 0.75 < vis_frac < 1.35:  # 온전히 보이면 그 위치로 포즈를 맞춘다
                    tr.kf.reset_pose(meas.cx, meas.cy, tr.kf.x[2], tr.kf.x[3])
                tr.teleported = True
            elif tr.state == TrackState.OCCLUDED and t - tr.t_seen > cfg.occluded_to_lost_s:
                tr.state = TrackState.LOST

        if tr.state == TrackState.TRACKING:
            tr.t_seen = t
            if new_mask.any():
                tr.mask = new_mask
            # 점 유지·재표본: 물체 마스크 안 + 물체 색인 곳만 (가리는 손 위의 점은 버린다)
            obj_color = tr.color.prob(idx) > (0.45 if sep > 0.3 else UNSEEN_PROB + 0.1)
            keep = motion.points
            if len(keep):
                xi = np.clip(keep[:, 0].astype(int), 0, W - 1); yi = np.clip(keep[:, 1].astype(int), 0, H - 1)
                keep = keep[tr.mask[yi, xi] & obj_color[yi, xi]]
            tr.since_sample += 1
            target = max(20, motion.sampled)
            if len(keep) < cfg.min_points_frac * target or tr.since_sample >= cfg.resample_every:
                fresh = sample_points(gray, tr.mask, ~obj_color)
                keep = fresh if len(keep) < 4 else np.concatenate([keep, fresh])[: max(len(fresh), 150)]
                tr.since_sample = 0
            tr.points = keep
            # 색 모델은 Tier 0 자기 출력으로 거의 배우지 않는다.
            # 포즈가 어긋난 채 배우면 물체를 배경으로, 배경을 물체로 학습해 어긋남이 굳어진다 (실측된 실패).
            # 가리는 손은 "물체에서 본 적 없는 색" 이라 배경 학습 없이도 이미 제외된다.
            # 배경은 색으로 물체가 확실히 확인될 때만 아주 천천히, 물체 색은 신뢰 출처(등록·Tier 1)만.
            if region_conf > 0.6 and pts_obj > 0.7 and 0.8 < vis_frac < 1.25:
                r = ring_mask(tr.mask, int(size_q * 0.4)) & ~self._amodal_mask(tr)
                tr.color.fit(idx, None, r, rate_bg=cfg.bg_rate)
            # 방해물 기억: 확실히 추적 중일 때 몇 프레임마다 화면 전체의 같은 색 덩어리를 본다
            tr.since_scan = getattr(tr, "since_scan", 0) + 1
            if cfg.distractor_every > 0 and sep > 0.35 and region_conf > 0.4 and tr.since_scan >= cfg.distractor_every:
                tr.since_scan = 0
                self._scan_distractors(tr, idx, size_q)
        tr.debug = {"_cand": tr.debug.get("_cand"), "t1": tr.debug.get("t1", ""),
                    "t1_vis": None if tr.t1_vis is None else round(tr.t1_vis, 3),
                    "sep": round(sep, 3), "pts_obj": round(pts_obj, 3), "found": found is not None,
                    "lk_inl": motion.inliers, "lk_conf": round(lk_conf, 3), "region_conf": round(region_conf, 3),
                    "vis_frac": round(vis_frac, 3), "agree": round(agree, 3), "pts": len(tr.points)}

    # ---------------------------------------------------------------- 재탐색
    def _color_search(self, tr: ObjectTrack, idx: np.ndarray, size_q: float) -> tuple[float, float] | None:
        """예측 위치 주변(물체 크기의 4배, 놓친 지 오래면 전체)에서 물체 색 덩어리를 찾는다.

        조건: 면적이 예상의 0.3~2.5 배, 덩어리 안 물체 확률이 주변보다 확실히 높음.
        여러 개면 예측 위치에 가까운 것. 반환: 작업 해상도 중심 또는 None.
        """
        cands = self._color_blobs(tr, idx, tr.state == TrackState.LOST)
        cx, cy = tr.kf.x[0], tr.kf.x[1]
        # 방해물(같은 색의 다른 덩어리)로 기억하는 곳 근처는 후보에서 뺀다
        cands = [c for c in cands if not self._near_distractor(tr, c, 0.6 * size_q)]
        if not cands:
            return None
        return min(cands, key=lambda c: (c[0] - cx) ** 2 + (c[1] - cy) ** 2)

    def _near_distractor(self, tr: ObjectTrack, p: tuple[float, float], r: float) -> bool:
        return any(math.hypot(p[0] - d[0], p[1] - d[1]) < r for d in self._distractor_pos(tr))

    def _distractor_pos(self, tr: ObjectTrack) -> list[tuple[float, float]]:
        """방해물 예측 위치 (마지막 관측 + 속도·경과시간). 다른 추적 물체의 현재 위치도 방해물로 본다."""
        out = [(d["x"] + d["vx"] * (tr.t - d["t"]), d["y"] + d["vy"] * (tr.t - d["t"])) for d in tr.distractors]
        out += [(o.kf.x[0], o.kf.x[1]) for o in self.tracks.values() if o is not tr and o.state.visible]
        return out

    def _scan_distractors(self, tr: ObjectTrack, idx: np.ndarray, size_q: float) -> None:
        """추적이 확실할 때 화면 전체에서 같은 색 덩어리를 찾아 방해물로 기억한다 (DAM4SAM 의 방해물 메모리 아이디어).
        나중에 물체와 방해물이 겹쳤다 갈라질 때, 방해물 쪽으로 옮겨붙지 않게 하는 데 쓴다."""
        cx, cy = tr.kf.x[0], tr.kf.x[1]
        blobs = [b for b in self._color_blobs(tr, idx, True) if math.hypot(b[0] - cx, b[1] - cy) > 1.2 * size_q]
        seen = set()
        for b in blobs:
            best, bd = None, 1.0 * size_q
            for k, d in enumerate(tr.distractors):
                px, py = d["x"] + d["vx"] * (tr.t - d["t"]), d["y"] + d["vy"] * (tr.t - d["t"])
                dd = math.hypot(b[0] - px, b[1] - py)
                if dd < bd and k not in seen:
                    best, bd = k, dd
            if best is None:
                tr.distractors.append({"x": b[0], "y": b[1], "vx": 0.0, "vy": 0.0, "t": tr.t, "miss": 0})
                seen.add(len(tr.distractors) - 1)
            else:
                d = tr.distractors[best]
                dt = max(1e-3, tr.t - d["t"])
                d["vx"] = 0.5 * d["vx"] + 0.5 * (b[0] - d["x"]) / dt
                d["vy"] = 0.5 * d["vy"] + 0.5 * (b[1] - d["y"]) / dt
                d.update(x=b[0], y=b[1], t=tr.t, miss=0)
                seen.add(best)
        for k, d in enumerate(tr.distractors):
            if k not in seen:
                d["miss"] += 1
        tr.distractors = [d for d in tr.distractors if d["miss"] <= 6][:4]

    def _color_blobs(self, tr: ObjectTrack, idx: np.ndarray, global_: bool) -> list[tuple[float, float]]:
        """예측 위치 주변(물체 크기 4배, global_ 이면 전체)의 '예상 크기의 물체 색 덩어리' 중심들."""
        H, W = idx.shape
        cx, cy = tr.kf.x[0], tr.kf.x[1]
        size_q = tr.size0 * math.exp(tr.kf.x[2])
        r = max(W, H) if global_ else size_q * 4
        x1, x2 = int(max(0, cx - r)), int(min(W, cx + r))
        y1, y2 = int(max(0, cy - r)), int(min(H, cy + r))
        if x2 - x1 < 8 or y2 - y1 < 8:
            return []
        step = 2  # 절반 해상도로 충분
        prob = tr.color.prob(idx[y1:y2:step, x1:x2:step])
        # 임계값은 이 물체의 등록 시 안/밖 확률 중간 (물체마다 색 구분력이 다르므로 고정값을 쓰지 않는다)
        thr = 0.5 * (tr.p_in0 + tr.p_out0)
        m = (cv2.GaussianBlur(prob, (5, 5), 0) > thr).astype(np.uint8)
        k = max(3, int(math.sqrt(tr.area0 * math.exp(2 * tr.kf.x[2])) / step * 0.08)) | 1
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
        n, lab, stats, cents = cv2.connectedComponentsWithStats(m, connectivity=8)
        expected = tr.area0 * math.exp(2 * tr.kf.x[2]) / (step * step)
        out = []
        for i in range(1, n):
            a = stats[i, cv2.CC_STAT_AREA]
            if not 0.4 * expected <= a <= 2.0 * expected:
                continue
            comp = lab == i
            ring = ring_mask(comp, max(3, int(math.sqrt(a) * 0.3)))
            if not ring.any() or prob[comp].mean() - prob[ring].mean() < 0.6 * tr.disc0:
                continue
            out.append((float(x1 + cents[i][0] * step), float(y1 + cents[i][1] * step)))
        return out

    # ---------------------------------------------------------------- 기하
    def _amodal_corners(self, tr: ObjectTrack) -> np.ndarray:
        cx, cy, ls, th = tr.kf.pose
        a = math.radians(th)
        R = math.exp(ls) * np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        return tr.box_rel @ R.T + np.array([cx, cy])

    def _amodal_mask(self, tr: ObjectTrack) -> np.ndarray:
        cx, cy, ls, th = tr.kf.pose
        M = similarity_about(tr.c0[0], tr.c0[1], math.exp(ls), th, cx - tr.c0[0], cy - tr.c0[1])
        return warp_mask(tr.template, M)

    def _output(self, tr: ObjectTrack) -> TrackOutput:
        k = tr.k
        cx, cy, ls, th = tr.kf.pose
        corners = self._amodal_corners(tr) / k
        amodal_box: Box = (float(corners[:, 0].min()), float(corners[:, 1].min()),
                           float(corners[:, 0].max()), float(corners[:, 1].max()))
        raw = (cx / k, cy / k, ls, th, tr.aspect)
        reanchored = tr.teleported
        if self.cfg.smooth:
            if tr.teleported:  # 순간이동(재검출·재정렬)은 미끄러지듯 따라가지 않고 바로 옮긴다
                tr.smoother.reset()
                tr.teleported = False
            scx, scy, sls, sth, sasp = tr.smoother(*raw, tr.size0 / k * math.exp(ls), tr.t)
        else:
            scx, scy, sls, sth, sasp = raw
            tr.teleported = False
        pose = Pose(scx, scy, math.exp(sls), sth, sasp)
        dbg = dict(tr.debug, reanchored=reanchored, amodal_box=amodal_box, raw_cx=round(raw[0], 2), raw_cy=round(raw[1], 2),
                   hand_frac=round(tr.hand_frac, 3))
        if not tr.state.visible:
            return TrackOutput(tr.state, None, pose, None, tr.conf, dbg)
        state = TrackState.GRASPED if tr.state == TrackState.TRACKING and tr.hand_frac >= 0.5 else tr.state
        mask_small = tr.mask
        box_s = mask_to_box(mask_small)
        box = None if box_s is None else tuple(v / k for v in box_s)
        full = None
        if self._full_size is not None:
            full = cv2.resize(mask_small.astype(np.uint8), self._full_size, interpolation=cv2.INTER_NEAREST).astype(bool)
        refined = self._refined(tr) if tr.kind == "pen" else None
        return TrackOutput(state, box, pose, full, tr.conf, dbg, refined)  # type: ignore[arg-type]

    _full_size: tuple[int, int] | None = None


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0
