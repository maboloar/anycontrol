import { useEffect, useRef, useState } from 'react';
import { useApp } from '../store';
import { padFromState, ZERO } from './GamepadView';
import { connection } from '../connection';
import type { FrameState } from '../protocol';

/** 키 입력은 게임 영역에 초점이 있을 때만 수집한다. 숨김·포커스 이탈·ESC 때 정지한다. */
export function useGameSession<T extends { score: number; over: boolean }>(key: string, create: () => T) {
  const conn = useApp(s => s.conn);
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
    if (savedBest.current === bestRef.current || !force && now - savedAt.current < 1000) return;
    try { localStorage.setItem(key, String(bestRef.current)); savedBest.current = bestRef.current; savedAt.current = now; } catch { /* 저장 실패는 플레이를 막지 않는다 */ }
  };
  const pause = () => { keys.current.clear(); pausedRef.current = true; setPaused(true); publish(performance.now(), true); };
  const play = (restart = false) => {
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
  const inputActive = () => connected.current && padRef.current.sent && performance.now() - padTime.current < 500;
  const control = (name: string) => keys.current.has(name) || (inputActive() && padRef.current.keys.some(k => k.toLowerCase() === (name === ' ' ? 'space' : name.toLowerCase())));
  const handlers = {
    onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => {
      if (e.target === canvas.current) root.current?.focus();
    },
    onKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.target !== e.currentTarget) return;
      const k = e.key.toLowerCase();
      if (['arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'w', 'a', 's', 'd', ' ', 'p'].includes(k)) {
        e.preventDefault();
        if (k === 'p' && !e.repeat) { if (pausedRef.current) play(); else pause(); }
        else keys.current.add(k);
      }
      if (k === 'escape') pause();
    },
    onKeyUp: (e: React.KeyboardEvent<HTMLDivElement>) => { keys.current.delete(e.key.toLowerCase()); },
    onBlur: (e: React.FocusEvent<HTMLDivElement>) => { if (!e.currentTarget.contains(e.relatedTarget)) pause(); },
  };
  const cursorInput = () => connected.current && performance.now() - padTime.current < 500 && !frameRef.current?.paused ? frameRef.current?.mouse ?? null : null;
  return { cursorInput, root, canvas, game, snapshot, paused, pausedRef, padRef, inputActive, best, keys, pause, play, publish, control, handlers };
}

/** 정지 중에는 한 번만 그린다. 패널 숨김·게임 종료도 프레임 예약을 끝낸다. */
export function useGameLoop<T extends { score: number; over: boolean }>(
  session: ReturnType<typeof useGameSession<T>>,
  step: (dt: number) => void,
  draw: (canvas: HTMLCanvasElement | null, game: T, paused: boolean) => void,
) {
  useEffect(() => {
    const s = session;
    if (s.paused) { draw(s.canvas.current, s.game.current, true); return; }
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
