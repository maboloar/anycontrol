import { Panel } from "./Panel";
import type { Quantiles } from "../protocol";
import { useApp } from "../store";

const fmt = (v: number | null | undefined, unit = "") => (v === null || v === undefined ? "–" : `${v}${unit}`);
const q = (x: Quantiles | undefined) => (x ? `${fmt(x.p50)} / ${fmt(x.p95)}` : "–");

/** 지연·처리율 표시. 값은 p50 / p95. */
export function Hud() {
  const t = useApp((s) => s.telemetry);
  const c = useApp((s) => s.client);
  const conn = useApp((s) => s.conn);
  const src = t?.source;

  const rows: [string, string, string?][] = [
    ["연결", conn === "open" ? "연결됨" : conn === "connecting" ? "연결 중" : "끊김"],
    ["카메라", src ? `${src.name ?? src.kind} ${src.size ? `${src.size[0]}×${src.size[1]}` : ""}` : "–"],
    ["캡처 fps", src?.enabled === false ? "꺼짐" : src?.paused ? "일시정지" : `${fmt(src?.rate.fps)} (설정 ${fmt(src?.active_fps ?? src?.requested?.fps)})`,
      "카메라가 실제로 보내는 프레임 수"],
    ["캡처 지연", fmt(src?.pts_lag_ms, " ms"), "센서 노출 시각(PTS) → 앱 수신"],
    ["처리 fps", fmt(t?.engine.rate.fps)],
    ["처리 ms", q(t?.engine.proc_ms), "추적·매핑 hot loop"],
    ["캡처→처리 완료", q(t?.engine.age_ms), "ms, 캡처 지연 포함"],
    ["미리보기 fps", `${fmt(c.renderFps)} (서버 ${fmt(t?.preview.rate.fps)})`],
    ["캡처→화면", `${fmt(c.glassP50)} / ${fmt(c.glassP95)}`, "ms, 인코딩·전송·디코딩 포함"],
    ["인코딩 ms", q(t?.preview.encode_ms)],
    ["WS 왕복", fmt(c.rttMs, " ms")],
  ];

  return (
    <Panel title="성능" className="hud" detail="p50 / p95" info={<>캡처부터 화면까지 각 단계의 지연입니다. p50 = 보통, p95 = 느린 5%. 값이 크면 물체 수를 줄이거나 재분할 주기를 늦춰 보세요.</>}>
      <dl>
        {rows.map(([k, v, title]) => (
          <div key={k} title={title}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}
