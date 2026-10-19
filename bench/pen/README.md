# 펜 접촉·기록 벤치 (수평 카메라)

`independent_pen_algorithm_test/METHOD.md`의 방법(바닥 기하 `d = k·w − c`, σ 비례 문턱, 그림자 링, 히스테리시스 상태기계)을
AnyControl에 옮긴 `vision_input/pen_floor.py`를 기존 방식(`legacy`, `SurfaceModel`)과 같은 라벨로 비교한다.

## 실행

```bash
# 작업 폴더: anycontrol-web
export PYTHONPATH=backend/src:third_party/EfficientTAM
# 1) 트래커 캐시 (앱과 같은 경로: register_line → ViTracker, Tier 1 sim = 결정적). 처음 한 번, 수십 초
backend/.venv/bin/python bench/pen/track_cache.py bench/pen/configs/pen_test.json            # 60fps
backend/.venv/bin/python bench/pen/track_cache.py bench/pen/configs/pen_test.json --step 2   # 30fps (앱 카메라와 같음)
# 2) 접촉 판정 비교 (캐시를 PenTracker 에 재생). 결과 JSON: bench/pen/results/
backend/.venv/bin/python bench/pen/run.py bench/pen/configs/pen_test.json --step 2
backend/.venv/bin/python bench/pen/run.py bench/pen/configs/pen_test.json --step 2 --variant floor+all \
    --overlay bench/pen/results/pen_test_floor_s2.mp4 --csv /tmp/frames.csv
# 3) 설정 조합 탐색
backend/.venv/bin/python bench/pen/sweep.py bench/pen/configs/pen_test.json
# 4) 깊이 모델 비교 (모델 설치 후)
backend/.venv/bin/python bench/pen/depth_compare.py bench/pen/configs/pen_test_roll4.json --step 2
backend/.venv/bin/python bench/pen/depth_prior.py bench/pen/configs/pen_test_roll4.json --step 2
```

새 영상: `configs/<name>.json`에 영상 경로, 펜 등록 프레임과 펜촉·반대쪽 끝 두 점(1280 폭 기준 px), 라벨 경로를 적는다.
라벨 형식은 `labels/pen_test.json`과 같다(원본 영상 프레임 번호, 접촉 구간, 저신뢰 구간, 경계 무시 반경).

## 결과 (pen_test.mov, 라벨: 사람이 펜촉 확대 크롭으로 판정)

F1 = 프레임 단위, 경계 ±2프레임 제외. "저신뢰 제외"는 262–305(손 그림자 속 거의 수직인 펜) 제외.

| 방식 | 30fps F1 | 30fps F1 (저신뢰 제외) | 60fps F1 | 60fps F1 (저신뢰 제외) | 허위 구간 | 첫 획 터치다운 지연 (30fps) | pen.update p95 |
|---|---|---|---|---|---|---|---|
| legacy (기존 기본) | 0.649 | 0.708 | 0.816 | 0.784 | 0 | 놓침 | 2.1 ms |
| legacy + 그림자 보조 | 0.674 | 0.738 | 0.838 | 0.810 | 0 | 놓침 | 8.1 ms |
| floor (F + 상태기계) | 0.728 | 0.718 | 0.931 | 0.930 | 0 | +115f | 4.8 ms |
| + 그림자(진입 거부·접촉 증거) | 0.946 | 0.994 | 0.908 | 0.956 | 0 | +3f (50 ms) | 5.7 ms |
| + 모서리 추적(드리프트) | 0.948 | 0.996 | 0.908 | 0.956 | 0 | +3f | 6.0 ms |
| **floor+all** (+ 획 소급·끝 정리) | **0.948** | **0.996** | 0.908 | 0.956 | 0 | +3f, 획은 +1f부터 기록 | 6.0 ms |
| floor+all + 그림자로 이탈 허용 | 0.900 | 0.970 | 0.834 | 0.899 | 0 | | |
| floor+all + 서브픽셀 굵기 | 0.846 | 0.915 | 0.831 | 0.900 | 1 | | |

- legacy는 표본 90개가 모여야 책상 면을 맞추기 시작해서 첫 획(147–305)을 30fps에서 통째로 놓친다. floor는 그림자 'attached'가 바닥 모델을 부트스트랩해 50 ms 만에 잡는다.
- 남은 오류는 대부분 저신뢰 구간(손 그림자 속 수직 펜)과 232–253(떠 보이는 자세)이다. METHOD.md 6.3절의 한계와 같다.
- 객체 영속성(분할 탈락 중 유지)은 이 영상에서 트래커가 펜을 한 번도 놓치지 않아 효과가 측정되지 않았다. 단위 테스트(`test_pen_floor.py`)로만 검증했다.
- 그림자로 이탈을 허용하거나, 몸통 윤곽 서브픽셀 굵기, 굵기 분위수(`floor_width_pct`)를 낮추는 것은 이 영상에서 30fps나 60fps 중 한쪽이 나빠져 기본값에서 제외했다.
- `floor_horizon`(바닥 모델로 그리기 소실선 추정)은 접촉 판정에 영향이 없다. 그리기 좌표 정확도는 정답 좌표가 없어 검증하지 못했다.

