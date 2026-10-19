import { getLang } from "./i18n";

/**
 * 백엔드가 보내는 한국어 안내·오류·경고를 영어 화면에서 번역한다.
 * 백엔드는 한국어 하나만 내보내고, 화면에 보여 줄 때 sv() 를 거친다. 모르는 문장은 그대로 둔다.
 */
const EXACT: Record<string, string> = {
  "가만히 두기": "Pause briefly",
  "좌우로 움직이기": "Sweep left and right",
  "앞뒤로 움직이기": "Sweep toward and away",
  "영상에서 위아래로 움직이기": "Sweep up and down in the video",
  "움직임이 작습니다. 지금 위치에서 한쪽으로 움직인 뒤 반대 방향으로 움직여 주세요.": "The movement is too small. Move one way from your current position, then reverse.",
  "한쪽으로 움직인 다음, 그 자리에서 반대 방향으로 움직여 잠깐 멈추세요.": "Move one way, then reverse from there and pause briefly.",
  "움직인 범위가 좁습니다. 위아래로 조금 더 넓게 움직여 주세요.": "The travel range is too small. Move a little farther up and down.",
  "반대 방향 움직임이 부족합니다. 현재 위치에서 반대쪽으로 조금 더 움직여 주세요.": "The reverse movement is too small. Move farther in the opposite direction from where you are.",
  "지금 위치에서 손을 영상 위쪽으로 움직여 잠깐 멈춘 뒤, 그 자리에서 아래쪽으로 움직여 멈추세요. 카메라와의 거리를 유지하고 중앙으로 돌아오지 않아도 됩니다.": "From your current position, move your hand up in the video, pause, then move down and pause. Keep the same distance from the camera; no return to the center is needed.",
  " 손가락은 집지 말고 편하게 펴세요.": " Keep your fingers relaxed, not pinched.",
  " 물체를 엄지·새끼손가락으로 잡고 검지·중지·약지는 든 채로 두세요.": " Hold the object with thumb and little finger; keep index, middle and ring fingers raised.",
  " 검지·중지·약지를 든 채로 두세요.": " Keep index, middle and ring fingers raised.",
  " 물체를 평소처럼 잡고 유지하세요.": " Hold the object naturally.",
  // 자동 보정: 단계 제목
  "떨림 확인": "Jitter check",
  "가까운 곳에서 접촉": "Touch near",
  "먼 곳에서 접촉": "Touch far",
  "다른 위치에서 접촉": "Touch elsewhere",
  "가까운 곳에서 떼기": "Lift near",
  "먼 곳에서 떼기": "Lift far",
  "검지 접촉 확인": "Index touch check",
  "검지 떼기 확인": "Index lift check",
  "오른쪽 이동": "Move right",
  "왼쪽 이동": "Move left",
  "가까워지는 이동": "Move closer",
  "멀어지는 이동": "Move away",
  "펜 클릭·놓기 확인": "Pen click & release",
  "왼쪽 클릭·놓기 확인": "Left click & release",
  "오른쪽 클릭·놓기 확인": "Right click & release",
  "스크롤 확인": "Scroll check",
  "물체 위 검지 들기": "Lift index off object",
  "물체 위 검지 대기": "Rest index on object",
  "물체 검지 탭 확인": "Index tap on object",
  "작은 이동·복귀 확인": "Small move & return",
  // 자동 보정: 단계 안내
  "펜을 평소 기울기로 가까운 책상 면에 대고 유지하세요.": "Hold the pen at its usual tilt on the near part of the desk.",
  "같은 기울기로 먼 책상 면에 대고 유지하세요. 가까운 위치와 충분히 떨어져야 합니다.": "At the same tilt, hold it on the far part of the desk, well away from the near spot.",
  "중간 거리의 다른 좌우 위치에 펜을 대고 유지하세요.": "Hold the pen at a different left/right spot at mid distance.",
  "가까운 위치에서 기울기를 유지하고 펜촉을 2–3cm 들어 유지하세요.": "At the near spot, keep the tilt and hold the tip 2–3cm up.",
  "먼 위치에서도 같은 기울기로 펜촉을 2–3cm 들어 유지하세요.": "At the far spot, same tilt, hold the tip 2–3cm up.",
  "책상에 검지를 가볍게 대고 유지하세요.": "Rest your index finger lightly on the desk.",
  "같은 위치에서 검지를 책상에서 들어 유지하세요.": "At the same spot, hold your index finger up off the desk.",
  "중간 거리에서 펜촉을 책상에 댔다 떼세요. 눌렀다 놓기를 천천히 3번 반복하세요.": "At mid distance, touch the tip down and lift it. Slowly repeat 3 times.",
  "엄지와 검지 끝을 맞댔다 완전히 떼세요. 천천히 3번 반복하세요.": "Touch thumb and index tips, then fully release. Slowly repeat 3 times.",
  "엄지와 중지 끝을 맞댔다 완전히 떼세요. 검지는 중지에서 떨어뜨리고 천천히 3번 반복하세요.": "Touch thumb and middle tips, then fully release. Keep the index apart; slowly repeat 3 times.",
  "검지·중지만 펴고 약지·새끼를 접으세요. 측정 시작 후 잠깐 기다렸다가 아래로 스크롤할 동작으로 움직여 유지하세요.": "Extend index and middle, fold the others. After starting, wait a moment, then make a scroll-down motion and hold.",
  "물체를 쥔 상태에서 검지 끝을 물체에서 충분히 떨어뜨리고 유지하세요.": "While gripping the object, hold your index tip well off it.",
  "같은 물체 위에 검지 끝을 가볍게 대고 유지하세요.": "Rest your index tip lightly on the same object.",
  "물체를 쥔 채 검지를 들었다 내려놓기를 천천히 3번 반복하세요.": "While gripping, lift and lower your index finger slowly 3 times.",
  // 자동 보정: 피드백
  "작은 이동과 시작 위치 복귀를 확인했습니다. 그대로 유지하세요.": "Small move and return confirmed. Hold still.",
  "떨림이 안정적입니다. 움직이지 말고 유지하세요.": "Jitter is stable. Hold still.",
  "펜촉 외형을 수집하고 있습니다. 기울기를 유지하세요. 접촉 여부는 닿음/떼기 표본을 비교해 확인합니다.": "Collecting the tip's appearance. Keep the tilt; contact is judged by comparing touch and lift samples.",
  "사용자가 검사를 건너뛰었습니다.": "Check skipped.",
  "단계가 바뀌었습니다. 현재 안내를 확인하세요.": "The step changed. Check the current prompt.",
  "이전 단계로 이동할 수 없습니다.": "Can't go back to the previous step.",
  "오랫동안 진행하지 않아 보정을 종료했습니다. 기존 설정은 유지됩니다.": "Calibration ended after inactivity. Your settings are unchanged.",
  "대상이 보입니다. 안내 자세를 준비한 뒤 측정 시작을 누르세요.": "Target visible. Get into position, then press Start measuring.",
  "시작 위치를 읽고 있습니다. 잠깐 유지하세요.": "Reading the start position. Hold for a moment.",
  "검사를 마쳤습니다. 건너뛴 항목과 계산한 설정을 확인하세요.": "Checks finished. Review skipped items and the computed settings.",
  "모든 검사를 마쳤습니다. 계산한 설정을 확인하세요.": "All checks finished. Review the computed settings.",
  "대상을 인식하지 못했습니다. 손/물체 전체가 보이도록 자세를 조정하세요. 인식이 돌아오면 측정을 이어갑니다.": "Target not detected. Make the whole hand or object visible; measuring resumes when it's found.",
  "동작을 확인했습니다. 안내의 끝 자세를 유지하세요.": "Motion confirmed. Hold the end position.",
  "대상을 인식하며 관측을 수집하고 있습니다. 안내 자세를 유지하세요.": "Collecting samples. Hold the position.",
  "관측이 부족합니다. 카메라에 손/물체 전체가 보이도록 한 뒤 다시 측정하세요.": "Not enough samples. Make the whole hand or object visible and measure again.",
  "정지 중 움직임이 큽니다. 자세를 고정하고 다시 측정하세요.": "Too much movement while holding still. Steady yourself and measure again.",
  "좌우 이동이 너무 작습니다. 시작 후 기다렸다가 더 크게 움직이세요.": "Sideways movement too small. Wait after starting, then move farther.",
  "앞뒤 입력 변화가 작습니다. 같은 기울기를 유지하며 카메라 쪽/반대쪽으로 더 움직이세요.": "Too little forward/back change. Keep the tilt and move farther toward or away from the camera.",
  "가까워지기와 같은 방향입니다. 카메라에서 멀어지는 방향으로 움직이세요.": "Same direction as 'closer'. Move away from the camera.",
  "오른쪽 검사와 같은 방향입니다. 반대 방향으로 움직이세요.": "Same direction as the right check. Move the other way.",
  "클릭 후 완전히 놓기까지 2회 이상 필요합니다. 천천히 맞댔다 떼세요.": "Need at least 2 full click-and-release cycles. Touch and release slowly.",
  "접촉 때와 자세가 비슷합니다. 검지를 더 들어 올려 유지하세요.": "Pose looks like the touch pose. Lift your index finger higher.",
  "두 손가락 스크롤 자세와 이동이 필요합니다. 안내 자세로 다시 측정하세요.": "Needs the two-finger scroll pose and motion. Measure again in that pose.",
  "검지 접촉과 들기의 차이가 작습니다. 충분히 들었다 대거나 이 검사를 건너뛰세요.": "Touch and lift look too similar. Lift higher, or skip this check.",
  "검지를 충분히 들었다 대는 탭과 떼기 2회 이상이 필요합니다. 다시 측정하거나 건너뛰세요.": "Need at least 2 clear index taps. Measure again or skip.",
  "작은 사각형의 좌우·앞뒤 이동이 모두 필요합니다.": "The small square needs both sideways and forward/back movement.",
  "처음 위치로 돌아온 뒤 잠깐 유지하세요.": "Return to the start and hold briefly.",
  "검지 접촉과 떼기가 구분되지 않습니다. 들어 올리는 높이/카메라 각도를 바꾸고 다시 측정하세요.": "Can't tell index touch from lift. Change lift height or camera angle and measure again.",
  "접촉 자세가 허용 범위를 벗어납니다. 손가락 자세를 조정하세요.": "Touch pose is out of range. Adjust your finger.",
  "검지를 책상에 댄 상태가 충분히 확인되지 않았습니다. 접촉을 유지하고 다시 측정하세요.": "Index-on-desk wasn't confirmed. Keep contact and measure again.",
  "스크롤에는 검지와 중지를 모두 책상에 대야 합니다. 두 손가락을 대고 다시 측정하세요.": "Scrolling needs both index and middle on the desk. Measure again with both down.",
  "검지 접촉 위치와 좌우 움직임으로 책상 기준선을 생성했습니다.": "Created a desk baseline from index contact and sideways movement.",
  "실제로 접촉하며 이동한 범위를 책상 허용 영역으로 반영했습니다.": "Set the desk area from the range you actually covered while touching.",
  "좌우 두 검사에서 같은 방향이 관측됐습니다. 왼쪽 안내대로 다시 움직이세요.": "Both sideways checks went the same way. Redo the left move as shown.",
  "앞뒤 입력을 구분하기 어렵습니다. 같은 기울기에서 멀어지는 동작을 다시 측정하세요.": "Forward/back is hard to tell apart. Redo the move-away step at the same tilt.",
  "화면 XY 범위가 좁습니다. 앞뒤 이동을 더 크게 측정하세요.": "Screen XY range is narrow. Measure with larger forward/back movement.",
  "이동 검사 일부를 건너뛰어 이동 방향·감도·범위 설정은 기존 값을 유지합니다.": "Some movement checks were skipped, so direction, sensitivity and range stay as they were.",
  "집기와 놓기를 구분할 수 없습니다. 손가락 끝을 맞댔다 완전히 펴세요.": "Can't tell pinch from release. Touch fingertips, then open fully.",
  "집기와 놓기의 거리 차이가 작습니다. 손을 더 펴고 다시 측정하세요.": "Pinch and release are too close. Open your hand more and measure again.",
  "클릭 후 놓기까지 2회 이상 관측해야 합니다. 천천히 3번 반복하세요.": "Need at least 2 click-and-release cycles. Slowly repeat 3 times.",
  "오른쪽 클릭 때 검지도 붙어 있습니다. 검지를 중지에서 떨어뜨리세요.": "Index was touching during right click. Keep it apart from the middle finger.",
  "스크롤 입력의 이동 차이가 부족합니다. 안내 자세로 더 크게 움직이세요.": "Not enough scroll movement. Move farther in the scroll pose.",
  "물체 검지 탭과 떼기를 구분하기 어렵습니다. 충분히 들어 올려 다시 3번 탭하세요.": "Can't tell index tap from lift on the object. Lift higher and tap 3 times again.",
  "접촉 높이와 그리기 원근은 별개입니다. 원근은 기존 소실선/책상 4점 보정을 유지합니다.": "Contact height is separate from drawing perspective, which keeps the horizon / 4-point calibration.",
  "필요한 검사가 빠진 설정은 자동으로 변경하지 않습니다. 기존 설정과 수동 슬라이더를 유지합니다.": "Settings missing a required check aren't changed; current values and sliders are kept.",
  "이동·정지·작은 이동 후 복귀 및 안내된 클릭 검사를 완료했습니다.": "Completed movement, stillness, small move and return, and click checks.",
  "자동으로 변경할 설정이 없습니다. 기존 설정을 유지합니다.": "Nothing to change automatically. Settings are kept.",
  "Desk View에서 닿음과 떼기의 외형 차이가 작습니다. 펜을 더 높이 들거나 구도를 바꾸세요.": "In Desk View, touch and lift look too alike. Lift higher or change the framing.",
  "외형 변화가 커 접촉 판단이 불안정합니다. 같은 기울기로 다시 측정하세요.": "Appearance varies too much for reliable contact. Measure again at the same tilt.",
  "닿음·떼기의 검사 샘플이 겹칩니다. 높이를 충분히 나누어 다시 측정하세요.": "Touch and lift samples overlap. Separate the heights more and measure again.",
  "펜을 댔다 떼는 클릭 2회 이상이 필요합니다. 천천히 3번 반복하세요.": "Need at least 2 pen touch-and-lift clicks. Slowly repeat 3 times.",
  "가까운 곳과 먼 곳의 거리 차이가 부족하거나 책상 기울기를 구분할 수 없습니다.": "Near and far are too close, or the desk tilt can't be determined.",
  "펜 닿음·떼기의 높이 차이가 불명확합니다. 같은 기울기에서 더 충분히 들어 올리세요.": "Pen touch vs. lift height is unclear. Lift higher at the same tilt.",
  "접촉 문턱을 안전하게 나눌 수 없습니다. 펜을 더 높이 들어 측정하세요.": "Can't set a safe contact threshold. Lift the pen higher and measure.",
  // 파이프라인
  "소스가 바뀌어 보정을 종료했습니다.": "Calibration ended because the source changed.",
  "입력 방향이 바뀌어 보정을 종료했습니다.": "Calibration ended because the input direction changed.",
  "책상 보정이 바뀌었습니다. 새 구도에서 자동 보정을 다시 시작하세요.": "Desk calibration changed. Restart auto calibration for the new framing.",
  "책상 보정이 해제되어 자동 보정을 종료했습니다.": "Auto calibration ended because desk calibration was cleared.",
  "책상 기준선이 바뀌었습니다. 새 구도에서 자동 보정을 다시 시작하세요.": "Desk baseline changed. Restart auto calibration for the new framing.",
  "긴급 정지로 자동 보정을 종료했습니다.": "Auto calibration ended by emergency stop.",
  "영상이 정지되어 자동 보정을 종료했습니다. 재생한 뒤 다시 시작하세요.": "Auto calibration ended because the video paused. Play it and start again.",
  "손쉬운 사용 권한이 필요합니다": "Accessibility permission is required",
  "손쉬운 사용 권한이 없습니다": "No Accessibility permission",
  "손쉬운 사용 권한이 필요합니다. 권한 설정을 열어 허용하세요.": "Accessibility permission is required. Open the settings and allow it.",
  "영상을 켜고 재생한 뒤 실제 출력을 켜세요.": "Turn on and play the video before enabling real output.",
  "자동 보정을 마친 뒤 실제 출력을 켜세요.": "Finish auto calibration before enabling real output.",
  "아직 카메라 프레임이 없습니다": "No camera frame yet",
  "아직 카메라 프레임이 없습니다.": "No camera frame yet.",
  "자동 보정을 마치거나 취소한 뒤 수동 설정을 변경하세요.": "Finish or cancel auto calibration before changing settings manually.",
  "물체 마우스로 쓸 물체를 먼저 등록하고 선택하세요.": "Register and select an object for the object mouse first.",
  "손 인식 엔진이 없어 이 모드를 쓸 수 없습니다 (Apple Vision 또는 MediaPipe).": "No hand engine is available for this mode (Apple Vision or MediaPipe).",
  "손 인식 엔진이 없습니다 (Apple Vision: pyobjc-framework-Vision, MediaPipe: models/hand_landmarker.task).": "No hand engine available (Apple Vision: pyobjc-framework-Vision, MediaPipe: models/hand_landmarker.task).",
  "손 인식 모델이 없어 맨손 그리기를 켤 수 없습니다 (mediapipe, models/hand_landmarker.task).": "Hand drawing needs a hand model (mediapipe, models/hand_landmarker.task).",
  "손 인식 모델이 없어 켤 수 없습니다": "Can't turn on without a hand model",
  "분할 결과가 비어 있습니다. 물체를 다시 지정하세요.": "Segmentation came back empty. Select the object again.",
  "보정 중인 물체를 다시 선택했습니다. 자동 보정을 다시 시작하세요.": "The object being calibrated was reselected. Restart auto calibration.",
  "보정 중인 물체가 삭제되었습니다.": "The object being calibrated was deleted.",
  "이미 자동 보정 중입니다. 현재 보정을 마치거나 취소하세요.": "Auto calibration is already running. Finish or cancel it first.",
  "카메라/영상을 켜고 재생한 뒤 자동 보정을 시작하세요.": "Turn on and play the camera or video before starting auto calibration.",
  "올바른 보정 대상을 선택하세요.": "Choose a valid calibration target.",
  "보정할 펜/물체를 먼저 등록하고 화면에 보이도록 하세요.": "Register the pen or object first and keep it in view.",
  "펜을 마우스 대상으로 선택하거나 마우스를 끈 뒤 펜 보정을 시작하세요.": "Select the pen as the mouse target, or turn the mouse off, before pen calibration.",
  "손 인식 모델이 필요합니다. 물체 이동만 보정하려면 손 클릭을 끄세요.": "A hand model is required. Turn off hand clicks to calibrate object movement only.",
  "자동 보정이 종료되었거나 바뀌었습니다. 현재 상태를 확인하세요.": "Auto calibration ended or changed. Check the current state.",
  "모든 검사를 완료해야 설정을 적용할 수 있습니다.": "Finish all checks before applying settings.",
  "마우스 대상이 바뀌었습니다. 대상에 맞게 보정을 다시 시작하세요.": "The mouse target changed. Restart calibration for it.",
  "보정한 펜이 삭제되었습니다.": "The calibrated pen was deleted.",
  "물체 추적이 불안정합니다. 등록한 대상을 가리지 말고 화면 안에 유지하세요.": "Object tracking is unstable. Keep the object uncovered and in view.",
  "손을 인식하지 못했습니다. 손바닥과 손가락 전체를 카메라에 보여 주세요.": "Hand not detected. Show your whole palm and fingers to the camera.",
  "손을 안정적으로 찾지 못했습니다. 손바닥 방향과 밝기를 조정하세요.": "Hand detection is unsteady. Adjust palm orientation and lighting.",
  "펜촉이 잘 보이지 않습니다. 펜 전체와 끝이 보이도록 구도와 조명을 조정하세요.": "Pen tip is hard to see. Adjust framing and lighting so the whole pen shows.",
  "물체를 쥔 손과 검지 끝을 찾지 못했습니다. 구도를 바꿔 재검사하거나 이 검사를 건너뛰세요.": "Couldn't find the gripping hand and index tip. Change framing and retry, or skip this check.",
  // 카메라·Desk View
  "Desk View 설정 창은 macOS에서 사용할 수 있습니다": "Desk View setup is only available on macOS",
  "이 macOS 버전은 Desk View 설정 API를 지원하지 않습니다": "This macOS version doesn't support the Desk View setup API",
  "Desk View 설정 창 실행 시간이 초과되었습니다. 메뉴 막대의 비디오 메뉴에서 여세요.": "Desk View setup timed out. Open it from the Video menu in the menu bar.",
  "Desk View 설정 창 실행 시간이 초과되었습니다": "Desk View setup timed out",
  "Desk View 설정 창을 열 수 없습니다": "Couldn't open Desk View setup",
  "카메라가 연결되어 있지 않습니다. 장치 목록을 새로고침하세요.": "No camera connected. Refresh the device list.",
  "선택한 카메라의 Desk View가 없습니다. 지원되는 iPhone을 연결하세요.": "The selected camera has no Desk View. Connect a supported iPhone.",
  "Desk View와 연결된 일반 카메라를 찾을 수 없습니다.": "Couldn't find the regular camera paired with Desk View.",
  "Desk View는 macOS AVFoundation 환경에서 사용할 수 있습니다": "Desk View requires macOS AVFoundation",
  "Desk View 장치를 찾을 수 없습니다. iPhone 연결을 확인하세요.": "No Desk View device found. Check the iPhone connection.",
  "카메라를 선택한 상태에서만 전원을 조절할 수 있습니다": "Power can only be toggled for a camera source",
  "카메라는 일시정지·재생 또는 구도 적용을 사용하세요": "For cameras, use pause/play or Apply framing",
  "선택한 소스가 없습니다": "No source selected",
  "카메라 소스가 없습니다": "No camera source",
  "camera stopped delivering frames (연결 확인)": "Camera stopped delivering frames (check the connection)",
  // 책상 보정
  "책상 네 모서리가 필요합니다": "Four desk corners are required",
  "책상 좌표가 올바르지 않습니다": "Invalid desk coordinates",
  "책상 네 점이 한 줄에 너무 가깝습니다. 수평 기준선 2점을 사용하세요": "The four points are nearly in a line. Use a 2-point level baseline",
  "책상 기준선 두 점이 필요합니다": "Two baseline points are required",
  "책상 기준선 두 점을 더 멀리 찍어 주세요": "Place the two baseline points farther apart",
  "네 점이 너무 가깝거나 한 줄에 있습니다": "The four points are too close or in a line",
  // 매핑·프로필
  "range 는 [작은 값, 큰 값] 이어야 합니다": "range must be [smaller, larger]",
  "off 는 on 보다 클 수 없습니다": "off can't be greater than on",
  "매핑 id 가 겹칩니다": "Duplicate mapping id",
  "프로필 이름에 쓸 수 있는 글자가 없습니다": "The profile name has no usable characters",
  "잘못된 프로필 이름": "Invalid profile name",
  "학습을 먼저 시작하세요": "Start learning first",
  // 게임·물체
  "게임에 연결할 물체를 먼저 등록하세요.": "Register an object to connect to the game first.",
  "자동 보정을 마치거나 취소하세요.": "Finish or cancel auto calibration.",
  "box, point, line 중 하나만 주세요": "Provide exactly one of box, point or line",
  "좌표는 0..1 로 정규화해야 합니다": "Coordinates must be normalized to 0..1",
  "펜은 펜촉·반대쪽 끝 두 점을, 일반 물체는 박스나 한 점을 주세요.": "Give two points (tip, other end) for a pen, or a box or point for an object.",
  "분할 중 영상 소스가 바뀌었습니다. 새 영상에서 다시 선택하세요.": "The video source changed during segmentation. Select again in the new video.",
  "분할 중 물체가 삭제되었거나 영상 소스가 바뀌었습니다. 다시 선택하세요.": "The object was deleted or the source changed during segmentation. Select again.",
  "자동 보정을 마치거나 취소한 뒤 펜 설정을 변경하세요.": "Finish or cancel auto calibration before changing pen settings.",
  "펜으로 등록된 물체가 아닙니다.": "This object isn't registered as a pen.",
  "펜을 1초 동안 안정적으로 댄 뒤 다시 눌러 주세요.": "Hold the pen steadily on the desk for 1 second, then press again.",
  "보정하려면 가까운 곳과 먼 곳, 두 군데 이상에서 펜을 대고 눌러 주세요.": "To calibrate, touch the pen and press at two or more spots, near and far.",
  "Desk View에서 펜을 2–3cm 들고 1초 유지한 뒤 눌러 주세요.": "In Desk View, hold the pen 2–3cm up for 1 second, then press.",
  "수동 그리기 버튼은 Desk View 모드에서 사용합니다.": "Hold-to-draw is for Desk View mode.",
  "두 점이 너무 가깝습니다. 펜촉과 펜의 반대쪽 끝을 찍어 주세요.": "The two points are too close. Click the pen tip and the other end.",
  "펜을 찾지 못했습니다. 펜 위를 정확히 찍었는지 확인하세요.": "Pen not found. Make sure you clicked right on the pen.",
  "선택한 물체가 충분히 길쭉하지 않습니다. 손가락까지 잡혔을 수 있습니다.": "The selection isn't elongated enough; a finger may have been included.",
  "물체를 찾지 못했습니다. 물체 위를 다시 클릭하거나 드래그하세요.": "Object not found. Click or drag on the object again.",
  "마스크가 여러 조각이라 가장 큰 조각만 씁니다.": "The mask has several pieces; using the largest.",
  "물체가 너무 작게 보입니다. 카메라에 더 가까이 두세요.": "The object looks too small. Move it closer to the camera.",
  "선택 영역이 화면의 절반을 넘습니다. 배경까지 잡혔을 수 있으니 물체만 다시 선택하세요.": "The selection covers over half the frame and may include background. Select just the object.",
  "물체가 화면 가장자리에 걸려 있습니다. 중앙 쪽으로 옮기면 더 안정적입니다.": "The object touches the frame edge; it tracks better nearer the center.",
  "분할 신뢰도가 낮습니다. 경계를 확인하고 필요하면 다른 후보를 고르세요.": "Low segmentation confidence. Check the outline and try another candidate if needed.",
  "무늬도 적고 배경과 색도 비슷합니다. 손으로 가리면 추적이 약해질 수 있습니다.": "Little texture and similar color to the background; tracking may weaken when covered.",
  "선택한 영역이 너무 작습니다. 물체를 조금 더 크게 드래그하세요.": "The selection is too small. Drag a bit larger around the object.",
};

