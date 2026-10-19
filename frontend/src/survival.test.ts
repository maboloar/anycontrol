import { expect, it } from 'vitest';
import { newSurvival, stepSurvival, waveSize, type Survival } from './survival';

const quiet = (): Survival => ({ ...newSurvival(), toSpawn: 0, bannerT: 0 });
it('normalizes diagonal movement and contains the player in the arena', () => {
  const start = quiet();
  const a = stepSurvival(start, 1, 0, .05), b = stepSurvival(start, 1, 1, .05);
  expect(Math.hypot(b.x - start.x, b.y - start.y)).toBeCloseTo(a.x - start.x);
  const edge = stepSurvival({ ...start, x: 626, y: 386 }, 1, 1, .05);
  expect([edge.x, edge.y]).toEqual([626, 386]);
});
it('batteries upgrade the weapon to double, spread and rapid fire', () => {
  let g = quiet(); g.zombies = [{ id: 1, x: 600, y: 380, hp: 99, max: 99, kind: 'walker', hit: 0 }];
  g.pickups = [0, 1, 2].map(() => ({ x: g.x, y: g.y, kind: 'battery' as const, life: 5 }));
  g = stepSurvival(g, 0, 0, .05);
  expect(g.power).toBe(1);
  g.fireIn = 0; g.bullets = [];
  g = stepSurvival(g, 0, 0, .01);
  expect(g.bullets.length).toBe(2);                                         // 두 발
});
it('clearing a wave starts a break, then the next, bigger wave', () => {
  let g = quiet();
  g = stepSurvival(g, 0, 0, .05);
  expect(g.breakT).toBeGreaterThan(0);
  for (let i = 0; i < 70; i++) g = stepSurvival(g, 0, 0, .05);
  expect(g.wave).toBe(2); expect(g.toSpawn + g.zombies.length).toBeLessThanOrEqual(waveSize(2));
});
it('surviving the last wave wins and freezes the game', () => {
  let g = { ...quiet(), wave: 8 };
  g = stepSurvival(g, 0, 0, .05);
  expect(g.won && g.over).toBe(true);
  expect(stepSurvival(g, 1, 0, .05)).toBe(g);
});
it('damage has invulnerability, death ends the game, shots hit, bombers explode', () => {
  let g = quiet(); g.hp = 1;
  g.zombies = [{ id: 1, x: g.x + 5, y: g.y, hp: 2, max: 2, kind: 'walker', hit: 0 }];
  g = stepSurvival(g, 0, 0, .05);
  expect(g.hp).toBe(0); expect(g.over).toBe(true);
  let shot = quiet(); shot.zombies = [{ id: 1, x: 400, y: 200, hp: 1, max: 1, kind: 'runner', hit: 0 }];
  for (let i = 0; i < 20; i++) shot = stepSurvival(shot, 0, 0, .05, () => .9);
  expect(shot.kills).toBe(1);
  let boom = quiet(); boom.hp = 5;
  boom.zombies = [{ id: 1, x: boom.x + 20, y: boom.y, hp: 2, max: 2, kind: 'bomber', hit: 0 }, { id: 2, x: boom.x + 50, y: boom.y, hp: 3, max: 3, kind: 'walker', hit: 0 }];
  boom = stepSurvival(boom, 0, 0, .02, () => .9);
  expect(boom.hp).toBe(3); expect(boom.zombies.find((z) => z.id === 2)).toBeUndefined();   // 자폭에 휘말림
});