## 결과 2: IMG_0002.MOV (30fps 원본, 실내 확산광)

라벨 `labels/img_0002.json`은 Kiro가 펜 색으로 찾은 펜촉 확대 크롭(2프레임 간격)을 보고 판정했다. 사람 검수 전이다.
흐림·애매 구간은 저신뢰로 표시했다. 펜 등록(120) 전 프레임은 채점하지 않는다.

| 방식 | F1 | 정밀도 | 재현율 | F1 (저신뢰 제외) | 허위 구간 | 획 수 (정답 9) |
|---|---|---|---|---|---|---|
| legacy | 0.785 | 0.921 | 0.685 | **0.821** | 1 | 9 (392–450이 4조각) |
| **floor+all (drift off, 현재 floor 기본)** | **0.785** | **0.938** | 0.675 | 0.777 | **0** | 5 |
| floor+all + 모서리 추적 | 0.645 | 0.970 | 0.483 | 0.659 | 0 | 8 |

- 등록 주의: 손가락이 펜 가운데를 쥐어 펜이 두 조각으로 보이면, 펜촉~반대쪽 끝 전체를 찍었을 때 위 조각이 선택된다. 그러면 legacy와 floor 모두 F1 0이다. 펜촉~손가락 아래 조각만 찍어야 한다(`configs/img_0002.json`).
- 모서리 추적은 피부·팔이 책상색과 비슷해 고정 카메라인데도 기준선이 약 56px 흔들렸다. 그래서 `floor_drift` 기본값을 `off`로 바꿨다(pen_test 영향은 0.002 이내).
- floor가 놓친 곳(392–450, 470–530)은 펜촉 링이 대부분 'gap'(직사광 판정이 켜짐)이다. 또 hover가 +0.4~0.8D로 읽힌다(손에 가린 굵기·흐림). 이 장면은 확산광이라 그림자 판정이 맞지 않는데도 이봉성 검사를 통과했다. 다음 개선 대상이다.

## 결과 3: 평면 바닥 모델 (좌우 롤 항) — `floor_roll` (기본 켬)
접촉 굵기를 `d = k·w + a·x − c`(x = 화면 가로 위치)로 맞춘다. a = 0 이면 이전의 '앞뒤 직선' 모델(`floor+all+noroll`)이다.
카메라가 좌우로 기운 영상은 pen_test 를 ±4° 돌려(`configs/pen_test_roll*.json`, `"rotate"`) 만들었다. 라벨은 같은 영상이라 그대로 쓴다.
| 영상 | fps | legacy | floor (롤 항 없음) | floor (평면, 현재) |
|---|---|---|---|---|
| pen_test (수평) | 30 / 60 | 0.649 / 0.816 | 0.946 / 0.908 | 0.946 / 0.908 (동일) |
| pen_test +4° | 30 / 60 | 0.624 / 0.785 | 0.875 / **0.944** | **0.906** / 0.920 |
| pen_test −4° | 30 / 60 | 0.649 / 0.787 | 0.938 / 0.962 | **0.963** / **0.981** |
| IMG_0002 | 30 | 0.785 | 0.785 | **0.813** |
- 수평 영상은 변하지 않고, 기운 영상은 대체로 좋아지지만 **+4° 60fps 에서는 평면이 오히려 낮다(0.944 → 0.920)**. 표본이 작은 한 영상의 회전본이라 롤 항이 항상 이득이라고 말할 수 없다.
  나쁜 경우를 막으려고 `|a|` 상한(`a_max_px`)과 약한 릿지 정규화를 두었고, 끄려면 `floor_roll=False`.
- 터치 3점 보정(자동 보정 `/api/auto-calibration/*` 적용 시 `apply_auto_calibration`)은 접촉 표본 ≥ 2개로 평면의 앵커를 준다. 자동 학습은 그대로 돈다.
## 개발자 도구
- 바닥 그라데이션 맵: 앱 개발자 모드(렌치) → 펜 패널의 [바닥 그라데이션 맵 보기]. `GET /api/objects/{id}/pen/floor-map` (PNG data URI `image`/`overlay`).
- 깊이 모델 비교(실험): 같은 화면의 [깊이 모델 비교]. Depth Anything V2 Small(Apple Core ML, Apache-2.0, 약 50MB)을 **사용자가 확인한 뒤에만** 내려받아
  `~/Library/Caches/AnyControl/depth`(`ANYCONTROL_DEPTH_DIR`)에 저장하고 SHA-256 을 확인한다. 접촉 판정에는 쓰지 않는다. 한 번에 24–80 ms.
  - 이유: 단안 깊이는 프레임마다 스케일·이동이 다른 상대값이라 펜 굵기(∝ 역깊이)와 직접 비교할 수 없다. 대신 '책상은 평면'이라는 사실로 평면 기울기만 비교한다.
  - 측정(`depth_compare.py`): 깊이 평면과 터치 평면의 상관 ≈ 1.0 이라 구분력은 약하다. 롤은 수평 1.3° vs 터치 3.9°, +4°: 4.8° vs 5.7°, −4°: −1.7° vs 2.4°.
    회전량 변화(Δ)는 깊이 3.5/3.0°, 터치 1.8/1.5° 라서 깊이 쪽이 회전을 더 크게 따라간다(터치 평면의 롤이 작게 학습되는 경향). 다만 절대 오프셋이 둘 다 있어 어느 쪽이 정답인지는 정답 롤이 없어 확정하지 못했다.
  - 실험(`depth_prior.py`): 깊이 롤로 a 를 고정(`a = −W·tan(roll)`)해도 F1 이 터치로 배운 평면과 똑같았다(수평/+4°/−4° 모두). 그래서 제품 경로에 넣지 않았다. (a = 0 보다는 +4°·−4° 에서 높다.)
