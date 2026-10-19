# 멈춘 물체 흔들림·드리프트 벤치

물체가 가만히 있어도 커서가 흔들리고 혼자 흘러가는 문제를 재는 벤치다.

    PYTHONPATH=backend/src:third_party/EfficientTAM backend/.venv/bin/python bench/still/run.py --variant baseline still_lock
    # --scene synthetic-still synthetic-move real-still, --csv out.csv (variant 하나일 때), --cfg '{"still_px": 0.5}'

variant: `baseline`(StillLock 끔 = 이전 동작), `still_lock`(기본), `no_refresh`, `tier0_only`.

## 원인
정지 물체인데 커서가 움직이는 원인은 추적 잡음이 아니라 **2초마다 도는 분할 갱신(refresh)이 물체 크기를 ~0.7% 바꾸는 것**이었다.
깊이 커서는 크기에 비례하므로 초당 24 px 가 움직이고 10초에 50 px 흘렀다. 평활을 세게 해도 지연만 늘고 이 드리프트는 사라지지 않는다.

## 해결: `tracking/still.py` 의 `StillLock`
LK 점이 10프레임 이상 조용하면 잠그고, 그동안 LK 증분을 쌓아 잡음을 넘을 때만 반영한다. 영역·T1·갱신 측정은 3번 연속 어긋남이 확인될 때까지 막고,
마스크는 다수결 값으로 고정한다. 움직임·손·상태 변화·순간이동·재개·점 소실이면 해제한다. 펜은 잠그지 않는다.
끄려면 `TrackerConfig.still.enabled=False` (`vi_nostill` 트래커).

## 결과 (최신 실행)
| 장면 | 지표 | baseline | still_lock |
|---|---|---|---|
| synthetic-still | 커서 경로 (px/s) | 24.2 | 0.37 |
| | 커서 드리프트 (px) | 50.6 | 3.5 |
| | 마스크 중심 표준편차 | 0.54 | 0 |
| | 자세 표준편차 | 0.356 | 0.010 |
| synthetic-move | 움직임 시작 지연 (프레임) | 5 | 4 |
| | 멈춤 후 꼬리 (px) | 3.6 | 2.6 |
| real-still (test.mov 0–24프레임) | 모든 지표 | 동일 | 동일 (잠금이 걸리지 않음) |

## 한계
- 합성 장면 중심의 검증이다. 실영상(test.mov)에서는 카메라를 손으로 들고 있어 잠금이 전체의 약 10% 구간(69/694 프레임)에만 걸렸다. 독립 Tier‑1 기준 중심 대비 평균 오차는 15.5 → 12.7 px.
- 느린 움직임은 잠금 중 ≥ 약 1 px 단위로 한 번에 반영된다(양자화).
- 비동기 Tier‑1 실시간 모드에서는 따로 검증하지 않았다. 합성 평가 모음(tune 50 시퀀스)은 변화 없음(3개 시퀀스만 ±0.002).
