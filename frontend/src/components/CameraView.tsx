import { useEffect, useRef, useState } from "react";
import { addObject, putCalibration, putLineCalibration, reselectObject, type AddObjectReq } from "../api";
import { connection, type DecodedFrame } from "../connection";
import {
  calibrationOpacity,
  drawCalibration,
  drawDrag,
  drawHands,
  drawObjects,
  drawPen,
  drawPendingPoint,
  selectionFrom,
  toNorm,
  type Norm,
} from "../overlay";
import { Rolling } from "../rolling";
import { useApp } from "../store";
import { ResizeHandle, useResizable } from "./useResizable";
import { CameraTools } from "./CameraTools";
import { Panel } from "./Panel";
import { Info } from "./Info";

/**
 * 카메라 미리보기 + 추적 오버레이 + 물체 선택(드래그 = 박스, 클릭 = 점).
 * 최신 비트맵을 rAF 에서 그린다. 그리는 순간 - 캡처 시각 = glass latency.
 */
export function CameraView() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewRef = useRef<HTMLDivElement>(null);
  const floatingRef = useRef<HTMLCanvasElement>(null);
  const floatingResize = useResizable('anycontrol.floating-camera.size', { floating: true });
  const floatingDrag = useFloatingDrag();
  const [floating, setFloating] = useState(false);
  const [floatingMinimized, setFloatingMinimized] = useState(false);
  const floatingMinimizedRef = useRef(false);
  useEffect(() => {
    const reset = () => { floatingMinimizedRef.current = false; setFloatingMinimized(false); dirtyRef.current = true; };
    window.addEventListener('anycontrol.layout.reset', reset);
    return () => window.removeEventListener('anycontrol.layout.reset', reset);
  }, []);
  const mirrorRef = useRef(false);
  const dirtyRef = useRef(true);
  const flashAt = useRef(-Infinity);
  const showCalibrationRef = useRef(false);
  const [showCalibration, setShowCalibration] = useState(false);
  const calibration = useApp((s) => s.calibration);
  useEffect(() => {
    if (calibration?.calibrated && (calibration.quad || calibration.line)) flashAt.current = performance.now();
    dirtyRef.current = true;
  }, [calibration]);
  const dragRef = useRef<{ start: Norm; end: Norm; shift?: boolean } | null>(null);
  const pendingRef = useRef<Norm | null>(null); // 펜 모드: 첫 번째로 찍은 펜촉
  const [pending, setPending] = useState(false);
  const calibRef = useRef<Norm[]>([]); // 책상 보정: 찍은 종이 모서리
  const selectMode = useApp((s) => s.selectMode);
  const reselectId = useApp((s) => s.reselectId);
  const reselectObj = useApp((s) => (s.reselectId === null ? undefined : s.objects.find((o) => o.id === s.reselectId)));

  useEffect(() => {
    pendingRef.current = null;
    setPending(false);
    calibRef.current = []; // 모드가 바뀌면(마우스 패널의 [종이 선택] 등 밖에서 바꿔도) 찍던 점을 버린다
  }, [selectMode, reselectId]);
  useEffect(() => {
    if (reselectId !== null && !reselectObj) useApp.getState().setReselect(null); // 다시 선택 중 물체가 삭제됨
  }, [reselectId, reselectObj]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);

  useEffect(() => {
    const cancel = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const app = useApp.getState();
      if (app.reselectId !== null) app.setReselect(null);
      if (app.selectMode === "calib" || app.selectMode === "calib-line") app.setSelectMode("object"); // 종이·수평 찍기 취소
      dragRef.current = null;
      pendingRef.current = null;
      calibRef.current = [];
      setPending(false);
      setMessage(null);
    };
    window.addEventListener("keydown", cancel);
    return () => window.removeEventListener("keydown", cancel);
  }, []);

  // 스크롤해서 영상 자리가 1/3 이상 위로 가려지면 고정 카메라를 띄운다.
  // 원래 자리는 그대로 남으므로 같은 기준으로 다시 돌아온다 (레이아웃 점프 없음).
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    let raf = 0;
    const check = () => {
      raf = 0;
      setFloating(isPartlyHidden(view.getBoundingClientRect()));
    };
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(check); };
    check();
    window.addEventListener("scroll", onScroll, { passive: true, capture: true });
    window.addEventListener("resize", onScroll);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll, { capture: true });
      window.removeEventListener("resize", onScroll);
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) return;
    let latest: DecodedFrame | null = null;
    let current: ImageBitmap | null = null;
    let sourceMirror = false;
    let lastView = "";
    let raf = 0;
    const glass = new Rolling(120);
    const intervals = new Rolling(60);
    let lastDraw = 0;
    let lastReport = 0;
    let lastCalibrationOpacity = 0;

    const off = connection.onFrame((f) => {
      latest?.bitmap.close();
      latest = f;
    });

    const draw = () => {
      raf = requestAnimationFrame(draw);
      const f = latest;
      const view = useApp.getState();
      const viewKey = JSON.stringify([view.viewFlip, view.overlays]);
      if (viewKey !== lastView) { dirtyRef.current = true; lastView = viewKey; }
      mirrorRef.current = sourceMirror !== view.viewFlip;
      const opacity = calibrationOpacity(performance.now(), flashAt.current, showCalibrationRef.current);
      if (f) {
        latest = null;
        const { width, height } = f.header;
        sourceMirror = Boolean(f.header.flags & 1);
        mirrorRef.current = sourceMirror !== view.viewFlip;
        if (useApp.getState().previewMirror !== mirrorRef.current) useApp.getState().setPreviewMirror(mirrorRef.current);
        if (canvas.width !== width || canvas.height !== height) {
          canvas.width = width;
          canvas.height = height;
          useApp.getState().setFrameSize({ width, height });
        }
        current?.close();
        current = f.bitmap;
        const now = performance.now();
        glass.add(Date.now() - f.header.tWallMs);
        if (lastDraw) intervals.add(now - lastDraw);
        lastDraw = now;
        if (now - lastReport > 250) {
          lastReport = now;
          const iv = intervals.quantile(0.5);
          useApp.getState().setClient({
            glassP50: round1(glass.quantile(0.5)),
            glassP95: round1(glass.quantile(0.95)),
            renderFps: iv ? Math.round((1000 / iv) * 10) / 10 : null,
          });
        }
      } else if (!dragRef.current && !pendingRef.current && !calibRef.current.length && !dirtyRef.current && opacity === lastCalibrationOpacity) {
        return; // 새 프레임도 드래그도 없으면 다시 그릴 필요 없음
      }
      if (!current) return;
      dirtyRef.current = false;
      lastCalibrationOpacity = opacity;
      const w = canvas.width;
      const h = canvas.height;
      mirrorRef.current = sourceMirror !== view.viewFlip;
      if (view.previewMirror !== mirrorRef.current) view.setPreviewMirror(mirrorRef.current);
      ctx.save();
      if (view.viewFlip) { ctx.translate(w, 0); ctx.scale(-1, 1); }
      ctx.drawImage(current, 0, 0);
      ctx.restore();
      const st = connection.latestState;
      if (st) {
        drawCalibration(ctx, useApp.getState().calibration, w, h, opacity, mirrorRef.current);
        if (view.overlays.objects) drawObjects(ctx, st.objects, useApp.getState().selectedId, w, h, mirrorRef.current);
        if (st.hands && view.overlays.hands) drawHands(ctx, st.hands, w, h, st.mouse?.gesture, mirrorRef.current);
        if (st.pens && st.size && view.overlays.pens) for (const p of Object.values(st.pens)) drawPen(ctx, p, st.size, w, h, mirrorRef.current);
      }
      const d = dragRef.current;
      if (d && useApp.getState().selectMode === "object") drawDrag(ctx, d.start, d.end, w, h, mirrorRef.current);
      if (useApp.getState().selectMode === "calib") drawPaperPath(ctx, calibRef.current, w, h, mirrorRef.current);
      for (const p of calibRef.current) drawPendingPoint(ctx, p, w, h, mirrorRef.current);
      const pend = pendingRef.current;
      if (pend) drawPendingPoint(ctx, pend, w, h, mirrorRef.current);
      const mini = floatingRef.current;
      if (mini && !floatingMinimizedRef.current) {
        if (mini.width !== w || mini.height !== h) { mini.width = w; mini.height = h; }
        mini.getContext("2d")?.drawImage(canvas, 0, 0);
      }
    };
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      off();
      latest?.bitmap.close();
      current?.close();
    };
  }, []);

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (busy || e.button !== 0) return;
    const p = toNorm(e.clientX, e.clientY, e.currentTarget.getBoundingClientRect(), mirrorRef.current);
    dragRef.current = { start: p, end: p, shift: e.shiftKey };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!dragRef.current) return;
    dragRef.current.end = toNorm(e.clientX, e.clientY, e.currentTarget.getBoundingClientRect(), mirrorRef.current);
  };
  const onPointerUp = async (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = dragRef.current;
    dragRef.current = null;
    if (!d) return;
    const rect = e.currentTarget.getBoundingClientRect();
    if (useApp.getState().selectMode === "calib" || useApp.getState().selectMode === "calib-line") {
      const line = useApp.getState().selectMode === "calib-line";
      const pts = [...calibRef.current, toNorm(e.clientX, e.clientY, rect, mirrorRef.current)];
      calibRef.current = pts;
      const needed = line ? 2 : 4;
      if (pts.length < needed) {
        setMessage({ text: line ? "책상 기준선의 반대쪽 끝을 찍으세요." : `📄 종이 모서리 ${pts.length}/4 — ${["", "두", "세", "네"][pts.length]} 번째 모서리를 찍으세요 (순서 무관). ESC 취소.`, error: false });
        return;
      }
      calibRef.current = [];
      setBusy(true);
      try {
        const r = line ? await putLineCalibration(pts) : await putCalibration(pts);
        useApp.getState().setCalibration(r);
        useApp.getState().setSelectMode("object");
        setMessage({ text: line ? "기준선 보정 완료. 수평 촬영에서는 손 크기 변화로 깊이 이동을 보완합니다."
          : r.yaw_ok ? "📄 종이 보정 완료. 이제 종이 = 마우스 패드입니다 (종이는 치워도 됩니다). 책상 좌우·앞뒤·회전 축도 쓸 수 있습니다."
          : "📄 종이 보정 완료. 다만 카메라가 거의 수평이라 책상 위 회전은 부정확합니다 (좌우·앞뒤만 권장). 종이는 치워도 됩니다.", error: !line && !r.yaw_ok });
      } catch (err) {
        setMessage({ text: String(err instanceof Error ? err.message : err).replace(/^\d+ /, ""), error: true });
      } finally {
        setBusy(false);
      }
      return;
    }
    const app = useApp.getState();
    const target = app.reselectId === null ? undefined : app.objects.find((o) => o.id === app.reselectId);
    if (target && target.kind === "pen") { // 다시 선택(펜): 등록과 같은 두 점
      const p = toNorm(e.clientX, e.clientY, rect, mirrorRef.current);
      const first = pendingRef.current;
      if (!first) {
        pendingRef.current = p;
        setPending(true);
        setMessage({ text: "이제 펜의 반대쪽 끝(손잡이 쪽)을 찍으세요. ESC 로 취소.", error: false });
        return;
      }
      pendingRef.current = null;
      setPending(false);
      await reselect(target.id, { line: [first[0], first[1], p[0], p[1]] });
      return;
    }
    if (target) { // 다시 선택(일반 물체): 박스 드래그 또는 한 점
      const sel = selectionFrom(d.start, toNorm(e.clientX, e.clientY, rect, mirrorRef.current), rect);
      await reselect(target.id, sel.kind === "box" ? { box: sel.box } : { point: sel.point });
      return;
    }
    if (d.shift && app.selectMode === "object" && app.selectedId !== null) { // Shift+드래그 = 선택된 물체 다시 선택
      const sel = selectionFrom(d.start, toNorm(e.clientX, e.clientY, rect, mirrorRef.current), rect);
      const obj = app.objects.find((o) => o.id === app.selectedId);
      if (obj && sel.kind === "box") {
        if (obj.kind === "pen") setMessage({ text: "펜은 [다시 선택] 버튼을 누르고 펜촉·반대쪽 끝 두 점을 찍으세요.", error: true });
        else await reselect(obj.id, { box: sel.box });
        return;
      }
    }
    if (useApp.getState().selectMode === "pen") {
      const p = toNorm(e.clientX, e.clientY, rect, mirrorRef.current);
      const first = pendingRef.current;
      if (!first) {
        pendingRef.current = p;
        setPending(true);
        setMessage({ text: "이제 펜의 반대쪽 끝(손잡이 쪽)을 찍으세요. ESC 로 취소.", error: false });
        return;
      }
      pendingRef.current = null;
      setPending(false);
      await register({ line: [first[0], first[1], p[0], p[1]] });
      return;
    }
    const sel = selectionFrom(d.start, toNorm(e.clientX, e.clientY, rect, mirrorRef.current), rect);
    // 이미 등록된 물체를 클릭하면 선택만 한다
    if (sel.kind === "point" && d) {
      const hit = connection.latestState?.objects.find(
        (o) => o.box && sel.point[0] >= o.box[0] && sel.point[0] <= o.box[2] && sel.point[1] >= o.box[1] && sel.point[1] <= o.box[3],
      );
      if (hit) {
        useApp.getState().select(hit.id);
        return;
      }
    }
    await register(sel.kind === "box" ? { box: sel.box } : { point: sel.point });
  };

  const register = async (req: AddObjectReq) => {
    setBusy(true);
    setMessage({ text: "line" in req ? "펜을 찾는 중…" : "물체를 분할하는 중…", error: false });
    try {
      const obj = await addObject(req);
      useApp.getState().select(obj.id);
      setMessage(obj.warnings.length ? { text: obj.warnings.join(" "), error: false } : null);
    } catch (err) {
      setMessage({ text: String(err instanceof Error ? err.message : err).replace(/^\d+ /, ""), error: true });
    } finally {
      setBusy(false);
    }
  };

  const reselect = async (id: number, req: AddObjectReq) => {
    useApp.getState().setReselect(null);
    setBusy(true);
    setMessage({ text: "다시 분할하는 중…", error: false });
    try {
      const obj = await reselectObject(id, req);
      useApp.getState().select(obj.id);
      setMessage({ text: `${obj.name}: 모양을 새로 기억했습니다.${obj.warnings.length ? " " + obj.warnings.join(" ") : ""}`, error: false });
    } catch (err) {
      setMessage({ text: `다시 선택 실패: ${String(err instanceof Error ? err.message : err).replace(/^\d+ /, "")}`, error: true });
    } finally {
      setBusy(false);
    }
  };

  const hint = reselectObj
    ? reselectObj.kind === "pen"
      ? pending
        ? `다시 선택 (${reselectObj.name}): 펜의 반대쪽 끝(손잡이 쪽)을 찍으세요. ESC 취소.`
        : `다시 선택 (${reselectObj.name}): 먼저 펜촉을 찍으세요. ESC 취소.`
      : `다시 선택 (${reselectObj.name}): 물체를 드래그해서 감싸거나 클릭하세요. ESC 취소.`
    : selectMode === "calib-line"
    ? "수평 촬영: 책상 위 좌우 기준선 양 끝을 찍으세요."
    : selectMode === "calib"
    ? "📄 종이 선택: 손·물체를 움직일 자리에 A4 종이를 가로로 놓고, 영상에서 종이의 네 모서리를 찍으세요 (순서 무관). ESC 취소."
    : selectMode === "pen"
      ? pending
        ? "펜의 반대쪽 끝(손잡이 쪽)을 찍으세요."
        : "펜 등록: 먼저 펜촉(책상에 닿는 끝)을 찍으세요."
      : "추적할 물체를 드래그해서 감싸거나, 물체 위를 클릭하세요. (Shift+드래그 = 선택된 물체 다시 선택)";

  const conn = useApp((s) => s.conn);
  const status = useApp((s) => s.telemetry?.source?.status);
  const error = useApp((s) => s.telemetry?.source?.error);
  const size = useApp((s) => s.frameSize);
  const paused = useApp((s) => s.telemetry?.source?.paused);

  return (
    <>
    <Panel title="카메라 미리보기" className="camera-panel" info={<>영상에서 물체를 <b>드래그·클릭</b>해 등록합니다. 아래로 스크롤해
      영상이 1/3 이상 가려지면 작은 실시간 영상이 뜹니다. 그 창은 제목 줄을 끌어 옮길 수 있습니다.</>}>
    <div className="camera-col">
      <div data-tour="tools"><CameraTools /></div>
      <div ref={viewRef} data-tour="camera" className="camera-view" style={size ? { aspectRatio: `${size.width} / ${size.height}` } : undefined}>
        <canvas
          ref={canvasRef}
          aria-label="카메라 미리보기. 물체를 드래그하거나 클릭해 등록합니다."
          role="img"
          className={`${busy ? "busy" : ""} ${reselectObj ? "reselecting" : ""}`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={() => (dragRef.current = null)}
        />
        {(conn !== "open" || status !== "running") && (
          <div className="camera-overlay" role="status">
            {conn !== "open" ? "백엔드에 연결 중…" : status === "off" ? "카메라 꺼짐" : (error ?? `카메라 상태: ${status ?? "알 수 없음"}`)}
          </div>
        )}
        {paused && status === "running" && <span className="camera-badge">일시정지 · 등록 상태 유지</span>}
      </div>
      <div className="row select-mode" role="radiogroup" aria-label="등록 방식">
        <button type="button" role="radio" aria-checked={selectMode === "object"}
          className={selectMode === "object" ? "active" : ""} data-tour="select-object"
          onClick={() => { setMessage(null); useApp.getState().setSelectMode("object"); }}>물체 (드래그·클릭)</button>
        <Info>물체를 드래그로 감싸거나 클릭하면 AI가 윤곽을 따서 추적을 시작합니다. 이때 <b>모양·색을 기억</b>해서 놓쳐도 다시 찾습니다. 최대 6개.</Info>
        <button type="button" role="radio" aria-checked={selectMode === "pen"}
          className={selectMode === "pen" ? "active" : ""} data-tour="select-pen"
          onClick={() => { setMessage(null); useApp.getState().setSelectMode("pen"); }}>펜 (두 점)</button>
        <Info>펜촉(책상에 닿는 끝)을 먼저, 반대쪽 끝을 나중에 찍습니다. 펜촉이 책상에 닿으면 그리기·클릭으로 씁니다.</Info>
        <button type="button" role="radio" aria-checked={selectMode === "calib"}
          className={selectMode === "calib" ? "active" : ""} data-tour="select-calib"
          onClick={() => { setMessage(null); calibRef.current = []; useApp.getState().setSelectMode("calib"); }}>📄 종이 선택 (책상 보정)</button>
        <Info wide>A4 종이를 책상에 가로로 놓고 영상에서 네 모서리를 찍으면, 카메라에 <b>사다리꼴</b>로 보이던 책상이 반듯하게 펴집니다.
          가장자리에서 커서가 비스듬히 가는 문제를 고치고, 책상 좌우·앞뒤 축과 펜 그리기 좌표에도 씁니다. 찍은 뒤 종이는 치워도 됩니다.</Info>
        <button type="button" role="radio" aria-checked={selectMode === "calib-line"}
          className={selectMode === "calib-line" ? "active" : ""}
          onClick={() => { setMessage(null); calibRef.current = []; useApp.getState().setSelectMode("calib-line"); }}>수평 보정 (기준선 2점)</button>
        <Info>카메라가 거의 수평이라 종이가 납작한 띠로 보일 때, 책상 위 좌우 기준선의 양 끝 두 점만 찍습니다.</Info>
        <p className={`hint ${message?.error ? "error" : ""}`} role="status" aria-live="polite">
          {message?.text ?? hint}
        </p>
      </div>
      {calibration?.calibrated && calibration.mode !== "deskview" && <label className="check small">
        <input type="checkbox" checked={showCalibration} onChange={(e) => {
          showCalibrationRef.current = e.target.checked; setShowCalibration(e.target.checked); dirtyRef.current = true;
        }} />{calibration.mode === "line" ? "수평 기준선 표시" : "책상 구역 표시"}</label>}
    </div>
    </Panel>
    {floating && <div className={`floating-camera ${floatingMinimized ? "minimized" : ""}`} aria-label="고정 카메라 미리보기" style={{ ...floatingResize.style, ...floatingDrag.style, ...(floatingMinimized ? { height: undefined } : {}) }}>
      <div className="floating-header" {...floatingDrag.handlers} title="끌어서 옮기기 · 두 번 클릭하면 오른쪽 위로">
        <span>⠿ 실시간 카메라{paused ? " · 일시정지" : ""}</span>
        <button type="button" className="minimize" aria-label={`실시간 카메라 ${floatingMinimized ? "펼치기" : "최소화"}`}
          aria-expanded={!floatingMinimized} onClick={() => {
            const next = !floatingMinimized; floatingMinimizedRef.current = next; setFloatingMinimized(next); dirtyRef.current = true;
          }}>{floatingMinimized ? "+" : "−"}</button>
      </div>
      <canvas ref={floatingRef} aria-hidden="true" hidden={floatingMinimized} />
      {!floatingMinimized && <ResizeHandle label="실시간 카메라" grip={floatingResize.grip} />}
    </div>}
    </>
  );
}