/** 자동 보정 안내 문장에 들어가는 대상·방향 */
const SUBJECT: Record<string, string> = { "펜촉": "the pen tip", "검지": "your index finger", "손바닥": "your palm", "물체": "the object" };
const DIRECTION: Record<string, string> = {
  "커서가 오른쪽으로 가야 하는 방향으로": "the way that should move the cursor right",
  "커서가 왼쪽으로 가야 하는 방향으로": "the way that should move the cursor left",
  "카메라 쪽으로": "toward the camera",
  "카메라에서 멀어지는 방향으로": "away from the camera",
};
/** 안내 끝에 붙는 덧붙임 */
const SUFFIX: [string, string][] = [
  [" 펜촉은 책상에 대고 움직이세요.", " Keep the tip on the desk while moving."],
  [" 검지는 책상에 대고 움직이세요.", " Keep your index finger on the desk while moving."],
  [" 검지는 책상에 둔 채 검사하세요.", " Keep your index finger on the desk during the check."],
  [" 두 손가락을 책상에 대세요.", " Put both fingers on the desk."],
];
const subj = (s: string) => SUBJECT[s] ?? s;
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

const PATTERNS: [RegExp, (...m: string[]) => string][] = [
  [/^(\S+)을 화면 중앙에서 움직이지 말고 유지하세요\. 손가락은 집지 말고 편하게 펴세요\.$/, (s) => `Hold ${subj(s!)} still at the center of the frame. Keep your fingers relaxed, not pinched.`],
  [/^중앙에서 준비하세요\. 측정 시작 후 0\.5초 기다렸다가 (\S+)을 (.+?) 10–15cm 움직이고 끝 위치를 유지하세요\.$/, (s, d) => `Start at the center. After starting, wait 0.5s, then move ${subj(s!)} ${DIRECTION[d!] ?? d} 10–15cm and hold the end position.`],
  [/^(\S+)으로 작은 사각형을 그리듯 좌우·앞뒤로 움직이고 처음 위치로 돌아오세요\.$/, (s) => `Trace a small square with ${subj(s!)}, moving sideways and forward/back, then return to the start.`],
  [/^클릭 후 놓기 (\d+)\/2회 이상 확인 · (.*)$/, (n, rest) => `Click & release ${n}/2+ confirmed · ${({ "손가락을 완전히 떼세요.": "Fully release your fingers.", "다시 맞댔다 떼세요.": "Touch and release again.", "좋습니다. 손가락을 편 상태로 유지하세요.": "Good. Keep your fingers open." } as Record<string, string>)[rest!] ?? rest}`],
  [/^검지 탭 후 떼기 (\d+)\/2회 이상 확인 · 충분히 들었다가 다시 대세요\.$/, (n) => `Index tap & lift ${n}/2+ confirmed · Lift well, then touch again.`],
  [/^건너뛴 검사: (.*)$/, (list) => `Skipped checks: ${list!.split(", ").map((x) => EXACT[x] ?? x).join(", ")}`],
  [/^방향: 좌우 (반전|유지) · 상하 (반전|유지)$/, (x, y) => `Direction: X ${x === "반전" ? "flipped" : "kept"} · Y ${y === "반전" ? "flipped" : "kept"}`],
  [/^이동 감도 (\S+) · 부드러움 (\S+)$/, (a, b) => `Sensitivity ${a} · Smoothing ${b}`],
  [/^집기 문턱 (\S+)$/, (a) => `Pinch threshold ${a}`],
  [/^스크롤 감도 (\S+)$/, (a) => `Scroll sensitivity ${a}`],
  [/^물체 검지 탭 문턱 (\S+)$/, (a) => `Object index-tap threshold ${a}`],
  [/^펜 접촉 (\S+) · 떼기 (\S+)$/, (a, b) => `Pen touch ${a} · lift ${b}`],
  [/^물체는 최대 (\d+)개까지 등록할 수 있습니다\.$/, (n) => `You can register up to ${n} objects.`],
  [/^camera (.+) could not be opened \(권한 또는 장치 확인\)$/, (c) => `Camera ${c} could not be opened (check permission or device)`],
  [/^손 인식 엔진 '(.+)' 를 쓸 수 없습니다 \(사용 가능: (.*)\)$/, (e, a) => `Hand engine '${e}' is unavailable (available: ${a})`],
  [/^지원하지 않는 키: (.+)$/, (k) => `Unsupported key: ${k}`],
  [/^'(.+)': '(.+)' 이름의 물체가 없습니다 \(등록하거나 이름을 맞추세요\)$/, (m, o) => `'${m}': no object named '${o}' (register it or match the name)`],
  [/^'(.+)': 버튼 출력인데 range 가 중립\(0\)을 가운데에 두고 있어 중립 위치에서 절반쯤 눌린 값이 됩니다\. 예: \[0, 0\.2\]$/, (m) => `'${m}': a button output whose range centers on neutral (0) will be half-pressed at rest. Example: [0, 0.2]`],
  [/^(.+) 에 매핑 (\d+)개 \((.*)\): (하나라도 누르면 눌림|값을 더합니다)$/, (k, n, names, how) => `${n} mappings on ${k} (${names}): ${how === "값을 더합니다" ? "values are added" : "pressed if any is pressed"}`],
];

