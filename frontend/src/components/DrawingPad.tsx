import { ActionIcon } from "./ActionIcon";
import { Panel } from "./Panel";
import { useEffect, useRef, useState } from "react";
import { clearHandDrawing, penAction, putHandDrawing } from "../api";
import { connection } from "../connection";
import { drawingView, mapHandStrokes, type Stroke } from "../drawing";
import type { FrameState } from "../protocol";
import { useApp } from "../store";
import { AutoCalibration, calibrationActive } from './AutoCalibration';

/** 펜 접촉 또는 엄지·검지 집기로 획을 그린다. */
export function DrawingPad() {
  const objects = useApp((s) => s.objects);
  const pens = objects.filter((o) => o.kind === "pen");
  const [penId, setPenId] = useState<number | null>(null);
  const live = useApp((s) => (penId === null ? undefined : s.live.pens[String(penId)]));
  const handLive = useApp((s) => s.live.handDrawing);
  const conn = useApp((s) => s.conn);
  const calibrating = useApp(s => calibrationActive(s.autoCalibration));
  const [previewMirror, setDrawingMirror] = useState(false);
  const previewMirrorRef = useRef(previewMirror);
  previewMirrorRef.current = previewMirror;
  const [source, setSource] = useState<"pen" | "hand">("pen");
  const [handEnabled, setHandEnabled] = useState(true);
  const [handInvertY, setHandInvertY] = useState(false);
  const handInvertYRef = useRef(false);
  const handPoint = useRef<[number, number] | null>(null);
  const handAspect = useRef(1.6);
  const penPoint = useRef<[number, number] | null>(null);
  const penImagePoint = useRef<[number, number] | null>(null);
  const penAnchor = useRef<[number, number] | null>(null);
  const [showTip, setShowTip] = useState(() => {
    try { return localStorage.getItem('anycontrol.drawing.crosshair') !== 'off'; } catch { return true; }
  });
  const showTipRef = useRef(showTip);
  showTipRef.current = showTip;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const strokes = useRef<Stroke[]>([]);
  const current = useRef<Stroke | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [nearUp, setNearUp] = useState(true);
  const nearUpRef = useRef(true);
  const holdTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const manualQueue = useRef<Promise<unknown>>(Promise.resolve());
  const holdGeneration = useRef(0);
  const [holding, setHolding] = useState(false);

  const manual = (id: number, down: boolean, generation: number) => {
    manualQueue.current = manualQueue.current.catch(() => undefined).then(() => {
      if (down && holdGeneration.current !== generation) return;
      return penAction(id, down ? 'down' : 'up');
    }).catch((e: unknown) => setErr(String(e)));
  };
  const stopHolding = () => {
    if (holdTimer.current === null) return;
    clearInterval(holdTimer.current);
    holdTimer.current = null;
    const generation = ++holdGeneration.current;
    setHolding(false);
    if (penId !== null) manual(penId, false, generation);
  };
  const startHolding = () => {
    if (source !== "pen" || penId === null || holdTimer.current !== null) return;
    const generation = ++holdGeneration.current;
    setHolding(true);
    manual(penId, true, generation);
    holdTimer.current = setInterval(() => manual(penId, true, generation), 400);
  };
  useEffect(() => {
    const end = () => stopHolding();
    const emergencyStop = () => { end(); setHandEnabled(false); };
    const hidden = () => { if (document.hidden) end(); };
    window.addEventListener('pointerup', end);
    window.addEventListener('pointercancel', end);
    window.addEventListener('blur', end);
    window.addEventListener('anycontrol-stop', emergencyStop);
    document.addEventListener('visibilitychange', hidden);
    return () => {
      end();
      window.removeEventListener('pointerup', end);
      window.removeEventListener('pointercancel', end);
      window.removeEventListener('blur', end);
      window.removeEventListener('anycontrol-stop', emergencyStop);
      document.removeEventListener('visibilitychange', hidden);
    };
  }, [penId, source]);

  useEffect(() => {
    if (source !== "hand" || conn !== "open") return;
    let active = true;
    setErr(null);
    setMsg(null);
    putHandDrawing(handEnabled).then((info) => {
      if (active) setErr(info.hands_error);
    }, (e: unknown) => {
      if (active) setErr(String(e instanceof Error ? e.message : e).replace(/^\d+ /, ""));
    });
    return () => { active = false; void putHandDrawing(false).catch(() => undefined); };
  }, [source, handEnabled, conn]);

  useEffect(() => {
    if (penId === null || !pens.some((p) => p.id === penId)) setPenId(pens[0]?.id ?? null);
  }, [pens, penId]);

  const activePenId = source === "pen" ? penId : null;
  useEffect(() => {
    strokes.current = [];
    current.current = null;
    handPoint.current = null;
    penPoint.current = penImagePoint.current = penAnchor.current = null;
    draw();
    return connection.onMessage((type, data) => {
      if (type !== "state") return;
      const frame = data as unknown as FrameState;
      const p = source === "hand" ? frame.hand_drawing : frame.pens?.[String(activePenId)];
      if (!p) { handPoint.current = penPoint.current = penImagePoint.current = null; draw(); return; }
      if (source === 'pen') {
        const pen = frame.pens?.[String(activePenId)];
        penPoint.current = pen && !pen.uncertain ? pen.draw_point ?? null : null;
        penImagePoint.current = pen?.tip && !pen.uncertain && frame.size ? [pen.tip[0] / frame.size[0], pen.tip[1] / frame.size[1]] : null;
        if (penPoint.current && !penAnchor.current) penAnchor.current = penPoint.current;
        if (frame.size) handAspect.current = frame.size[0] / frame.size[1];
      }
      if (source === "hand" && frame.hand_drawing) {
        handPoint.current = frame.hand_drawing.point;
        if (frame.size) handAspect.current = frame.size[0] / frame.size[1];
      }
      for (const ev of p.events) {
        if (ev.type === "clear") { strokes.current = []; penAnchor.current = penPoint.current; }
        if (ev.type === "up" && ev.stroke) strokes.current.push(ev.stroke);
      }
      current.current = p.current;
      draw();
    });
  }, [source, activePenId]);

  const draw = () => {
    const c = canvasRef.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const all = current.current ? [...strokes.current, current.current] : strokes.current;
    ctx.fillStyle = "#fbfaf7";
    ctx.fillRect(0, 0, c.width, c.height);
    const project = drawingView(all, penAnchor.current ?? [0, 0], c.width, c.height, nearUpRef.current, previewMirrorRef.current);
    const fitted = source === "hand"
      ? mapHandStrokes(all, c.width, c.height, 24, handAspect.current, handInvertYRef.current, previewMirrorRef.current)
      : all.map(s => s.map(project));
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    fitted.forEach((s, i) => {
      ctx.strokeStyle = i === fitted.length - 1 && current.current ? "#e63946" : "#1d3557";
      ctx.lineWidth = 3;
      ctx.beginPath();
      s.forEach(([x, y], k) => (k ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.stroke();
      if (s.length === 1) {
        ctx.fillStyle = ctx.strokeStyle;
        ctx.beginPath();
        ctx.arc(s[0]![0], s[0]![1], 1.5, 0, Math.PI * 2);
        ctx.fill();
      }
    });
    const point = source === 'hand' ? handPoint.current : penPoint.current;
    if (showTipRef.current && (point || source === 'pen' && penImagePoint.current)) {
      const world = source === 'pen' && penPoint.current;
      const raw = world ? project(world) : mapHandStrokes([[point ?? penImagePoint.current!]], c.width, c.height, 24,
        handAspect.current, source === 'hand' && handInvertYRef.current, previewMirrorRef.current)[0]![0]!;
      const x = Math.max(12, Math.min(c.width - 12, raw[0]));
      const y = Math.max(12, Math.min(c.height - 12, raw[1]));
      ctx.strokeStyle = current.current ? '#e63946' : '#2677c9';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x - 10, y); ctx.lineTo(x + 10, y);
      ctx.moveTo(x, y - 10); ctx.lineTo(x, y + 10);
      ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.stroke();
      ctx.fillStyle = '#35516a'; ctx.font = '12px system-ui';
      ctx.fillText(source === 'pen' && !world ? '영상 위치 · 책상 투영 범위 밖' :
        raw[0] !== x || raw[1] !== y ? '위치 · 화면 밖' : current.current ? '그리는 중' : source === 'pen' ? '펜촉 위치' : '검지 위치',
        Math.min(x + 14, c.width - 185), Math.max(16, y - 12));
    }
  };

  useEffect(() => { draw(); }, [previewMirror, showTip]);
  useEffect(() => {
    if (conn !== 'open') { penPoint.current = penImagePoint.current = handPoint.current = null; draw(); }
  }, [conn]);

  const clearHand = async () => {
    try {
      await clearHandDrawing();
      strokes.current = [];
      current.current = null;
      draw();
      setErr(null);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e).replace(/^\d+ /, ""));
    }
  };

  const act = async (a: "clear" | "touch" | "lift" | "auto" | "reset") => {
    if (penId === null) return;
    try {
      await penAction(penId, a);
      if (a === "clear") {
        strokes.current = [];
        current.current = null;
        draw();
      }
      setMsg(a === "touch" || a === 'lift' ? (live?.desk_view
        ? '샘플을 저장했습니다. 같은 기울기로 닿음과 떼기를 모두 지정한 뒤 자동 접촉을 사용하세요.'
        : "보정 지점을 저장했습니다. 가까운 곳·먼 곳 두 군데 이상 찍으면 정확해집니다.") : null);
      setErr(null);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e).replace(/^\d+ /, ""));
    }
  };

  const setHorizon = async (v: number) => {
    if (penId !== null) await penAction(penId, "config", { horizon: v }).catch(() => undefined);
  };

  const setPenSetting = async (key: string, value: number) => {
    if (penId !== null) await penAction(penId, "config", { [key]: value }).catch((e: unknown) => setErr(String(e)));
  };

  return (
    <Panel title="펜·맨손 그리기" label="펜·맨손 그리기 데모" className="demo" info={<>등록한 펜의 펜촉이 책상에 닿은 동안, 또는 맨손으로 엄지+검지를 집은 동안 그려집니다. 접촉은 영상으로 추정하므로 보정을 먼저 해 주세요.</>}>
      <div className="row" role="group" aria-label="그리기 입력 방식">
        <button type="button" aria-pressed={source === "pen"} className={source === "pen" ? "active" : ""}
          onClick={() => { setSource("pen"); setErr(null); setMsg(null); }}>펜</button>
        <button type="button" aria-pressed={source === "hand"} className={source === "hand" ? "active" : ""}
          onClick={() => { setSource("hand"); setHandEnabled(true); }}>맨손 검지</button>
      </div>
      <label className="check small"><input type="checkbox" checked={showTip} onChange={e => {
        setShowTip(e.target.checked);
        try { localStorage.setItem('anycontrol.drawing.crosshair', e.target.checked ? 'on' : 'off'); } catch { /* 선택은 현재 세션에 유지 */ }
      }} />펜촉·검지 위치 십자 표시</label>
      <label className="check small"><input type="checkbox" checked={previewMirror} onChange={e => { setDrawingMirror(e.target.checked); previewMirrorRef.current = e.target.checked; draw(); }} />그리기 좌우 반전 (개별)</label>
      {showTip && source === 'pen' && live?.uncertain && <p className="small muted">펜촉이 가려져 위치를 확인하는 중입니다.</p>}
      {source === "hand" ? (
        <>
          <p className="small muted">엄지와 검지 끝을 맞대면 그리기를 시작하고, 떼면 멈춥니다. 맞댄 상태로 손을 움직이면 검지 끝을 따라 그려집니다. 펜 등록이나 책상 접촉 보정 없이 사용할 수 있습니다.</p>
          <div className="row">
            <label className="check"><input type="checkbox" checked={handEnabled} disabled={conn !== "open"}
              onChange={(e) => setHandEnabled(e.target.checked)} />맨손 그리기 활성화</label>
            <span className={`state ${handEnabled && handLive?.contact ? "state-tracking" : ""}`}>
              {conn !== "open" ? "연결 대기" : !handEnabled || !handLive?.enabled ? "그리기 중지"
                : !handLive.hand_visible ? "손을 카메라에 보여 주세요" : handLive.contact ? "맞댐 (그리는 중)" : "떼어 있음"}
            </span>
          </div>
          <canvas ref={canvasRef} width={640} height={400} className="drawpad" aria-label="검지로 그린 그림" role="img" />
          <label className="check small"><input type="checkbox" checked={handInvertY}
            onChange={(e) => { handInvertYRef.current = e.target.checked; setHandInvertY(e.target.checked); draw(); }} />
            그리기 상하 반전</label>
          <button type="button" className="act-danger" onClick={() => void clearHand()}><ActionIcon name="trash" />지우기</button>
        </>
      ) : pens.length === 0 ? (
        <p className="muted">영상 아래 [펜 (두 점)] 을 누르고, 펜촉 → 반대쪽 끝 순서로 찍어 펜을 등록하세요.</p>
      ) : (
        <>
          <div className="row">
            {pens.length > 1 && (
              <select aria-label="펜 선택" disabled={calibrating} value={penId ?? ""} onChange={(e) => setPenId(Number(e.target.value))}>
                {pens.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            )}
            <span className={`state ${live?.contact && !live.uncertain ? "state-tracking" : ""}`}>{live?.uncertain ? "가림 · 입력 대기" : live?.contact ? "닿음 (그리는 중)" : "떨어짐"}</span>
            <span className="muted small">
              {live?.desk_view
                ? `Desk View · ${live.contact_mode === 'manual' ? '수동 입력' : live.calibrated ? '접촉 보정됨' : '접촉 보정 필요'} · 닿음 ${live.touch_samples ?? 0} / 떼기 ${live.lift_samples ?? 0}`
                : live?.calibrated ? (live.manual_calibration ? "수동 보정됨" : "자동 보정됨") : `자동 보정 중… (${live?.samples ?? 0}/90)`}
              {live?.height != null ? ` · 높이 ${live.height.toFixed(1)}px` : ""}
            </span>
          </div>
          {penId !== null && <AutoCalibration kind="pen" objectId={penId} prepare={async () => { stopHolding(); await manualQueue.current; }} />}
          <canvas ref={canvasRef} width={640} height={400} className="drawpad" aria-label="펜으로 그린 그림" role="img" />
          <label className="check small"><input type="checkbox" checked={nearUp}
            onChange={(e) => { nearUpRef.current = e.target.checked; setNearUp(e.target.checked); draw(); }} />
            그리기 상하 반전 (카메라 가까운 방향이 위)</label>
          <fieldset className="manual-settings" disabled={calibrating} aria-label="수동 펜 설정">
          <div className="row">
            <button type="button" className="act-danger" onClick={() => act("clear")}><ActionIcon name="trash" />지우기</button>
            <button type="button" className="act-config" onClick={() => act("touch")} title="펜촉을 책상에 댄 채로 누르세요"><ActionIcon name="target" />지금 닿아 있음 (보정)</button>
            {live?.desk_view && <>
              <button type="button" className="act-config" onClick={() => act('lift')}><ActionIcon name="target" />지금 떼어 있음 (보정)</button>
              <button type="button" className="act-output" disabled={!live.calibrated || holding} onClick={() => act('auto')}><ActionIcon name="check" />자동 접촉 사용</button>
              <button type="button" className={`act-output ${holding ? 'active' : ''}`}
                onPointerDown={(e) => { if (e.button !== 0) return; e.currentTarget.setPointerCapture(e.pointerId); startHolding(); }}
                onKeyDown={(e) => { if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) { e.preventDefault(); startHolding(); } }}
                onKeyUp={(e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); stopHolding(); } }}>
                <ActionIcon name="play" />{holding ? '그리는 중 · 떼면 멈춤' : '누르는 동안 그리기'}</button>
            </>}
            <button type="button" className="act-reset" onClick={() => act("reset")}><ActionIcon name="reset" />보정 초기화</button>
            {!live?.desk_view && <>
            <label className="small" htmlFor="horizon">책상 소실선</label>
            <input id="horizon" type="range" min={0.2} max={0.8} step={0.01} value={live?.horizon ?? 0.5}
              onChange={(e) => void setHorizon(Number(e.target.value))} />
            </>}
          </div>
          {!live?.desk_view && <label className="check small"><input type="checkbox" checked={!!live?.shadow_assist} onChange={e => { if (penId !== null) void penAction(penId, 'config', { shadow_assist: e.target.checked }).catch(e => setErr(String(e))); }} />책상색·그림자로 헛획 시작 줄이기</label>}
          {live?.shadow_veto && <p className="small muted">펜촉 주변이 책상인지 확인 중 · 획 시작 보류</p>}
          <div className="field">
            {live?.desk_view ? <PenSlider key={`${penId}-desk-margin`} label="Desk View 접촉 확신 문턱"
              initial={live.settings?.desk_contact_margin ?? .18} min={0} max={.9} step={.02}
              onChange={(v) => setPenSetting('desk_contact_margin', v)} /> : <>
            <PenSlider key={`${penId}-on`} label="펜 접촉 감도" initial={live?.settings?.touch_on ?? 0.6} min={0.1} max={3} step={0.05}
              onChange={(v) => setPenSetting("touch_on", v)} />
            <PenSlider key={`${penId}-off`} label="펜 떼기 문턱" initial={live?.settings?.touch_off ?? 1} min={0.15} max={4} step={0.05}
              onChange={(v) => setPenSetting("touch_off", v)} />
            </>}
            <PenSlider key={`${penId}-edge`} label="펜촉 경계 탐색 폭" initial={live?.settings?.edge_span ?? 0.4} min={0} max={1.5} step={0.05}
              onChange={(v) => setPenSetting("edge_span", v)} />
            <PenSlider key={`${penId}-smooth`} label="펜촉 안정화" initial={live?.settings?.tip_min_cutoff ?? 2} min={0.2} max={10} step={0.1}
              onChange={(v) => setPenSetting("tip_min_cutoff", v)} />
            <PenSlider key={`${penId}-speed`} label="빠른 움직임 반응" initial={live?.settings?.tip_beta ?? 1} min={0} max={5} step={0.1}
              onChange={(v) => setPenSetting("tip_beta", v)} />
            <PenSlider key={`${penId}-mask-age`} label="마스크 유효 시간" initial={live?.settings?.refined_max_age ?? 0.35} min={0.05} max={2} step={0.05}
              onChange={(v) => setPenSetting("refined_max_age", v)} />
          </div>
          </fieldset>
          <p className="small muted">
            {live?.desk_view
              ? 'Desk View는 책상 XY를 그대로 사용합니다. 종이 4점을 지정하면 그림 영역을 보정합니다. 동일한 기울기로 펜을 바닥에 1초 대고 닿음 샘플, 2–3cm 들어 1초 유지하고 떼기 샘플을 저장하세요. 여러 위치·기울기도 추가할 수 있습니다. 두 상태의 외형 차이가 작으면 수동 그리기 버튼을 사용하세요. 자동 접촉은 영상 외형에 따른 추정입니다.'
              : '펜을 책상에 대고 몇 초 움직이면 책상 면을 스스로 보정합니다. 그림이 한쪽으로 눌려 보이면 소실선을 조절하세요 (카메라가 수평이면 0.5).'}
          </p>
          {msg && <p className="small">{msg}</p>}
        </>
      )}
      {(err || (source === "hand" && handLive?.error)) &&
        <p className="error small" role="alert">{err || handLive?.error}</p>}
    </Panel>
  );
}

function PenSlider({ label, initial, min, max, step, onChange }: {
  label: string; initial: number; min: number; max: number; step: number;
  onChange: (value: number) => void;
}) {
  const [value, setValue] = useState(initial);
  useEffect(() => { setValue(initial); }, [initial]);
  return <label>{label} ({value.toFixed(step < .1 ? 2 : 1)})
    <input type="range" min={min} max={max} step={step} value={value}
      onChange={(e) => { const v = Number(e.target.value); setValue(v); onChange(v); }} /></label>;
}
