import type { MouseState } from './protocol';
export function positionTarget(mouse: MouseState | null): { x: number; y: number } | undefined {
  if (!mouse || mouse.mode === 'off' || mouse.cursor_active !== true || !Number.isFinite(mouse.x) || !Number.isFinite(mouse.y)) return;
  return { x: Math.max(0, Math.min(1, mouse.x)), y: Math.max(0, Math.min(1, mouse.y)) };
}