function round1(v: number | null): number | null {
  return v === null ? null : Math.round(v * 10) / 10;
}

/** 영상 자리가 화면 위쪽으로 frac(기본 1/3) 이상 가려졌나 */
export function isPartlyHidden(r: { top: number; height: number }, frac = 1 / 3): boolean {
  return r.height > 0 && -r.top >= r.height * frac;
}

const FLOAT_POS_KEY = "anycontrol.floating-camera.pos";
type Pos = { left: number; top: number };

/** 떠 있는 창을 화면 안에 들어오게 당긴다 (창이 줄어들어도 헤더는 항상 잡을 수 있게) */
export function clampFloating(p: Pos, size: { width: number; height: number }, vp: { width: number; height: number }): Pos {
  const m = 8;
  return {
    left: Math.round(Math.max(m, Math.min(p.left, vp.width - size.width - m))),
    top: Math.round(Math.max(m, Math.min(p.top, vp.height - Math.min(size.height, 40) - m))),
  };
}

/** 떠 있는 실시간 카메라를 헤더로 끌어 옮긴다. 위치는 저장하고 화면 초기화 때 오른쪽 위로 돌아간다. */
function useFloatingDrag() {
  const [pos, setPos] = useState<Pos | null>(() => {
    try {
      const v = JSON.parse(localStorage.getItem(FLOAT_POS_KEY) ?? "null") as Pos | null;
      return v && Number.isFinite(v.left) && Number.isFinite(v.top) ? v : null;
    } catch { return null; }
  });
  const drag = useRef<{ dx: number; dy: number; el: HTMLElement } | null>(null);
  useEffect(() => {
    const reset = () => { setPos(null); try { localStorage.removeItem(FLOAT_POS_KEY); } catch { /* 표시만 */ } };
    window.addEventListener("anycontrol.layout.reset", reset);
    window.addEventListener("anycontrol.resize.reset", reset);
    return () => {
      window.removeEventListener("anycontrol.layout.reset", reset);
      window.removeEventListener("anycontrol.resize.reset", reset);
    };
  }, []);
  const vp = () => ({ width: window.innerWidth, height: window.innerHeight });
  const move = (el: HTMLElement, p: Pos) => {
    const r = el.getBoundingClientRect();
    const next = clampFloating(p, r, vp());
    setPos(next);
    return next;
  };
  const handlers = {
    onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => {
      if (e.button !== 0 || (e.target as HTMLElement).closest("button")) return; // 최소화 버튼은 그대로 누른다
      const el = e.currentTarget.parentElement!;
      const r = el.getBoundingClientRect();
      drag.current = { dx: e.clientX - r.left, dy: e.clientY - r.top, el };
      e.currentTarget.setPointerCapture?.(e.pointerId);
      e.preventDefault();
    },
    onPointerMove: (e: React.PointerEvent<HTMLDivElement>) => {
      const d = drag.current;
      if (d) move(d.el, { left: e.clientX - d.dx, top: e.clientY - d.dy });
    },
    onPointerUp: (e: React.PointerEvent<HTMLDivElement>) => {
      const d = drag.current;
      drag.current = null;
      if (!d) return;
      const next = move(d.el, { left: e.clientX - d.dx, top: e.clientY - d.dy });
      try { localStorage.setItem(FLOAT_POS_KEY, JSON.stringify(next)); } catch { /* 이번 화면에서만 */ }
    },
    onPointerCancel: () => { drag.current = null; },
    onDoubleClick: (e: React.MouseEvent<HTMLDivElement>) => {
      if ((e.target as HTMLElement).closest("button")) return;
      setPos(null);
      try { localStorage.removeItem(FLOAT_POS_KEY); } catch { /* 표시만 */ }
    },
  };
  // 창 크기가 바뀌면 화면 밖으로 나가지 않게 다시 당긴다
  useEffect(() => {
    if (!pos) return;
    const onResize = () => setPos((p) => (p ? clampFloating(p, { width: 220, height: 40 }, vp()) : p));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [pos]);
  const style: React.CSSProperties = pos ? { left: pos.left, top: pos.top, right: "auto" } : {};
  return { style, handlers };
}

/** 종이 선택 중: 찍은 모서리를 점선으로 이어 그린다 (4점이 모이기 전 모양 확인용) */
function drawPaperPath(ctx: CanvasRenderingContext2D, pts: Norm[], w: number, h: number, mirror: boolean) {
  if (pts.length < 2) return;
  ctx.save();
  ctx.strokeStyle = "#4cc9f0";
  ctx.lineWidth = 2;
  ctx.setLineDash([8, 6]);
  ctx.beginPath();
  pts.forEach(([x, y], i) => {
    const px = (mirror ? 1 - x : x) * w;
    if (i) ctx.lineTo(px, y * h); else ctx.moveTo(px, y * h);
  });
  ctx.stroke();
  ctx.restore();
}
