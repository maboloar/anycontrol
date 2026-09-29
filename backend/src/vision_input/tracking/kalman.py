"""포즈 칼만 필터.

상태 x = [cx, cy, ls, th, vcx, vcy, vls, vth]
    cx, cy: 전체 물체 중심 (px, 작업 해상도가 아니라 원본 프레임 좌표)
    ls:     log(scale), 등록 크기 대비
    th:     회전 (도, 연속)
등속 모델 + 가속 잡음. 측정은 여러 출처(점 추적, 영역, 마스크 모델)가 각자 공분산을 들고 들어온다.
Mahalanobis 게이트로 튀는 측정을 버린다. 속도는 가림 중 서서히 0 으로 줄인다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

N = 8
IDX_POS = [0, 1, 2, 3]
# 카이제곱 4자유도 99.9% ≈ 18.5
GATE_CHI2 = 18.5


@dataclass
class Meas:
    z: np.ndarray            # (k,) 측정값
    H: np.ndarray            # (k, 8)
    R: np.ndarray            # (k, k)
    name: str = ""


def pose_meas(cx: float, cy: float, ls: float | None, th: float | None,
              sigma_px: float, sigma_ls: float = 0.05, sigma_th: float = 3.0, name: str = "") -> Meas:
    """위치(+선택적으로 크기·각도) 측정. None 인 성분은 관측하지 않는다."""
    rows, z, var = [0, 1], [cx, cy], [sigma_px**2, sigma_px**2]
    if ls is not None:
        rows.append(2); z.append(ls); var.append(sigma_ls**2)
    if th is not None:
        rows.append(3); z.append(th); var.append(sigma_th**2)
    H = np.zeros((len(rows), N))
    for i, r in enumerate(rows):
        H[i, r] = 1.0
    return Meas(np.array(z, float), H, np.diag(var), name)


class PoseKalman:
    def __init__(self, cx: float, cy: float, size_px: float, accel_px: float = 900.0,
                 accel_ls: float = 2.0, accel_th: float = 400.0) -> None:
        """accel_*: 가속 잡음 표준편차 (단위/s²). size_px 에 비례해 위치 잡음을 정한다."""
        self.x = np.zeros(N)
        self.x[:4] = [cx, cy, 0.0, 0.0]
        k = size_px / 100.0
        self.q = np.array([accel_px * k, accel_px * k, accel_ls, accel_th])
        self.P = np.diag([4.0, 4.0, 0.01, 4.0, (50 * k) ** 2, (50 * k) ** 2, 0.25, 100.0])
        self._P_prev_pos = self.P[:4, :4].copy()
        self.last_nis: dict[str, float] = {}

    def predict(self, dt: float, damping: float = 0.0) -> None:
        """dt 초 앞으로. damping>0 이면 속도를 exp(-damping·dt) 로 줄인다 (가림 중)."""
        dt = float(np.clip(dt, 1e-3, 0.5))
        F = np.eye(N)
        for i in range(4):
            F[i, i + 4] = dt
        if damping > 0:
            d = np.exp(-damping * dt)
            for i in range(4, 8):
                F[i, i] = d
        # 이산 백색 가속 잡음
        Q = np.zeros((N, N))
        for i in range(4):
            a2 = self.q[i] ** 2
            Q[i, i] = a2 * dt**4 / 4
            Q[i, i + 4] = Q[i + 4, i] = a2 * dt**3 / 2
            Q[i + 4, i + 4] = a2 * dt**2
        self._P_prev_pos = self.P[:4, :4].copy()
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q

    def update(self, m: Meas, gate: bool = True) -> bool:
        """측정을 반영한다. 게이트에 걸리면 False (상태 불변)."""
        y = m.z - m.H @ self.x
        S = m.H @ self.P @ m.H.T + m.R
        try:
            Si = np.linalg.inv(S)
        except np.linalg.LinAlgError:
            return False
        nis = float(y @ Si @ y)
        self.last_nis[m.name] = nis
        # 자유도에 맞춘 게이트 (k 성분): 4자유도 기준값을 비례 조정
        if gate and nis > GATE_CHI2 * len(y) / 4 + 4:
            return False
        K = self.P @ m.H.T @ Si
        self.x = self.x + K @ y
        I_KH = np.eye(N) - K @ m.H
        self.P = I_KH @ self.P @ I_KH.T + K @ m.R @ K.T  # Joseph form (수치 안정)
        self.P = 0.5 * (self.P + self.P.T)
        return True

    def propagate(self, pose: np.ndarray, dt: float, sigma: np.ndarray) -> None:
        """상대 이동 측정(점 추적)으로 예측을 대신한다.

        predict() 직후에 부른다: 등속 예측 대신 관측된 이동으로 위치를 옮기고, 그 이동의 불확실성만큼
        공분산을 키운다 (random walk). 속도는 관측된 이동으로 부드럽게 갱신한다.
        """
        prev = self.x[:4] - self.x[4:] * dt  # predict 이전 위치 (근사)
        v = (pose - prev) / max(dt, 1e-3)
        self.x[:4] = pose
        self.x[4:] = 0.6 * self.x[4:] + 0.4 * v
        # 등속 예측이 만든 위치 불확실성 대신 점 추적 불확실성 누적
        self.P[:4, :4] = self._P_prev_pos + np.diag(sigma**2)
        self.P[:4, 4:] = 0
        self.P[4:, :4] = 0

    def reset_pose(self, cx: float, cy: float, ls: float, th: float, keep_velocity: bool = False) -> None:
        self.x[:4] = [cx, cy, ls, th]
        if not keep_velocity:
            self.x[4:] = 0
        self.P[:4, :] = 0
        self.P[:, :4] = 0
        self.P[:4, :4] = np.diag([4.0, 4.0, 0.004, 4.0])

    @property
    def pose(self) -> tuple[float, float, float, float]:
        return float(self.x[0]), float(self.x[1]), float(self.x[2]), float(self.x[3])

    @property
    def velocity(self) -> tuple[float, float, float, float]:
        return float(self.x[4]), float(self.x[5]), float(self.x[6]), float(self.x[7])

    def pos_sigma(self) -> float:
        return float(np.sqrt(max(self.P[0, 0], self.P[1, 1])))
