import { ActionIcon } from "./ActionIcon";
import { useEffect, useRef, useState } from "react";
import { getMouse, putMouse, putTracking, stopAll } from "../api";
import { Info } from "./Info";
import type { HandBackend, MouseMode, MouseSettings } from "../protocol";
import { useApp } from "../store";
import { Panel } from "./Panel";
import { AutoCalibration, calibrationActive } from './AutoCalibration';

const GESTURE_LABEL: Record<string, string> = {
  move: "이동",
  left: "왼쪽 누름",
  right: "오른쪽 누름",
  scroll: "스크롤",
  none: "손 없음",
  pen: "펜 누름",
  "object-tap": "물체 검지 탭",
};

/** 마우스 모드: 끄기 / 맨손 마우스 / 물체 마우스. 손 추적은 필요한 모드에서만 켜진다. */
export function MousePanel() {
  const info = useApp((s) => s.mouseInfo);
  const setInfo = useApp((s) => s.setMouseInfo);
  const objects = useApp((s) => s.objects);
  const live = useApp((s) => s.live.mouse);
  const conn = useApp((s) => s.conn);
  const calibrating = useApp(s => calibrationActive(s.autoCalibration));
  const deskView = useApp((s) => Boolean(s.telemetry?.source?.desk_view));
  const [err, setErr] = useState<string | null>(null);
  const settingsRef = useRef<MouseSettings | null>(null);
  const queueRef = useRef<Promise<void>>(Promise.resolve());
  const generationRef = useRef(0);

  useEffect(() => { if (info) settingsRef.current = info.settings; }, [info]);

  useEffect(() => {
    const cancel = () => { generationRef.current++; settingsRef.current = null; };
    window.addEventListener("anycontrol-stop", cancel);
    return () => window.removeEventListener("anycontrol-stop", cancel);
  }, []);

  useEffect(() => {
    if (conn === "open") getMouse().then((m) => { settingsRef.current = m.settings; setInfo(m); },
      (e: unknown) => setErr(String(e)));
  }, [conn, setInfo]);

  const apply = (patch: Partial<MouseSettings>) => {
    const current = settingsRef.current ?? info?.settings;
    if (!current || !info || calibrating) return;
    const next = { ...current, ...patch };
    const generation = generationRef.current;
    settingsRef.current = next;
    setInfo({ ...info, settings: next });
    queueRef.current = queueRef.current.then(async () => {
      if (generation !== generationRef.current) return;
      const updated = await putMouse(next);
      if (generation !== generationRef.current) {
        setInfo(await stopAll());
        return;
      }
      if (settingsRef.current === next) setInfo(updated);
      setErr(null);
    }).catch(async (e: unknown) => {
      setErr(String(e instanceof Error ? e.message : e).replace(/^\d+ /, ""));
      try {
        const actual = await getMouse();
        settingsRef.current = actual.settings;
        setInfo(actual);
      } catch { /* 연결 오류는 위에 표시 */ }
    });
  };

  const s = info?.settings;
  const mode = s?.mode ?? "off";
  const deskCalibrated = useApp((st) => st.calibration?.mode === "quad");
  const picking = useApp((st) => st.selectMode === "calib");
  /** [종이 선택]: 원근 보정을 켜고, 영상에서 종이 네 모서리를 찍는 모드로 바꾼 뒤 영상으로 스크롤 */
  const pickPaper = () => {
    if (s && !s.desk_correct) apply({ desk_correct: true });
    useApp.getState().setSelectMode("calib");
    document.querySelector('[data-tour="camera"]')?.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  const [engineBusy, setEngineBusy] = useState(false);
  const setEngine = async (b: HandBackend) => {
    setEngineBusy(true);
    try {
      await putTracking({ hand_backend: b });
      setInfo(await getMouse());
      setErr(null);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e).replace(/^\d+ /, ""));
    } finally {
      setEngineBusy(false);
    }
  };
  const depthMode = mode === "hand" && s?.hand_control === "depth" || mode === "object" && s?.coordinate_mode === "depth";
  const setMode = (m: MouseMode) => {
    if (m === "object") {
      const id = s?.object_id && objects.some((o) => o.id === s.object_id) ? s.object_id : (objects[0]?.id ?? null);
      apply({ mode: m, object_id: id });
    } else apply({ mode: m });
  };

  return (
    <Panel title="마우스" tour="mouse" info={<>맨손이나 등록한 물체를 커서로 씁니다. <b>끄기</b>를 누르면 손 추적도 멈춥니다.
      <b> ESC</b>(어디서든) 또는 [긴급 정지]로 모든 출력과 눌린 버튼을 즉시 놓습니다.</>}>
      <div className="row" role="radiogroup" aria-label="마우스 모드">
        {(
          [
            ["off", "끄기"],
            ["hand", "맨손 마우스"],
            ["object", "물체 마우스"],
          ] as [MouseMode, string][]
        ).map(([m, label]) => (
          <button key={m} type="button" role="radio" aria-checked={mode === m} className={`${m === "off" ? "act-safe" : "act-output"} ${mode === m ? "active" : ""}`}
            disabled={calibrating || !info || (m !== "off" && m !== "object" && !info.hands_available)}
            onClick={() => setMode(m)}>
            <ActionIcon name={m === "off" ? "stop" : "play"} />{label}
          </button>
        ))}
        <button type="button" className="act-stop" onClick={() => stopAll().then(setInfo)} title="ESC 키로도 멈춥니다">
          <ActionIcon name="stop" />긴급 정지 (ESC)
        </button>
      </div>

      {info?.hands_available && (info.hand_backends?.length ?? 0) > 0 && <div className="field">
        <label htmlFor="hand-backend" className="with-info">손 인식 엔진
          <Info wide><b>Apple Vision</b>(기본): 물체를 쥔 손도 잘 찾고 빠릅니다 (프레임당 약 9ms). 엄지가 가려지면 위치를 추측해
            쥔 채로 왼쪽 누름으로 오인할 수 있습니다. <b>MediaPipe</b>: 펼친 손에 안정적이지만 쥔 손을 자주 놓칩니다.
            오작동이 잦으면 바꿔 보세요. 영상의 손 뼈대 표시는 어느 엔진이든 같습니다.</Info></label>
        <select id="hand-backend" value={info.hand_backend ?? "vision"} disabled={engineBusy || calibrating}
          onChange={(e) => void setEngine(e.target.value as HandBackend)}>
          {(info.hand_backends ?? []).includes("vision") && <option value="vision">Apple Vision (기본, macOS에 적합)</option>}
          {(info.hand_backends ?? []).includes("mediapipe") && <option value="mediapipe">MediaPipe</option>}
        </select>
      </div>}
      {info && !info.hands_available && (
        <p className="warn small">손 인식 모델이 없어 맨손 마우스를 쓸 수 없습니다.</p>
      )}
      {info?.hands_error && <p className="error small">손 인식 오류: {info.hands_error}</p>}

      {mode !== 'off' && s && <AutoCalibration
        kind={mode === 'hand' ? 'hand' : objects.find(o => o.id === s.object_id)?.kind === 'pen' ? 'pen' : 'object'}
        objectId={mode === 'hand' ? null : s.object_id}
        disabled={mode === 'object' && !objects.some(o => o.id === s.object_id)} prepare={() => queueRef.current} />}

      <fieldset className="manual-settings" disabled={calibrating} aria-label="수동 마우스 설정">

      {mode === "object" && s && (
        <div className="field">
          <label htmlFor="object-control" className="with-info">물체 이동 방식
            <Info><b>좌우 + 깊이</b>: 옆 카메라용 상대 이동 (가까워지면 위). <b>영상 XY</b>: 영상 속 물체 위치가 곧 화면 위치.</Info></label>
          <select id="object-control" value={s.coordinate_mode} onChange={(e) => apply({ coordinate_mode: e.target.value as "depth" | "image" })}>
            <option value="depth">수평 카메라 · 좌우 + 깊이 (기본)</option>
            <option value="image">영상 XY · 절대 위치</option>
          </select>
          <label htmlFor="mouse-obj">커서로 쓸 물체</label>
          <select id="mouse-obj" value={s.object_id ?? ""}
            onChange={(e) => void apply({ object_id: Number(e.target.value) })}>
            {objects.map((o) => (
              <option key={o.id} value={o.id}>{o.name}{o.kind === "pen" ? " (펜촉 = 커서, 닿으면 클릭)" : ""}</option>
            ))}
          </select>
          <label className="check">
            <input type="checkbox" checked={s.hand_clicks} onChange={(e) => void apply({ hand_clicks: e.target.checked })} />
            손 제스처로 클릭·스크롤 (손 추적 켜짐)
            <Info>물체로 커서를 움직이면서, 다른 손(또는 쥔 손)의 집기로 클릭·스크롤합니다. 손 추적이 함께 돌아 CPU를 조금 더 씁니다.</Info>
          </label>
          {s.hand_clicks && objects.find((o) => o.id === s.object_id)?.kind !== "pen" && <>
            <label className="check"><input type="checkbox" checked={s.object_tap}
              onChange={(e) => void apply({ object_tap: e.target.checked })} />물체 위 검지 탭 = 왼쪽 클릭</label>
            {s.object_tap && <Slider id="object-tap-distance" label="검지 탭 허용 거리" value={s.object_tap_distance}
              min={.03} max={.25} step={.01} onChange={(v) => apply({ object_tap_distance: v })} />}
            <p className="small muted">물체를 쥔 손의 검지를 살짝 들었다가 내려놓으세요. 영상상 거리로 접촉을 추정합니다.</p>
          </>}
        </div>
      )}

      {mode !== "off" && s && (
        <>
          <div className="field">
            {depthMode && <>
              <p className="small muted">좌우 이동은 X, 가까워지면 커서 위·멀어지면 아래로 이동합니다. 손바닥/물체 크기로 깊이를 추정하고, 종이 4점 보정이 있으면 책상 앞뒤 좌표를 사용합니다.
                <Info>수평 카메라에서 카메라 쪽으로 다가가면 영상 속 크기가 커집니다. 이 크기 변화를 앞뒤 거리로 바꿔 커서 위아래로 씁니다.</Info></p>
              <Slider id="depth-sensitivity" label="좌우·깊이 이동 감도" value={s.depth_sensitivity} min={.2} max={6} step={.1} onChange={(v) => apply({ depth_sensitivity: v })} />
              <Slider id="depth-gain" label="깊이 이동 감도" value={s.depth_gain} min={.2} max={5} step={.1} onChange={(v) => apply({ depth_gain: v })} />
            </>}
            <fieldset className="axis-sens">
              <legend className="small with-info">커서 감도·방향 ({mode === "hand" ? "맨손" : "물체"} 마우스)
                <Info>감도 2× = 조금만 움직여도 커서가 두 배 멀리 움직입니다. 위의 이동 감도에 곱해집니다.
                  방향이 반대면 반전을 켜세요. 자동 보정도 방향을 정합니다.</Info>
              </legend>
              <label htmlFor="sens-x">좌우 감도 ({s.sens_x.toFixed(1)}×)</label>
              <input id="sens-x" type="range" min={0.2} max={5} step={0.1} value={s.sens_x}
                onChange={(e) => void apply({ sens_x: Number(e.target.value) })} />
              <label htmlFor="sens-y">상하 감도 ({s.sens_y.toFixed(1)}×)</label>
              <input id="sens-y" type="range" min={0.2} max={5} step={0.1} value={s.sens_y}
                onChange={(e) => void apply({ sens_y: Number(e.target.value) })} />
              <div className="row">
                <label className="check">
                  <input type="checkbox" checked={s.mirror} onChange={(e) => void apply({ mirror: e.target.checked })} />
                  좌우 반전
                </label>
                <label className="check">
                  <input type="checkbox" checked={s.invert_y} onChange={(e) => void apply({ invert_y: e.target.checked })} />
                  상하 반전
                </label>
                {(s.sens_x !== 1 || s.sens_y !== 1 || s.mirror || s.invert_y) && (
                  <button type="button" className="small act-reset"
                    onClick={() => void apply({ sens_x: 1, sens_y: 1, mirror: false, invert_y: false })}>기본값</button>
                )}
              </div>
            </fieldset>
            {depthMode && <fieldset className="desk-correct">
              <legend className="small with-info">가장자리 사선 보정
                <Info wide>화면 가운데에서는 앞뒤 이동이 커서 위아래로 곧게 가지만, 가장자리에서는 곧게 앞뒤로 움직여도 영상에서는
                  사선으로 보입니다 (원근). 두 가지로 폅니다.<br /><b>① 크기 기반</b>: 가까워질수록 물체가 화면 가운데에서 멀어지는 만큼을
                  빼서 계산합니다. 카메라 FOV(화각)는 계산에서 상쇄되어 입력할 필요가 없습니다.<br /><b>② 종이 보정</b>: 책상 위 A4 종이 네 모서리를
                  찍으면 책상 면 자체를 반듯하게 펴서 가장 정확합니다.</Info>
              </legend>
              <label className="check">
                <input type="checkbox" checked={s.depth_perspective} onChange={(e) => void apply({ depth_perspective: e.target.checked })} />
                ① 크기 기반 사선 보정 <span className="badge-rec">권장</span>
              </label>
              <div className="paper-guide">
                <PaperDiagram done={deskCalibrated} />
                <ol className="small">
                  <li><b>A4 종이</b> 한 장을 {mode === "hand" ? "손을" : "물체를"} 움직일 자리의 책상 위에 <b>가로로</b> 놓습니다.</li>
                  <li><b>[📄 종이 선택]</b>을 누르고 영상에서 종이의 <b>네 모서리</b>를 하나씩 클릭합니다 (순서 무관).</li>
                  <li>끝. <b>종이 = 마우스 패드</b>가 됩니다. 종이는 치워도 됩니다 (카메라를 옮기면 다시 선택).</li>
                </ol>
              </div>
              <div className="row">
                <button type="button" className={picking ? "active" : "act-output"} onClick={pickPaper} aria-pressed={picking}>
                  📄 {picking ? "영상에서 모서리 찍는 중…" : deskCalibrated ? "종이 다시 선택" : "종이 선택"}
                </button>
                <span className={`small ${deskCalibrated ? "ok" : "muted"}`}>{deskCalibrated ? "✓ 종이 보정 있음" : "아직 종이 보정 없음"}</span>
              </div>
              <label className="check">
                <input type="checkbox" checked={s.desk_correct} onChange={(e) => void apply({ desk_correct: e.target.checked })} />
                ② 커서에 종이 보정 쓰기
                <Info>켜면 커서를 영상 좌표 대신 <b>책상(종이) 면 위 좌표</b>로 계산합니다
                  {mode === "hand" ? " (손바닥을 책상 가까이 두고 움직일 때 가장 정확합니다. 손을 공중에 높이 띄우면 높이가 앞뒤로 섞이므로 끄는 게 낫습니다)"
                    : " (물체가 책상에 닿은 점 기준. 부드러운 추적 위치에 닿은 점 오프셋을 더해 떨림을 줄였습니다)"}.
                  종이가 화면에서 너무 납작하면(카메라가 거의 수평) 자동으로 크기 기반을 씁니다.</Info>
              </label>
              <p className="small muted">지금: {live?.depth_source === "desk" ? "종이 보정으로 계산 중" : live?.perspective_active ? "크기 기반 사선 보정 중" : "보정 없음"}</p>
            </fieldset>}
            <label className="check">
              <input type="checkbox" checked={s.invert_scroll} onChange={(e) => void apply({ invert_scroll: e.target.checked })} />
              스크롤 반전
            </label>
            <label htmlFor="smooth" className="with-info">부드럽게 ↔ 빠르게 ({s.smoothing.toFixed(1)})
              <Info>왼쪽 = 떨림이 적지만 조금 늦게 따라옴, 오른쪽 = 빠르지만 손떨림도 보임.</Info></label>
            <input id="smooth" type="range" min={0.3} max={4} step={0.1} value={s.smoothing}
              onChange={(e) => void apply({ smoothing: Number(e.target.value) })} />
            {(mode === "hand" || s.hand_clicks) && (
              <>
                <label htmlFor="pinch" className="with-info">집기 민감도 ({s.pinch_on.toFixed(2)})
                  <Info>엄지와 손가락 끝이 이 거리(손 크기 대비)보다 가까우면 집은 것으로 봅니다. 클릭이 잘 안 되면 높이고, 저절로 눌리면 낮추세요.</Info></label>
                <input id="pinch" type="range" min={0.15} max={0.5} step={0.01} value={s.pinch_on}
                  onChange={(e) => void apply({ pinch_on: Number(e.target.value) })} />
              </>
            )}
          </div>
          {mode === "hand" && <div className="field">
            <label htmlFor="hand-control" className="with-info">손 이동 방식
              <Info><b>좌우 + 깊이</b>: 옆 카메라용, 손을 카메라 쪽으로 밀면 위. <b>터치패드</b>: 검지를 책상에 댄 동안만 이동.
                <b> 공중 마우스</b>: 영상 속 손 위치가 곧 화면 위치.</Info></label>
            <select id="hand-control" value={s.hand_control}
              onChange={(e) => void apply({ hand_control: e.target.value as "depth" | "touchpad" | "air" })}>
              <option value="depth">수평 카메라 · 좌우 + 깊이 (기본)</option>
              <option value="touchpad">책상 터치패드 · 접촉 중 상대 이동</option>
              <option value="air">공중 마우스 · 화면 절대 위치</option>
            </select>
            {s.hand_control === "touchpad" && <>
              <p className="small muted">손 검지가 책상에 닿았을 때만 이동합니다. 영상에서 종이 4점 또는 기준선 2점을 먼저 보정하세요.
                현재: {live?.surface_mode === "quad" ? "4점 보정" : live?.surface_mode === "line" ? "기준선 보정" : live?.surface_mode === 'deskview' ? 'Desk View 전체 책상' : "보정 필요"} · {live?.touching ? "접촉" : "떨어짐"}</p>
              {deskView && <p className="small muted">Desk View에서는 보정된 XY 이동과 손가락 상대 깊이/자세를 사용합니다. 접촉 판정은 추정이며 높이 슬라이더로 조절하세요. 크기 기반 깊이 보정은 적용하지 않습니다.</p>}
              <Slider id="touch-sensitivity" label="손 이동 감도" value={s.touch_sensitivity} min={0.2} max={6} step={0.1} onChange={(v) => apply({ touch_sensitivity: v })} />
              <Slider id="touch-height" label="접촉 판정 높이" value={s.touch_height} min={-1} max={1} step={0.05} onChange={(v) => apply({ touch_height: v })} />
              <Slider id="touch-margin" label="책상 허용 범위" value={s.touch_margin} min={0} max={0.15} step={0.005} onChange={(v) => apply({ touch_margin: v })} />
              <Slider id="touch-depth" label="크기 변화로 깊이 보정" value={s.touch_depth_blend} min={0} max={1} step={0.05} disabled={deskView} onChange={(v) => apply({ touch_depth_blend: v })} />
              <Slider id="touch-deadzone" label="손 떨림 제거" value={s.touch_deadzone} min={0} max={0.04} step={0.001} onChange={(v) => apply({ touch_deadzone: v })} />
              <Slider id="scroll-gain" label="두 손가락 스크롤 감도" value={s.scroll_gain} min={1} max={100} step={1} onChange={(v) => apply({ scroll_gain: v })} />
            </>}
          </div>}
          {mode === "object" && objects.find((o) => o.id === s.object_id)?.kind === "pen" && <div className="field">
            <label className="check"><input type="checkbox" checked={s.pen_relative}
              onChange={(e) => void apply({ pen_relative: e.target.checked })} />펜촉 접촉 중 상대 이동</label>
            <Slider id="pen-sensitivity" label="펜 이동 감도" value={s.pen_sensitivity} min={0.2} max={6} step={0.1} onChange={(v) => apply({ pen_sensitivity: v })} />
            <Slider id="pen-depth" label="펜 크기 변화로 깊이 보정" value={s.pen_depth_blend} min={0} max={1} step={0.05} disabled={deskView} onChange={(v) => apply({ pen_depth_blend: v })} />
            {deskView && <p className="small muted">Desk View의 펜 접촉은 [펜·맨손 그리기]에서 닿음·떼기 보정 또는 수동 그리기로 지정하세요.</p>}
          </div>}
          <dl className="mouse-status">
            <div><dt>손</dt><dd>{live?.hand_visible ? "보임" : "안 보임"}</dd></div>
            <div><dt>동작</dt><dd>{GESTURE_LABEL[live?.gesture ?? "none"] ?? live?.gesture}{live?.freeze ? " · 커서 고정" : ""}</dd></div>
            <div>
              <dt>집기 거리</dt>
              <dd>
                <span className="bar" aria-hidden="true">
                  <span className="fill" style={{
                    left: 0, width: `${Math.min(100, ((live?.pinch_index ?? 1) / 1.0) * 100)}%`,
                    background: (live?.pinch_index ?? 1) < (s.pinch_on ?? 0.3) ? "#ff4d6d" : "#5b9dff",
                  }} />
                </span>
              </dd>
            </div>
          </dl>
          {(mode === "hand" || s.hand_clicks) && (
            <ul className="small muted gesture-help">
              {mode === "hand" && <li>{s.hand_control === "touchpad" ? "책상에 검지를 댄 채 움직이면 커서가 상대적으로 이동합니다. 손을 떼면 멈춥니다." : "손바닥을 움직이면 커서가 움직입니다."}</li>}
              <li>엄지 + 검지 끝 집기 = 왼쪽 클릭 (집은 채로 움직이면 드래그)</li>
              <li>엄지 + 가운뎃손가락 끝 집기 = 오른쪽 클릭</li>
              <li>{s.hand_control === "touchpad" ? "검지·중지를 책상에 대고 위아래로 = 스크롤" : "검지·중지만 펴고 위아래로 = 스크롤"}</li>
            </ul>
          )}
        </>
      )}
      </fieldset>
      {err && <p className="error small" role="alert">{err}</p>}
    </Panel>
  );
}

