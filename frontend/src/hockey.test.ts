import { expect, it } from "vitest";
import { HH, HW, MALLET, PUCK, RAIL, newHockey, stepHockey } from "./hockey";
const home = [{ x: HW * .24, y: HH / 2 }, { x: HW * .76, y: HH / 2 }] as [{ x: number; y: number }, { x: number; y: number }];
it('keeps two independently controlled mallets in their own halves', () => {
  let g = newHockey('2p');
  for (let i = 0; i < 30; i++) g = stepHockey(g, [{ x: -100, y: -100 }, { x: 1000, y: 1000 }], .03);
  expect(g.mallets[0].x).toBeCloseTo(RAIL + MALLET); expect(g.mallets[0].y).toBeCloseTo(RAIL + MALLET);
  expect(g.mallets[1].x).toBeCloseTo(HW - RAIL - MALLET); expect(g.mallets[1].y).toBeCloseTo(HH - RAIL - MALLET);
});
it('bounces a fast puck off a circular mallet without tunneling', () => {
  let g = newHockey('2p'); g.serve = 0; g.puck = { x: 215, y: HH / 2, vx: -1000, vy: 0 };
  g = stepHockey(g, home, .05);
  expect(g.hits).toBe(1); expect(g.puck.vx).toBeGreaterThan(0); expect(g.points).toEqual([0, 0]);
});
it('goals score only through the opening and the seventh goal finishes the game', () => {
  let g = newHockey('2p'); g.serve = 0; g.puck = { x: 40, y: 70, vx: -700, vy: 0 };
  g = stepHockey(g, home, .03); expect(g.points).toEqual([0, 0]); expect(g.puck.vx).toBeGreaterThan(0);
  g.points = [6, 0]; g.puck = { x: HW + PUCK - 1, y: HH / 2, vx: 700, vy: 0 };
  g = stepHockey(g, home, .03); expect(g.points).toEqual([7, 0]); expect(g.over).toBe(true); expect(g.winner).toBe(0);
});
it('single-player AI moves and the simulation stays finite during extended play', () => {
  let g = newHockey();
  for (let i = 0; i < 3000; i++) g = stepHockey(g, [{ x: HW / 2 + 130 * Math.sin(i / 30), y: 325 }, home[1]], 1 / 60);
  for (const p of [g.puck, ...g.mallets]) expect([p.x, p.y, p.vx, p.vy].every(Number.isFinite)).toBe(true);
  expect(g.mallets[1].x).toBeGreaterThanOrEqual(HW / 2 + MALLET);
});

it('makes normal AI a little slower and exposes distinct easy/normal/hard movement limits', () => {
  const speeds = (['easy', 'normal', 'hard'] as const).map(d => {
    const g = newHockey('pc', d); g.puck = { x: 580, y: 80, vx: 0, vy: 0 };
    const next = stepHockey(g, home, .05);
    return Math.hypot(next.mallets[1].vx, next.mallets[1].vy);
  });
  expect(speeds[0]).toBeCloseTo(270); expect(speeds[1]).toBeCloseTo(360); expect(speeds[2]).toBeCloseTo(420);
  expect(newHockey().difficulty).toBe('normal');
});
