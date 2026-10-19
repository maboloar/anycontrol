import { GAME_AXES } from "../gameFunctions";
import { useEffect, useRef, useState } from 'react';
import { useApp } from '../store';
import { padFromState, ZERO } from './GamepadView';
import { useDraftStore } from "../mappingDraft";
import { connection } from '../connection';
import type { FrameState, ObjectInfo } from '../protocol';

/** 상태 표시용 물체 메타데이터. 물리 조작은 demoControl의 매핑 출력만 사용한다. */
export interface GameObject { id: number; name: string; color: string; x: number; y: number; size: number | null; axes: ObjectInfo['axes'] }
export function gameObjects(state: FrameState | null, mirror: boolean): GameObject[] {
  if (!state) return [];
  return (state.objects ?? []).filter((o) => o.kind !== 'pen' && o.box && (o.state === 'tracking' || o.state === 'grasped'))
    .map((o) => {
      const [x0, y0, x1, y1] = o.box!;
      const cx = (x0 + x1) / 2;
      return { id: o.id, name: o.name, color: o.color, x: mirror ? 1 - cx : cx, y: (y0 + y1) / 2, size: o.axes.depth, axes: o.axes };
    })
    .sort((a, b) => a.x - b.x);
}

/** 키 입력은 게임 영역에 초점이 있을 때만 수집한다. 탭 숨김·창 포커스 이탈·ESC 때 정지한다. 앱 안 매핑 편집 중에는 계속 실행한다. */
export function useGameSession<T extends { score: number; over: boolean }>(key: string, create: () => T, check?: () => string | null) {
  const conn = useApp(s => s.conn);
  const checkRef = useRef(check); checkRef.current = check;
  const [warning, setWarning] = useState("");
  const padRef = useRef(ZERO);
  const frameRef = useRef<FrameState | null>(null);
  const padTime = useRef(-Infinity);
  useEffect(() => connection.onMessage((type, data) => {
    if (type !== 'state') return;
    frameRef.current = data as unknown as FrameState;
    padRef.current = padFromState(data as unknown as FrameState);
    padTime.current = performance.now();
  }), []);
  const connected = useRef(conn === 'open'); connected.current = conn === 'open';
  const root = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const keys = useRef(new Set<string>());
  const [snapshot, setSnapshot] = useState<T>(create);
  const game = useRef<T>(snapshot);
  const [paused, setPaused] = useState(true);
  const pausedRef = useRef(true);
  const [best, setBest] = useState(() => {
    try { const n = Number(localStorage.getItem(key)); return Number.isFinite(n) ? Math.max(0, n) : 0; } catch { return 0; }
  });
  const bestRef = useRef(best);
  const savedBest = useRef(best), savedAt = useRef(-Infinity);
  const saveBest = (now: number, force = false) => {
    if (useApp.getState().resetBusy) return;
    if (savedBest.current === bestRef.current || !force && now - savedAt.current < 1000) return;
    try { localStorage.setItem(key, String(bestRef.current)); savedBest.current = bestRef.current; savedAt.current = now; } catch { /* 저장 실패는 플레이를 막지 않는다 */ }
  };
  const pause = () => { keys.current.clear(); pausedRef.current = true; setPaused(true); publish(performance.now(), true); };
  const play = (restart = false) => {
    const problem = checkRef.current?.();
    if (problem) { setWarning(problem); return; }
    setWarning("");
    if (restart || game.current.over) { game.current = create(); setSnapshot(game.current); }
    keys.current.clear(); pausedRef.current = false; setPaused(false); root.current?.focus();
  };
  const publish = (now = performance.now(), force = false) => {
    setSnapshot(game.current);
    if (game.current.score > bestRef.current) {
      bestRef.current = game.current.score; setBest(bestRef.current);
    }
    saveBest(now, force);
  };
  useEffect(() => {
    const hide = () => { if (document.hidden) pause(); };
    window.addEventListener('blur', pause); window.addEventListener('anycontrol-stop', pause);
    document.addEventListener('visibilitychange', hide);
    return () => { bestRef.current = Math.max(bestRef.current, game.current.score); saveBest(performance.now(), true); window.removeEventListener('blur', pause); window.removeEventListener('anycontrol-stop', pause); document.removeEventListener('visibilitychange', hide); };
  }, []);
  // 보기만 모드에서도 게임은 계산된 매핑 값을 쓴다 (게임은 앱 안의 가상 입력이므로)
  const inputActive = () => connected.current && performance.now() - padTime.current < 500;
  /** 카메라 상태/개수 표시에만 사용하는 물체 목록. 컨트롤러 선택은 실제 케이블을 따른다. */
  const objectsInput = () => connected.current && performance.now() - padTime.current < 500
    ? gameObjects(frameRef.current, useApp.getState().inputMirror) : [];
  // Space = 일시정지/계속 (모든 게임 공통). 입력창·버튼에 초점이 있으면 그쪽에 맡긴다.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== ' ' || e.repeat || !root.current?.getClientRects().length) return;
      const el = e.target instanceof Element ? e.target : null;
      if (el && el !== root.current && el.closest('input, textarea, select, button, [contenteditable=true]')) return;
      e.preventDefault();
      if (pausedRef.current) play(); else pause();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  const control = (name: string) => keys.current.has(name) || (inputActive() && padRef.current.keys.some(k => k.toLowerCase() === (name === ' ' ? 'space' : name.toLowerCase())));
  const handlers = {
    onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => {
      if (e.target === canvas.current) root.current?.focus();
    },
    onKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.target !== e.currentTarget) return;
      const k = e.key.toLowerCase();
      if (k === ' ') { e.preventDefault(); return; }   // Space 는 위 공통 처리(일시정지)
      if (['arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'w', 'a', 's', 'd', 'p', 'i', 'k', 'j', 'l', '1', '2', '3', '4', '5', '6', '7', '8', '9'].includes(k)) {
        e.preventDefault();
        if (k === 'p' && !e.repeat) { if (pausedRef.current) play(); else pause(); }
        else keys.current.add(k);
      }
      if (k === 'escape') pause();
    },
    onKeyUp: (e: React.KeyboardEvent<HTMLDivElement>) => { keys.current.delete(e.key.toLowerCase()); },
    onBlur: (e: React.FocusEvent<HTMLDivElement>) => { if (!e.currentTarget.contains(e.relatedTarget)) keys.current.clear(); },
  };
  const demoControl = (name: string) => {
    if (!inputActive() || frameRef.current?.paused) return 0;
    const p = useDraftStore.getState().draft;
    const axis = GAME_AXES[name];
    if (!axis || !p?.mappings.some(m => m.enabled && m.output.target === "gamepad_axis" && m.output.axis === axis)) return 0;
    return padRef.current.axes[axis] ?? 0;
  };
  const frame = () => frameRef.current;
  return { warning, demoControl, objectsInput, frame, root, canvas, game, snapshot, paused, pausedRef, padRef, inputActive, best, keys, pause, play, publish, control, handlers };
}