function Slider({ id, label, value, min, max, step, disabled, onChange }: {
  id: string; label: string; value: number; min: number; max: number; step: number;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  return <><label htmlFor={id}>{label} ({value.toFixed(step < 0.01 ? 3 : step < 1 ? 2 : 0)})</label>
    <input id={id} type="range" min={min} max={max} step={step} value={value} disabled={disabled}
      onChange={(e) => onChange(Number(e.target.value))} /></>;
}

/** 종이 보정 그림: 카메라에 사다리꼴로 보이는 종이 → 반듯한 마우스 패드 */
function PaperDiagram({ done }: { done: boolean }) {
  const corners: [number, number][] = [[22, 10], [62, 10], [76, 48], [8, 48]];
  return (
    <svg className="paper-diagram" viewBox="0 0 190 58" role="img"
      aria-label="카메라에는 종이가 사다리꼴로 보입니다. 네 모서리를 찍으면 반듯한 네모(마우스 패드)로 펴집니다.">
      <text x="42" y="7" textAnchor="middle" className="pd-cap">카메라에 보이는 종이</text>
      <polygon points={corners.map((p) => p.join(",")).join(" ")} className="pd-paper" />
      {corners.map(([x, y], i) => (
        <g key={i}>
          <circle cx={x} cy={y} r={4.2} className="pd-dot" />
          <text x={x} y={y + 2.2} textAnchor="middle" className="pd-num">{i + 1}</text>
        </g>
      ))}
      <path d="M88 29 h18 m-5 -5 l5 5 l-5 5" className="pd-arrow" />
      <text x="148" y="7" textAnchor="middle" className="pd-cap">{done ? "✓ 마우스 패드" : "→ 마우스 패드"}</text>
      <rect x="116" y="12" width="64" height="38" rx="2" className={`pd-pad ${done ? "done" : ""}`} />
      <path d="M140 26 l0 11 l3 -3 l2.5 5 l2 -1 l-2.5 -5 l4 0 z" className="pd-cursor" />
    </svg>
  );
}