## 기본 설정 변경: 깊이 모델 기울기 (`floor_depth_roll`, 기본 켬)
바닥 평면의 좌우 기울기 a 를 Depth Anything V2 Small 로 잰 카메라 롤(`a = −W·tan(roll)`)로 고정한다. 2초마다 백그라운드에서 재고,
5개 중 3개 이상이 2.5° 안에서 맞고 내점 비율이 0.55 이상일 때만 적용한다. 가중치가 없거나 끄면 터치로 배운 롤을 쓴다 (`floor+all+touchroll`).
벤치(`floor+all+depth`, 추론은 동기 실행)에서 적용 여부를 확인했다(pen_test_roll4: 롤 4.4° → a −97.6px).
**F1 은 터치 롤과 네 영상 모두 같다**(0.946 / 0.906 / 0.963 / 0.889). 즉 이 벤치로는 이득이 보이지 않고, 실제 사용에서의 체감은 별도 확인이 필요하다.
## 펜 뼈대 (`pen_skeleton.py`)
펜은 곧은 막대라는 점으로 마스크에서 직선을 다시 맞추고, 보이는 구간 사이의 틈(손에 쥔 부분)을 '가려진 구간'으로 표시한다.
끝이 가려진 경우는 **손의 증거가 있을 때만** 기억한 길이로 채운다: 손 가림 처리의 손 마스크, 또는 (반대쪽 끝에 한해) 피부색.
- 포즈 예측만으로 채우면 실제 영상(pen_test)에서 카메라 쪽으로 기울어 짧아 보이는 펜을 가려졌다고 착각해 펜촉을 책상 위로 늘렸다 → 제거.
- 피부색은 베이지색 책상과 비슷해(img_0002: F1 0.889 → 0.772) 펜촉 쪽 판정과 접촉 판정에는 쓰지 않는다. 표시용 뼈대에서 반대쪽 끝만 채운다.
- 펜촉이 가려진 판정은 손 마스크가 있을 때(손 가림 처리 켬)만 측정을 멈추고 뼈대의 펜촉으로 잇는다.
- 처음 온전히 보인 모습에서 양 끝 색을 기억해, 다시 나타났을 때 방향이 뒤집혔으면 바로잡는다 (두 끝 색이 Lab 14 이상 다를 때만).
- pen_test 뼈대 상태 분포(30fps 267프레임): seen 210, middle_hidden 16, tail_hidden 24(대부분 엄지에 가림), tip_hidden 8. 접촉 F1 은 변하지 않았다(0.946 / 0.889).
## 획 삐침 벤치 (`strokes.py`)
`bench/pen/strokes.py <config> [--set key=value …] [--png out.png]`: 재생해 만든 획(그리기 좌표)을 그림으로 저장하고 걸음 길이비로 삐침을 잰다.
`--set draw_project=false stroke_start_delay_s=0 stroke_end_trim_s=0 stroke_hover_gate=99` 가 이전 동작이다. 결과와 비용은 `HANDOFF.md` §9.5 참고.

## 기본값

(이 문단은 이력이다: 이후 기본값이 `floor` 로 바뀌었다. HANDOFF.md §9.2 참고.) `PenConfig.contact_method`의 기본값은 당시 `legacy`였다. floor는 접촉 정확도에서 legacy보다 모두 낫지만, 펜 처리 시간이 p95 기준 약 +4 ms 늘고 검증이 영상 1개뿐이다. 앱의 펜 패널에서 "바닥 기하 접촉 판정 (실험)"을 켜거나 `POST /api/objects/{id}/pen/config {"contact_method": "floor"}`로 바꿔 쓴다. 다른 조명·각도·펜·책상의 영상으로 재검증한 뒤 기본값 변경을 결정한다.

## 주의 (과적합)

- 임계값은 METHOD.md의 값을 펜 지름·σ·초·프레임 크기 비율로 옮긴 것이다. 그 위에 이 영상을 보며 다음을 정했다:
  - gap 2프레임 연속, gap 단독 이탈 금지, 모서리 게이트 2프레임
  - baseline 시상수 0.08 s, 최소 프레임 1
  - `table_like`의 Lab 한계(밝은 면 ±25°·채도 0.5배, 그림자 ±55°·C/L ≥ 0.4)
- 위 수치는 낙관적일 수 있다. 특히 `table_like`는 이 책상·조명의 표본으로 정했다. 무늬 있는 책상, 무채색 책상, 확산광에서 다시 확인해야 한다.