/** 정지 중에는 한 번만 그린다. 패널 숨김·게임 종료도 프레임 예약을 끝낸다. */
export function useGameLoop<T extends { score: number; over: boolean }>(
  session: ReturnType<typeof useGameSession<T>>,
  step: (dt: number) => void,
  draw: (canvas: HTMLCanvasElement | null, game: T, paused: boolean) => void,
) {
  useEffect(() => {
    const s = session;
    if (s.paused) {
      const repaint = () => draw(s.canvas.current, s.game.current, true);
      repaint();
      const observer = typeof ResizeObserver !== 'undefined' && s.canvas.current ? new ResizeObserver(repaint) : null;
      if (s.canvas.current) observer?.observe(s.canvas.current);
      window.addEventListener('resize', repaint);
      return () => { observer?.disconnect(); window.removeEventListener('resize', repaint); };
    }
    let raf = 0, last = performance.now(), report = last;
    const loop = (now: number) => {
      if (s.pausedRef.current) return;
      if (!s.root.current?.getClientRects().length) { s.pause(); return; }
      const dt = Math.min(.05, Math.max(0, (now - last) / 1000)); last = now;
      step(dt);
      draw(s.canvas.current, s.game.current, false);
      if (s.game.current.over) { s.pause(); return; }
      if (now - report >= 150) { s.publish(now); report = now; }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [session.paused]);
}
