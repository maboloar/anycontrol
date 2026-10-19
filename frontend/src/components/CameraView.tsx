import { connectVideoObject, fittedVideoRect } from "../videoMapping";
import { BetaBadge } from "./BetaBadge";
import { useEffect, useRef, useState } from "react";
import { CameraBuddy } from "./CameraBuddy";
import { addObject, reselectObject, type AddObjectReq } from "../api";
import { connection, type DecodedFrame } from "../connection";
import {
  calibrationOpacity,
  drawCalibration,
  drawDrag,
  drawHands,
  drawObjects,
  drawPen,
  drawPendingPoint,
  drawTouch,
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
import { t } from "../i18n";
import { sv } from "../serverText";

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
  const floatingOn = useApp((s) => s.floatingCamera);
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
  const calibration = useApp((s) => s.calibration);
  useEffect(() => {
    if (calibration?.calibrated && (calibration.quad || calibration.line)) flashAt.current = performance.now();
    dirtyRef.current = true;
  }, [calibration]);
  const dragRef = useRef<{ start: Norm; end: Norm; shift?: boolean } | null>(null);
  const pendingRef = useRef<Norm | null>(null); // 펜 모드: 첫 번째로 찍은 펜촉
  const [pending, setPending] = useState(false);
  const calibRef = useRef<Norm[]>([]); // 책상 보정: 찍은 종이 모서리
  const pendingFn = useApp(s => s.patchDrag?.from.kind === "fn" ? s.patchDrag.from.id : null);
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
  useEffect(() => { if (pendingFn) setMessage(null); }, [pendingFn]);

  useEffect(() => {
    const cancel = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const app = useApp.getState();
      if (app.reselectId !== null) app.setReselect(null);
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
        if (st.touch && view.devMode && view.touchOverlay) drawTouch(ctx, st.touch, w, h, mirrorRef.current);
      }
      const d = dragRef.current;
      if (d && useApp.getState().selectMode === "object") drawDrag(ctx, d.start, d.end, w, h, mirrorRef.current);
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

  const pointerRect = (canvas: HTMLCanvasElement) => {
    const rect = canvas.getBoundingClientRect();
    return canvas === floatingRef.current ? fittedVideoRect(rect, canvas.width, canvas.height) : rect;
  };
  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (busy || e.button !== 0) return;
    const p = toNorm(e.clientX, e.clientY, pointerRect(e.currentTarget), mirrorRef.current);
    dragRef.current = { start: p, end: p, shift: e.shiftKey };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!dragRef.current) return;
    dragRef.current.end = toNorm(e.clientX, e.clientY, pointerRect(e.currentTarget), mirrorRef.current);
  };
  const connectFromVideo = (e: React.PointerEvent<HTMLCanvasElement>, d: typeof dragRef.current) => {
    const app = useApp.getState(), cable = app.patchDrag;
    if (cable?.from.kind !== "fn" || !app.patchConnect) return false;
    const rect = pointerRect(e.currentTarget);
    const inFrame = e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom;
    const point = toNorm(e.clientX, e.clientY, rect, mirrorRef.current);
    const clicked = !d || selectionFrom(d.start, point, rect).kind === "point";
    const target = clicked && inFrame ? connectVideoObject(point, connection.latestState?.objects ?? app.objects) : undefined;
    if (target) setMessage({ text: t(`${target.name}에 매핑을 연결했습니다.`, `Mapping connected to ${target.name}.`), error: false });
    else {
      app.setPatchDrag({ ...cable, sticky: true, x: e.clientX, y: e.clientY });
      setMessage({ text: t("영상의 등록된 물체를 클릭하세요. 손·배경에는 연결하지 않습니다. ESC 취소.", "Click a registered object in the video. Hands and background are excluded. ESC cancels."), error: false });
    }
    return true;
  };
  const onPointerUp = async (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = dragRef.current;
    dragRef.current = null;
    if (connectFromVideo(e, d)) return;
    if (!d) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const app = useApp.getState();
    const target = app.reselectId === null ? undefined : app.objects.find((o) => o.id === app.reselectId);
    if (target && target.kind === "pen") { // 다시 선택(펜): 등록과 같은 두 점
      const p = toNorm(e.clientX, e.clientY, rect, mirrorRef.current);
      const first = pendingRef.current;
      if (!first) {
        pendingRef.current = p;
        setPending(true);
        setMessage({ text: t("이제 펜의 반대쪽 끝(손잡이 쪽)을 찍으세요. ESC 로 취소.", "Now click the other end of the pen (the grip). ESC cancels."), error: false });
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
        if (obj.kind === "pen") setMessage({ text: t("펜은 [다시 선택] 버튼을 누르고 펜촉·반대쪽 끝 두 점을 찍으세요.", "For a pen, press [Reselect] and click the tip and the other end."), error: true });
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
        setMessage({ text: t("이제 펜의 반대쪽 끝(손잡이 쪽)을 찍으세요. ESC 로 취소.", "Now click the other end of the pen (the grip). ESC cancels."), error: false });
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
    setMessage({ text: "line" in req ? t("펜을 찾는 중…", "Finding the pen…") : t("물체를 분할하는 중…", "Segmenting the object…"), error: false });
    try {
      const obj = await addObject(req);
      useApp.getState().select(obj.id);
      setMessage(obj.warnings.length ? { text: obj.warnings.map(sv).join(" "), error: false } : null);
    } catch (err) {
      setMessage({ text: String(err instanceof Error ? err.message : err).replace(/^\d+ /, ""), error: true });
    } finally {
      setBusy(false);
    }
  };

  const reselect = async (id: number, req: AddObjectReq) => {
    useApp.getState().setReselect(null);
    setBusy(true);
    setMessage({ text: t("다시 분할하는 중…", "Re-segmenting…"), error: false });
    try {
      const obj = await reselectObject(id, req);
      useApp.getState().select(obj.id);
      setMessage({ text: `${obj.name}: ${t("모양을 새로 기억했습니다.", "New shape remembered.")}${obj.warnings.length ? " " + obj.warnings.map(sv).join(" ") : ""}`, error: false });
    } catch (err) {
      setMessage({ text: `${t("다시 선택 실패", "Reselect failed")}: ${String(err instanceof Error ? err.message : err).replace(/^\d+ /, "")}`, error: true });
    } finally {
      setBusy(false);
    }
  };

  const hint = pendingFn
    ? t("케이블을 연결할 등록 물체를 영상에서 클릭하세요. 연결선은 물체 카드 잭에 이어집니다. ESC 취소.", "Click a registered object in the video to connect this cable to its card jack. ESC cancels.")
    : reselectObj
    ? reselectObj.kind === "pen"
      ? pending
        ? t(`다시 선택 (${reselectObj.name}): 펜의 반대쪽 끝(손잡이 쪽)을 찍으세요. ESC 취소.`, `Reselect (${reselectObj.name}): click the other end of the pen (the grip). ESC cancels.`)
        : t(`다시 선택 (${reselectObj.name}): 먼저 펜촉을 찍으세요. ESC 취소.`, `Reselect (${reselectObj.name}): click the pen tip first. ESC cancels.`)
      : t(`다시 선택 (${reselectObj.name}): 물체를 드래그해서 감싸거나 클릭하세요. ESC 취소.`, `Reselect (${reselectObj.name}): drag around or click the object. ESC cancels.`)
    : selectMode === "pen"
      ? pending
        ? t("펜의 반대쪽 끝(손잡이 쪽)을 찍으세요.", "Click the other end of the pen (the grip).")
        : t("펜 등록: 먼저 펜촉(책상에 닿는 끝)을 찍으세요.", "Register pen: click the tip (the end touching the desk) first.")
      : t("추적할 물체를 드래그해서 감싸거나, 물체 위를 클릭하세요. (Shift+드래그 = 선택된 물체 다시 선택)", "Drag around an object to track, or click on it. (Shift+drag = reselect the selected object)");

  const conn = useApp((s) => s.conn);
  const status = useApp((s) => s.telemetry?.source?.status);
  const error = useApp((s) => s.telemetry?.source?.error);
  const size = useApp((s) => s.frameSize);
  const paused = useApp((s) => s.telemetry?.source?.paused);
  const floorOverlay = useApp((s) => (s.devMode && s.floorOverlay ? s.floorMap?.overlay : undefined));
  const depthOverlay = useApp((s) => (s.devMode && s.depthMapOverlay && s.depthMap?.ready ? s.depthMap.overlay : undefined));
  const previewMirror = useApp((s) => s.previewMirror);
  const depthOpacity = useApp((s) => s.depthMapOpacity);

  return (
    <>
    <Panel title={t("카메라 미리보기", "Camera preview")} label="카메라 미리보기" className="camera-panel" info={t(<>영상에서 물체를 <b>드래그·클릭</b>해 등록합니다. 아래로 스크롤해
      영상이 1/3 이상 가려지면 작은 실시간 영상이 뜹니다. 그 창은 제목 줄을 끌어 옮길 수 있습니다.</>,
      <><b>Drag or click</b> objects in the video to register them. When you scroll and over a third of the video is hidden, a small live view appears; drag its title bar to move it.</>)}>
    <div className="camera-col">
      <div data-tour="tools"><CameraTools /></div>
      <div ref={viewRef} data-tour="camera" className="camera-view" style={size ? { aspectRatio: `${size.width} / ${size.height}` } : undefined}>
        <canvas
          ref={canvasRef}
          data-video-map-target
          aria-label={t("카메라 미리보기. 물체를 드래그하거나 클릭해 등록합니다.", "Camera preview. Drag or click an object to register it.")}
          role="img"
          className={`${busy ? "busy" : ""} ${reselectObj ? "reselecting" : ""} ${pendingFn ? "mapping-target" : ""}`}
          onPointerDown={onPointerDown}
          onPointerEnter={(e) => jelly(e.currentTarget)}
          onAnimationEnd={(e) => { if (e.animationName === "egg-jelly") e.currentTarget.classList.remove("jelly"); }}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={() => (dragRef.current = null)}
        />
        {floorOverlay && <img className="floor-overlay" src={floorOverlay} alt="" aria-hidden="true"
          style={previewMirror ? { transform: "scaleX(-1)" } : undefined} />}
        {depthOverlay && <img className="depth-overlay" src={depthOverlay} alt="" aria-hidden="true"
          style={{ opacity: depthOpacity, ...(previewMirror ? { transform: "scaleX(-1)" } : {}) }} />}
        {(conn !== "open" || status !== "running") && (
          <div className="camera-overlay" role="status">
            {conn !== "open" ? t("백엔드에 연결 중…", "Connecting to backend…") : status === "off"
              ? <span className="camera-offline"><CameraBuddy size={40} sleeping />{t("카메라 오프라인", "Camera offline")}</span>
              : (error ? sv(error) : t(`카메라 상태: ${status ?? "알 수 없음"}`, `Camera status: ${status ?? "unknown"}`))}
          </div>
        )}
        {paused && status === "running" && <span className="camera-badge">{t("일시정지 · 등록 상태 유지", "Paused · registrations kept")}</span>}
      </div>
      <div className="row select-mode" role="radiogroup" aria-label={t("등록 방식", "Selection mode")}>
        <button type="button" role="radio" aria-checked={selectMode === "object"}
          className={selectMode === "object" ? "active" : ""} data-tour="select-object"
          onClick={() => { setMessage(null); useApp.getState().setSelectMode("object"); }}>{t("물체 (드래그·클릭)", "Object (drag / click)")}</button>
        <Info>{t(<>물체를 드래그로 감싸거나 클릭하면 AI가 윤곽을 따서 추적을 시작합니다. 이때 <b>모양·색을 기억</b>해서 놓쳐도 다시 찾습니다. 최대 6개.</>, <>Drag around or click an object and the AI outlines it and starts tracking. Its <b>shape and color are remembered</b> to re-find it. Up to 6.</>)}</Info>
        <button type="button" role="radio" aria-checked={selectMode === "pen"}
          className={selectMode === "pen" ? "active" : ""} data-tour="select-pen"
          onClick={() => { setMessage(null); useApp.getState().setSelectMode("pen"); }}>{t("펜 (두 점)", "Pen (two points)")}<BetaBadge /></button>
        <Info>{t("펜촉(책상에 닿는 끝)을 먼저, 반대쪽 끝을 나중에 찍습니다. 펜촉이 책상에 닿으면 그리기·클릭으로 씁니다.", "Click the tip (the end touching the desk) first, then the other end. Touching the desk draws or clicks.")}</Info>
        <p className={`hint ${message?.error ? "error" : ""}`} role="status" aria-live="polite">
          {message?.text ?? hint}
        </p>
      </div>
    </div>
    </Panel>
    {floating && floatingOn && <div className={`floating-camera ${floatingMinimized ? "minimized" : ""}`} aria-label={t("고정 카메라 미리보기", "Pinned camera preview")} style={{ ...floatingResize.style, ...floatingDrag.style, ...(floatingMinimized ? { height: undefined } : {}) }}>
      <div className="floating-header" {...floatingDrag.handlers} title={t("끌어서 옮기기 · 두 번 클릭하면 오른쪽 아래로", "Drag to move · Double-click to return to the bottom right")}>
        <span>⠿ {t("실시간 카메라", "Live camera")}{paused ? t(" · 일시정지", " · Paused") : ""}</span>
        <button type="button" className="minimize" aria-label={t(`실시간 카메라 ${floatingMinimized ? "펼치기" : "최소화"}`, `${floatingMinimized ? "Expand" : "Collapse"} live camera`)}
          aria-expanded={!floatingMinimized} onClick={() => {
            const next = !floatingMinimized; floatingMinimizedRef.current = next; setFloatingMinimized(next); dirtyRef.current = true;
          }}>{floatingMinimized ? "+" : "−"}</button>
      </div>
      <canvas ref={floatingRef} hidden={floatingMinimized} data-video-map-target role="img"
        aria-label={t("실시간 카메라. 기능 잭에서 집은 케이블을 영상의 물체에 연결할 수 있습니다.", "Live camera. Connect a held function cable to an object in the video.")}
        className={pendingFn ? "mapping-target" : ""}
        onPointerDown={e => { if (useApp.getState().patchDrag?.from.kind === "fn") onPointerDown(e); }}
        onPointerMove={onPointerMove} onPointerUp={e => { const d = dragRef.current; dragRef.current = null; connectFromVideo(e, d); }}
        onPointerCancel={() => { dragRef.current = null; }} />
      {!floatingMinimized && <ResizeHandle label={t("실시간 카메라", "Live camera")} grip={floatingResize.grip} />}
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
export function clampFloating(p: Pos, size: { width: number; height: number }, vp: { width: number; height: number }, minTop = 8): Pos {
  const m = 8;
  return {
    left: Math.round(Math.max(m, Math.min(p.left, vp.width - size.width - m))),
    top: Math.round(Math.max(minTop, Math.min(p.top, vp.height - Math.min(size.height, 40) - m))),
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
  /** 실제 입력 상단바가 고정되어 있으면 그 아래까지만 올릴 수 있다 */
  const bannerBottom = () => Math.max(8, (document.querySelector(".topbar.real-active")?.getBoundingClientRect().bottom ?? 0) + 8);
  const move = (el: HTMLElement, p: Pos) => {
    const r = el.getBoundingClientRect();
    const next = clampFloating(p, r, vp(), bannerBottom());
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
    const onResize = () => setPos((p) => (p ? clampFloating(p, { width: 220, height: 40 }, vp(), bannerBottom()) : p));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [pos]);
  const style: React.CSSProperties = pos ? { left: pos.left, top: `max(${pos.top}px, var(--float-min-top, 0px))`, right: "auto", bottom: "auto" } : {};
  return { style, handlers };
}

/** 이스터에그 모드에서 마우스가 영상 위로 들어오면 한 번 젤리처럼 출렁인다 */
function jelly(el: HTMLElement) {
  if (!document.documentElement.classList.contains("rainbow-mode")) return;
  el.classList.remove("jelly");
  void el.offsetWidth; // 애니메이션을 처음부터 다시 시작
  el.classList.add("jelly");
}
