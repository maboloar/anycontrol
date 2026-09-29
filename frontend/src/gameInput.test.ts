import { expect, it } from 'vitest';
import { positionTarget } from './gameInput';
import { newSurvival, stepSurvival } from './survival';
import type { MouseState } from './protocol';
const mouse: MouseState = { mode: 'object', cursor_active: true, x: .8, y: .2, left: false, right: false, scroll: 0, events: [] };
it('position control sets the player before pickups and does not turn it into velocity', () => {
  const g = newSurvival(); g.cells = [{ x: 512, y: 80 }];
  const next = stepSurvival(g, 0, 0, false, .016, () => .5, positionTarget(mouse));
  expect([next.x, next.y]).toEqual([512, 80]);
  expect(next.carrying).toBe(1);
  const again = stepSurvival(next, 0, 0, false, .016, () => .5, positionTarget(mouse));
  expect([again.x, again.y]).toEqual([512, 80]);
});
it('loss, paused/stale null cursor and nonfinite inputs do not move the player', () => {
  for (const m of [null, { ...mouse, cursor_active: false }, { ...mouse, mode: 'off' as const }, { ...mouse, x: NaN }]) {
    expect(positionTarget(m)).toBeUndefined();
    const next = stepSurvival(newSurvival(), 0, 0, false, .016, () => .5, positionTarget(m));
    expect([next.x, next.y]).toEqual([320, 200]);
  }
});
it('position control stays inside the arena', () => {
  const next = stepSurvival(newSurvival(), 0, 0, false, .016, () => .5, positionTarget({ ...mouse, x: -2, y: 2 }));
  expect([next.x, next.y]).toEqual([14, 386]);
});
