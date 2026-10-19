import { BetaBadge } from "./BetaBadge";
import { ActionIcon } from "./ActionIcon";
import { Panel } from "./Panel";
import { useEffect, useRef, useState } from "react";
import { clearHandDrawing, penAction, putHandDrawing } from "../api";
import { connection } from "../connection";
import { drawingView, mapHandStrokes, type Stroke } from "../drawing";
import type { FrameState } from "../protocol";
import { useApp } from "../store";
import { AutoCalibration, calibrationActive } from './AutoCalibration';
import { t } from '../i18n';
import { Info } from './Info';

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
        if (ev.type === "up" && ev.stroke) { strokes.current.push(ev.stroke); if (strokes.current.length > 300) strokes.current.splice(0, strokes.current.length - 300); }   // 오래 켜 두어도 메모리·그리기 비용이 끝없이 늘지 않게
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
      ctx.fillText(source === 'pen' && !world ? t('영상 위치 · 책상 투영 범위 밖', 'Video position · outside desk projection') :
        raw[0] !== x || raw[1] !== y ? t('위치 · 화면 밖', 'Position · off canvas') : current.current ? t('그리는 중', 'Drawing') : source === 'pen' ? t('펜촉 위치', 'Pen tip') : t('검지 위치', 'Index fingertip'),
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
        ? t('샘플을 저장했습니다. 같은 기울기로 닿음과 떼기를 모두 지정한 뒤 자동 접촉을 사용하세요.', 'Sample saved. Record both touch and lift at the same tilt, then use auto contact.')
        : t("보정 지점을 저장했습니다. 가까운 곳·먼 곳 두 군데 이상 찍으면 정확해집니다.", "Calibration point saved. Record at least one near and one far spot for accuracy.")) : null);
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
    <Panel title={t("펜·맨손 그리기", "Pen & hand drawing")} label="펜·맨손 그리기 데모" badge={source === "pen" ? <BetaBadge /> : undefined} className="demo" info={t(<>등록한 펜의 펜촉이 책상에 닿은 동안, 또는 맨손으로 엄지+검지를 집은 동안 그려집니다. 접촉은 영상으로 추정하므로 보정을 먼저 해 주세요.</>, <>Draws while a registered pen tip touches the desk, or while you pinch thumb and index finger. Contact is estimated from video, so calibrate first.</>)}>
      <div className="row" role="group" aria-label={t("그리기 입력 방식", "Drawing input")}>
        <button type="button" aria-pressed={source === "pen"} className={source === "pen" ? "active" : ""}
          onClick={() => { setSource("pen"); setErr(null); setMsg(null); }}>{t("펜", "Pen")}<BetaBadge /></button>
        <button type="button" aria-pressed={source === "hand"} className={source === "hand" ? "active" : ""}
          onClick={() => { setSource("hand"); setHandEnabled(true); }}>{t("맨손 검지", "Index finger")}</button>
      </div>
      <label className="check small"><input type="checkbox" checked={showTip} onChange={e => {
        setShowTip(e.target.checked);
        try { localStorage.setItem('anycontrol.drawing.crosshair', e.target.checked ? 'on' : 'off'); } catch { /* 선택은 현재 세션에 유지 */ }
      }} />{t("펜촉·검지 위치 십자 표시", "Show crosshair at pen tip / fingertip")}</label>
      <label className="check small"><input type="checkbox" checked={previewMirror} onChange={e => { setDrawingMirror(e.target.checked); previewMirrorRef.current = e.target.checked; draw(); }} />{t("그리기 좌우 반전 (개별)", "Flip drawing horizontally (this pad only)")}</label>
      {showTip && source === 'pen' && live?.uncertain && <p className="small muted">{t("펜촉이 가려져 위치를 확인하는 중입니다.", "Pen tip is hidden; confirming its position.")}</p>}
      {source === "hand" ? (
        <>
          <p className="small muted">{t("엄지와 검지 끝을 맞대면 그리기를 시작하고, 떼면 멈춥니다. 맞댄 상태로 손을 움직이면 검지 끝을 따라 그려집니다. 펜 등록이나 책상 접촉 보정 없이 사용할 수 있습니다.", "Touch thumb and index tips to start drawing; release to stop. The line follows your index fingertip. No pen or desk calibration needed.")}</p>
          <div className="row">
            <label className="check"><input type="checkbox" checked={handEnabled} disabled={conn !== "open"}
              onChange={(e) => setHandEnabled(e.target.checked)} />{t("맨손 그리기 활성화", "Enable hand drawing")}</label>
            <span className={`state ${handEnabled && handLive?.contact ? "state-tracking" : ""}`}>
              {conn !== "open" ? t("연결 대기", "Waiting for connection") : !handEnabled || !handLive?.enabled ? t("그리기 중지", "Drawing stopped")
                : !handLive.hand_visible ? t("손을 카메라에 보여 주세요", "Show your hand to the camera") : handLive.contact ? t("맞댐 (그리는 중)", "Pinched (drawing)") : t("떼어 있음", "Released")}
            </span>
          </div>
          <canvas ref={canvasRef} width={640} height={400} className="drawpad" aria-label={t("검지로 그린 그림", "Drawing made with the index finger")} role="img" />
          <label className="check small"><input type="checkbox" checked={handInvertY}
            onChange={(e) => { handInvertYRef.current = e.target.checked; setHandInvertY(e.target.checked); draw(); }} />
            {t("그리기 상하 반전", "Flip drawing vertically")}</label>
          <button type="button" className="act-danger" onClick={() => void clearHand()}><ActionIcon name="trash" />{t("지우기", "Clear")}</button>
        </>
      ) : pens.length === 0 ? (
        <p className="muted">{t("영상 아래 [펜 (두 점)] 을 누르고, 펜촉 → 반대쪽 끝 순서로 찍어 펜을 등록하세요.", "Press [Pen (two points)] below the video, then click the tip → the other end to register a pen.")}</p>
      ) : (
        <>
          <div className="row">
            {pens.length > 1 && (
              <select aria-label={t("펜 선택", "Select pen")} disabled={calibrating} value={penId ?? ""} onChange={(e) => setPenId(Number(e.target.value))}>
                {pens.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            )}
            <span className={`state ${live?.contact && !live.uncertain ? "state-tracking" : ""}`}>{live?.uncertain ? t("가림 · 입력 대기", "Hidden · waiting") : live?.contact ? t("닿음 (그리는 중)", "Touching (drawing)") : t("떨어짐", "Lifted")}</span>
            <span className="muted small">
              {live?.desk_view
                ? `Desk View · ${live.contact_mode === 'manual' ? t('수동 입력', 'Manual input') : live.calibrated ? t('접촉 보정됨', 'Contact calibrated') : t('접촉 보정 필요', 'Contact needs calibration')} · ${t('닿음', 'touch')} ${live.touch_samples ?? 0} / ${t('떼기', 'lift')} ${live.lift_samples ?? 0}`
                : live?.calibrated ? (live.manual_calibration ? t("수동 보정됨", "Manually calibrated") : t("자동 보정됨", "Auto calibrated")) : t(`자동 보정 중… (${live?.samples ?? 0}/90)`, `Auto calibrating… (${live?.samples ?? 0}/90)`)}
              {live?.height != null ? ` · ${t("높이", "height")} ${live.height.toFixed(1)}px` : ""}
            </span>
          </div>
          {penId !== null && <AutoCalibration kind="pen" objectId={penId} prepare={async () => { stopHolding(); await manualQueue.current; }} />}
          <canvas ref={canvasRef} width={640} height={400} className="drawpad" aria-label={t("펜으로 그린 그림", "Drawing made with the pen")} role="img" />
          <label className="check small"><input type="checkbox" checked={nearUp}
            onChange={(e) => { nearUpRef.current = e.target.checked; setNearUp(e.target.checked); draw(); }} />
            {t("그리기 상하 반전 (카메라 가까운 방향이 위)", "Flip drawing vertically (near camera = up)")}</label>
          <fieldset className="manual-settings" disabled={calibrating} aria-label={t("수동 펜 설정", "Manual pen settings")}>
          <div className="row">
            <button type="button" className="act-danger" onClick={() => act("clear")}><ActionIcon name="trash" />{t("지우기", "Clear")}</button>
            <button type="button" className="act-config" onClick={() => act("touch")} title={t("펜촉을 책상에 댄 채로 누르세요", "Press while the tip touches the desk")}><ActionIcon name="target" />{t("지금 닿아 있음 (보정)", "Touching now (calibrate)")}</button>
            {live?.desk_view && <>
              <button type="button" className="act-config" onClick={() => act('lift')}><ActionIcon name="target" />{t('지금 떼어 있음 (보정)', 'Lifted now (calibrate)')}</button>
              <button type="button" className="act-output" disabled={!live.calibrated || holding} onClick={() => act('auto')}><ActionIcon name="check" />{t("자동 접촉 사용", "Use auto contact")}</button>
              <button type="button" className={`act-output ${holding ? 'active' : ''}`}
                onPointerDown={(e) => { if (e.button !== 0) return; e.currentTarget.setPointerCapture(e.pointerId); startHolding(); }}
                onKeyDown={(e) => { if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) { e.preventDefault(); startHolding(); } }}
                onKeyUp={(e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); stopHolding(); } }}>
                <ActionIcon name="play" />{holding ? t('그리는 중 · 떼면 멈춤', 'Drawing · release to stop') : t('누르는 동안 그리기', 'Hold to draw')}</button>
            </>}
            <button type="button" className="act-reset" onClick={() => act("reset")}><ActionIcon name="reset" />{t("보정 초기화", "Reset calibration")}</button>
            {!live?.desk_view && <>
            <label className="small" htmlFor="horizon">{t("책상 소실선", "Desk horizon")}</label>
            <input id="horizon" type="range" min={0.2} max={0.8} step={0.01} value={live?.horizon ?? 0.5}
              onChange={(e) => void setHorizon(Number(e.target.value))} />
            </>}
          </div>
          {!live?.desk_view && <label className="check small"><input type="checkbox" checked={live?.contact_method !== 'legacy'} onChange={e => { if (penId !== null) void penAction(penId, 'config', { contact_method: e.target.checked ? 'floor' : 'legacy' }).catch(e => setErr(String(e))); }} />{t('바닥 기하 접촉 판정 (기본)', 'Floor-geometry contact detection (default)')}<Info>{t('책상 바닥의 기울기를 Depth Anything V2 Small로 재고 펜 굵기로 닿음을 판정합니다. 끄면 이전의 단순 책상 면 방식을 씁니다.', 'Measures the desk tilt with Depth Anything V2 Small and judges contact from the pen width. Off = the older simple desk-plane method.')}</Info></label>}
          {!live?.desk_view && live?.contact_method !== 'legacy' && <label className="check small"><input type="checkbox" checked={live?.depth_roll?.enabled ?? true} onChange={e => { if (penId !== null) void penAction(penId, 'config', { floor_depth_roll: e.target.checked }).catch(e => setErr(String(e))); }} />{t('책상 기울기를 깊이 모델로 재기 (기본)', 'Measure desk tilt with the depth model (default)')}<Info>{t('Depth Anything V2 Small로 책상의 좌우 기울기를 2초마다 잽니다. 끄면 펜을 책상에 대고 움직이며 배운 기울기를 씁니다 (더 느리게 맞춰지고 덜 정확합니다).', 'Depth Anything V2 Small measures the desk\'s sideways tilt every 2 s. Off = use the tilt learned from sliding the pen on the desk (slower to settle and less accurate).')}</Info></label>}
          {!live?.desk_view && live?.contact_method === 'floor' && live.floor && <p className="small muted" aria-live="polite">
            {live.floor.samples !== undefined && live.floor.samples < 40
              ? t(`책상 면 학습 중 (${live.floor.samples}/40) · 펜을 책상에 대고 앞뒤로 움직여 주세요`, `Learning the desk (${live.floor.samples}/40) · slide the pen near and far on the desk`)
              : t(`높이 ${live.floor.h_s == null ? '-' : live.floor.h_s.toFixed(2)}D${live.floor.holding ? ' · 가림 중 유지' : ''}${live.floor.shadow ? ` · 그림자 ${live.floor.shadow}` : ''}`,
                  `height ${live.floor.h_s == null ? '-' : live.floor.h_s.toFixed(2)}D${live.floor.holding ? ' · holding' : ''}${live.floor.shadow ? ` · shadow ${live.floor.shadow}` : ''}`)}
          </p>}
          {!live?.desk_view && live?.contact_method !== 'floor' && <label className="check small"><input type="checkbox" checked={!!live?.shadow_assist} onChange={e => { if (penId !== null) void penAction(penId, 'config', { shadow_assist: e.target.checked }).catch(e => setErr(String(e))); }} />{t('책상색·그림자로 헛획 시작 줄이기', 'Use desk color and shadow to reduce false strokes')}</label>}
          {live?.shadow_veto && <p className="small muted">{t("펜촉 주변이 책상인지 확인 중 · 획 시작 보류", "Checking the desk around the tip · stroke on hold")}</p>}
          <div className="field">
            {live?.desk_view ? <PenSlider key={`${penId}-desk-margin`} label={t("Desk View 접촉 확신 문턱", "Desk View contact confidence")}
              initial={live.settings?.desk_contact_margin ?? .18} min={0} max={.9} step={.02}
              onChange={(v) => setPenSetting('desk_contact_margin', v)} /> : <>
            <PenSlider key={`${penId}-on`} label={t("펜 접촉 감도", "Pen touch sensitivity")} initial={live?.settings?.touch_on ?? 0.6} min={0.1} max={3} step={0.05}
              onChange={(v) => setPenSetting("touch_on", v)} />
            <PenSlider key={`${penId}-off`} label={t("펜 떼기 문턱", "Pen lift threshold")} initial={live?.settings?.touch_off ?? 1} min={0.15} max={4} step={0.05}
              onChange={(v) => setPenSetting("touch_off", v)} />
            </>}
            <PenSlider key={`${penId}-edge`} label={t("펜촉 경계 탐색 폭", "Tip edge search width")} initial={live?.settings?.edge_span ?? 0.4} min={0} max={1.5} step={0.05}
              onChange={(v) => setPenSetting("edge_span", v)} />
            <PenSlider key={`${penId}-smooth`} label={t("펜촉 안정화", "Tip smoothing")} initial={live?.settings?.tip_min_cutoff ?? 2} min={0.2} max={10} step={0.1}
              onChange={(v) => setPenSetting("tip_min_cutoff", v)} />
            <PenSlider key={`${penId}-speed`} label={t("빠른 움직임 반응", "Fast-motion response")} initial={live?.settings?.tip_beta ?? 1} min={0} max={5} step={0.1}
              onChange={(v) => setPenSetting("tip_beta", v)} />
            <PenSlider key={`${penId}-mask-age`} label={t("마스크 유효 시간", "Mask lifetime")} initial={live?.settings?.refined_max_age ?? 0.35} min={0.05} max={2} step={0.05}
              onChange={(v) => setPenSetting("refined_max_age", v)} />
          </div>
          </fieldset>
          <p className="small muted">
            {live?.desk_view
              ? t('Desk View는 책상 XY를 그대로 사용합니다. 종이 4점을 지정하면 그림 영역을 보정합니다. 동일한 기울기로 펜을 바닥에 1초 대고 닿음 샘플, 2–3cm 들어 1초 유지하고 떼기 샘플을 저장하세요. 여러 위치·기울기도 추가할 수 있습니다. 두 상태의 외형 차이가 작으면 수동 그리기 버튼을 사용하세요. 자동 접촉은 영상 외형에 따른 추정입니다.', 'Desk View uses desk XY directly; a 4-point paper calibration sets the drawing area. At the same tilt, hold the pen on the desk for 1s and save a touch sample, then lift it 2–3cm for 1s and save a lift sample. You can add more positions and tilts. If the two look alike, use the hold-to-draw button. Auto contact is an estimate from appearance.')
              : t('펜을 책상에 대고 몇 초 움직이면 책상 면을 스스로 보정합니다. 그림이 한쪽으로 눌려 보이면 소실선을 조절하세요 (카메라가 수평이면 0.5).', 'Move the pen on the desk for a few seconds to self-calibrate the surface. If the drawing looks squashed, adjust the horizon (0.5 for a level camera).')}
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
