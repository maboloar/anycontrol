import { expect, it } from 'vitest';
import { newSurvival, stepSurvival } from './survival';
it('normalizes diagonal movement and contains the player in the arena', () => {
  const start = newSurvival();
  const a = stepSurvival(start, 1, 0, false, .05), b = stepSurvival(start, 1, 1, false, .05);
  expect(Math.hypot(b.x - start.x, b.y - start.y)).toBeCloseTo(a.x - start.x);
  const edge = stepSurvival({ ...start, x: 626, y: 386 }, 1, 1, false, .05);
  expect([edge.x, edge.y]).toEqual([626, 386]);
});
it('collects cells, delivers them at the beacon and heals without exceeding max health', () => {
  let g = newSurvival(); g.hp = 4; g.cells = [{ x: 320, y: 200 }, { x: 320, y: 200 }];
  g = stepSurvival(g, 0, 0, false, .05);
  expect(g.charge).toBe(2); expect(g.carrying).toBe(0); expect(g.hp).toBe(5); expect(g.score).toBe(300);
  expect(g.cells).toHaveLength(0);
});
it('pulse kills nearby zombies, awards score and respects its cooldown', () => {
  let g = newSurvival();
  g.zombies = [1, 2, 3].map(id => ({ id, x: 340 + id, y: 200, hp: 2, fast: false }));
  g = stepSurvival(g, 0, 0, true, .05);
  expect(g.kills).toBe(3); expect(g.pulseIn).toBe(6); expect(g.zombies).toHaveLength(0);
  expect(g.cells.length + g.carrying + g.charge).toBe(3); // 시작 전지 2개 + 처치 보상 1개
  g.zombies = [{ id: 8, x: 400, y: 200, hp: 2, fast: false }];
  g = stepSurvival(g, 0, 0, true, .05);
  expect(g.zombies).toHaveLength(1);
});
it('requires both survival time and charge for rescue and freezes completed games', () => {
  let g = { ...newSurvival(), time: 90, charge: 7 };
  expect(stepSurvival(g, 0, 0, false, .05).won).toBe(false);
  g.charge = 8;
  const win = stepSurvival(g, 0, 0, false, .05);
  expect(win.won && win.over).toBe(true);
  expect(win.score).toBeGreaterThan(3000);
  expect(stepSurvival(win, 1, 0, true, .05)).toBe(win);
});
it('damage has invulnerability, death ends the game, and automatic shots hit targets', () => {
  let g = newSurvival(); g.hp = 1;
  g.zombies = [{ id: 1, x: g.x + 5, y: g.y, hp: 2, fast: false }];
  g = stepSurvival(g, 0, 0, false, .05);
  expect(g.hp).toBe(0); expect(g.over).toBe(true);
  let shot = newSurvival(); shot.zombies = [{ id: 1, x: 400, y: 200, hp: 1, fast: false }];
  for (let i = 0; i < 30; i++) shot = stepSurvival(shot, 0, 0, false, .02, () => .5);
  expect(shot.kills).toBe(1);
});
