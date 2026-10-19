import { Info } from "./Info";
import { Panel } from "./Panel";
import type { Quantiles } from "../protocol";
import { useApp } from "../store";
import { t as tr } from "../i18n";

const fmt = (v: number | null | undefined, unit = "") => (v === null || v === undefined ? "–" : `${v}${unit}`);
const q = (x: Quantiles | undefined) => (x ? `${fmt(x.p50)} / ${fmt(x.p95)}` : "–");

/** 지연·처리율 표시. 값은 p50 / p95. */
export function Hud() {
  const t = useApp((s) => s.telemetry);
  const c = useApp((s) => s.client);
  const conn = useApp((s) => s.conn);
  const objects = useApp(s => s.objects);
  const src = t?.source;
  const advanced = useApp((s) => s.devMode);

  const rows: [string, string, string?][] = [
    [tr("연결", "Connection"), conn === "open" ? tr("연결됨", "Connected") : conn === "connecting" ? tr("연결 중", "Connecting") : tr("끊김", "Disconnected"), tr("브라우저와 백엔드의 연결 상태입니다. 끊기면 새 입력을 받지 못합니다.", "Browser-to-backend connection. New input stops when disconnected.")],
    [tr("카메라", "Camera"), src ? `${src.name ?? src.kind} ${src.size ? `${src.size[0]}×${src.size[1]}` : ""}` : "–", tr("현재 영상 소스의 이름과 가로×세로 해상도입니다.", "Current video source and width × height resolution.")],
    [tr("캡처 fps", "Capture fps"), src?.enabled === false ? tr("꺼짐", "Off") : src?.paused ? tr("일시정지", "Paused") : `${fmt(src?.rate.fps)} (${tr("설정", "target")} ${fmt(src?.active_fps ?? src?.requested?.fps)})`,
      tr("카메라가 초당 실제로 보내는 프레임 수입니다. 괄호 안은 요청한 목표값이며 실제 값은 카메라/노출에 따라 낮아질 수 있습니다.", "Actual frames per second from the camera. The requested target is in parentheses; exposure and device limits can reduce it.")],
    [tr("캡처 지연", "Capture latency"), fmt(src?.pts_lag_ms, " ms"), tr("센서 노출 시각(PTS) → 앱 수신", "Sensor exposure (PTS) → app")],
    [tr("처리 fps", "Processing fps"), fmt(t?.engine.rate.fps), tr("백엔드가 초당 처리한 영상 수입니다. 캡처보다 낮으면 일부 오래된 프레임을 건너뛰고 최신 영상을 우선 처리합니다.", "Frames processed per second. If below capture fps, stale frames may be skipped to prioritize recent input.")],
    [tr("처리 ms", "Processing ms"), q(t?.engine.proc_ms), tr("한 프레임의 추적·입력 계산에 걸린 시간(ms)입니다. 앞은 p50(중앙값), 뒤는 p95(95%가 이 값 이내)입니다. 별도 비동기 모델 대기와 화면 표시 시간은 포함하지 않습니다.", "Milliseconds for one tracking/input processing pass: median p50, then p95 (95% at or below it). Separate asynchronous model wait and screen presentation are excluded.")],
    [tr("캡처→처리 완료", "Capture→processed"), q(t?.engine.age_ms), tr("프레임의 캡처 타임스탬프부터 추적 완료까지의 시간(ms, p50/p95)입니다. 대기·처리를 포함하며 AVFoundation에서 PTS를 보정한 경우 카메라 수신 지연도 포함합니다.", "Milliseconds from the capture timestamp to processing completion (p50/p95), including queueing and processing. AVFoundation PTS correction also includes camera delivery lag.")],
    [tr("미리보기 fps", "Preview fps"), `${fmt(c.renderFps)} (${tr("서버", "server")} ${fmt(t?.preview.rate.fps)})`, tr("브라우저가 초당 그린 미리보기 수입니다. 괄호 안은 서버의 미리보기 전송 속도이며, 원본 캡처/추적 fps와 다를 수 있습니다.", "Preview frames drawn per second. Parentheses show the server preview rate; both may differ from capture/tracking fps.")],
    [tr("캡처→화면", "Capture→screen"), `${fmt(c.glassP50)} / ${fmt(c.glassP95)}`, tr("캡처 타임스탬프부터 브라우저가 미리보기를 그릴 때까지의 추정 시간(ms, p50/p95)입니다. 처리·인코딩·전송·디코딩을 포함합니다. PTS 보정 여부에 따라 캡처 기준이 다르며 실제 모니터 스캔아웃은 측정하지 않습니다.", "Estimated milliseconds from the capture timestamp to browser preview drawing (p50/p95), including processing, encoding, transfer and decoding. The capture reference depends on PTS correction; physical display scanout is not measured.")],
    [tr("인코딩 ms", "Encode ms"), q(t?.preview.encode_ms), tr("미리보기 한 장을 전송 형식으로 압축하는 시간(ms, p50/p95)입니다. 원본 추적 계산 시간과 별개입니다.", "Time to compress one preview frame for transmission (ms, p50/p95), separate from tracking.")],
    [tr("WS 왕복", "WS round trip"), fmt(c.rttMs, " ms"), tr("브라우저의 확인 메시지가 백엔드를 거쳐 돌아오는 시간입니다. 카메라·손 인식·모니터 표시까지의 전체 지연은 아닙니다.", "Browser message round-trip to the backend. This is not total camera, hand recognition or display latency.")],
    [tr("캡처 슬롯 교체", "Capture slot replaced"), fmt(src?.dropped), tr("처리가 읽기 전에 최신 프레임으로 덮어쓴 누적 수입니다. 지연을 쌓지 않기 위한 교체이며 카메라 고장을 뜻하지 않습니다. 소스 재시작 시 초기화됩니다.", "Cumulative unread frames replaced by newer captures to avoid a backlog. This is not a camera failure counter; resets with the source.")],
    [tr("카메라 프레임 누락", "Camera dropped frames"), fmt(src?.late_drops), tr("AVFoundation이 콜백으로 보고한 누적 프레임 드롭입니다. 위 캡처 슬롯 교체와 다른 단계이며, 지원하지 않는 소스는 –로 표시합니다.", "Cumulative dropped-frame callbacks reported by AVFoundation, separate from app slot replacement. Unsupported sources show –.")],
    [tr("미리보기 디코딩 생략", "Preview decode skipped"), fmt(c.decodeDropped), tr("브라우저에서 이전 미리보기를 디코딩하는 동안 대기 프레임이 더 최신 프레임으로 교체되어 생략된 누적 수입니다. 추적 입력 손실과는 별개입니다.", "Pending previews replaced by newer frames while the browser was busy decoding an earlier preview. Separate from tracking input loss.")],
    [tr("미리보기 용량", "Preview size"), fmt(t?.preview.kb_per_frame, " KiB/frame"), tr("서버가 전송하는 압축 미리보기 한 장 크기의 중앙값(p50)입니다. 해상도·화질·장면 복잡도에 따라 바뀌며 전체 영상 데이터 용량은 아닙니다.", "Median (p50) compressed preview size, depending on resolution, quality and scene complexity; not the full capture data size.")],
    [tr("처리 프레임 누계", "Frames processed"), fmt(t?.engine.frames), tr("현재 엔진에서 처리를 완료한 프레임 수입니다. 초당 처리량인 처리 fps와 구분합니다.", "Frames processed by the current engine, distinct from the per-second processing rate.")],
    [tr("물체 추적 상태", "Object tracking"), `${objects.filter(x => x.state === "tracking" || x.state === "grasped").length} / ${objects.length}`, tr("추적 또는 쥠 상태인 물체 수 / 등록 물체 수입니다. 가림·탐색·놓침 상태는 앞의 수에서 제외합니다.", "Tracking or grasped objects / registered objects. Occluded, searching and lost objects are excluded from the first count.")],
  ];

  const basic: [string, string, string?][] = [rows[0]!, rows[1]!, rows[2]!, rows[4]!, rows[5]!, rows[6]!, rows[7]!, rows[8]!, rows[10]!,
    [tr("등록 물체", "Objects"), String(useApp(s => s.objects.length))],
    [tr("맨손 잭", "Hand jack"), useApp(s => s.handInputEnabled) ? tr("사용 가능", "Enabled") : tr("비활성화", "Disabled")]];
  const shown = advanced ? rows : basic;
  return (
    <Panel title={tr("성능", "Performance")} label="성능" className="hud" detail="p50 / p95" info={tr(<>캡처부터 화면까지 각 단계의 지연입니다. p50 = 보통, p95 = 느린 5%. 값이 크면 물체 수를 줄이거나 재분할 주기를 늦춰 보세요.</>,
      <>Latency at each stage from capture to screen. p50 = typical, p95 = slowest 5%. If high, track fewer objects or slow the re-segmentation rate.</>)}>
      <dl>
        {shown.map(([k, v, title]) => (
          <div key={k} title={title}>
            <dt>{k}{advanced && title && <Info wide>{title}</Info>}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}