function translate(msg: string): string {
  const suffixOnly = SUFFIX.find(([ko]) => ko === msg);
  if (suffixOnly) return suffixOnly[1];
  const rest = msg.match(/^(펜촉|검지|손바닥|물체)(?:을|를) 잘 보이는 편한 위치에 두고 잠깐 멈추세요\. 화면 중앙에 맞출 필요는 없어요\.(.*)$/);
  if (rest) return `Keep ${SUBJECT[rest[1]!] ?? "the target"} visible and pause at a comfortable position. No need to center it.${translate(rest[2]!).trim() ? " " + translate(rest[2]!).trim() : ""}`;
  const sweep = msg.match(/^지금 위치에서 (펜촉|검지|손바닥|물체)(?:을|를) 오른쪽으로 천천히 움직여 잠깐 멈춘 뒤, 그 자리에서 왼쪽으로 움직여 멈추세요\. 중앙으로 원위치시키지 않아도 됩니다\.(.*)$/);
  if (sweep) return `Move ${SUBJECT[sweep[1]!] ?? "the target"} slowly right from where you are, pause, then move left and pause. No return to the center is needed. ${translate(sweep[2]!).trim()}`;
  const depth = msg.match(/^현재 위치에서 (펜촉|검지|손바닥|물체)(?:을|를) 카메라 쪽으로 천천히 움직여 잠깐 멈춘 뒤, 그 자리에서 카메라 반대쪽으로 움직여 멈추세요\. 기울기는 유지하고 중앙으로 돌아오지 않아도 됩니다\.(.*)$/);
  if (depth) return `Move ${SUBJECT[depth[1]!] ?? "the target"} toward the camera, pause, then move away and pause. Keep its tilt; no return to the center is needed. ${translate(depth[2]!).trim()}`;

  const exact = EXACT[msg];
  if (exact) return exact;
  for (const [re, fn] of PATTERNS) {
    const m = msg.match(re);
    if (m) return fn(...m.slice(1));
  }
  for (const [ko, en] of SUFFIX) {
    if (msg.endsWith(ko) && msg.length > ko.length) {
      const head = translate(msg.slice(0, -ko.length));
      if (head !== msg.slice(0, -ko.length)) return head + en;
    }
  }
  return msg;
}

/** 서버 문구를 현재 언어로. 한국어 화면이면 그대로. */
export function sv(msg: string): string;
export function sv(msg: string | null | undefined): string | null | undefined;
export function sv(msg: string | null | undefined) {
  if (!msg || getLang() === "ko") return msg;
  return cap(translate(msg));
}
