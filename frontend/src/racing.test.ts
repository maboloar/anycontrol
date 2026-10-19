import { describe, expect, it } from "vitest";
import { stepCar, type Car } from "./racing";

const start: Car = { x: 0, speed: 0, dist: 0, heading: 0, crashes: 0 };

describe("racing", () => {
  it("throttle accelerates, brake stops", () => {
    let c = start;
    for (let i = 0; i < 60; i++) c = stepCar(c, 0, 1, 0, 1 / 30);
    expect(c.speed).toBeGreaterThan(1);
    for (let i = 0; i < 60; i++) c = stepCar(c, 0, 0, 1, 1 / 30);
    expect(c.speed).toBe(0);
  });
  it("steering moves sideways and counts leaving the road once", () => {
    let c = { ...start, speed: 2 };
    for (let i = 0; i < 300; i++) c = stepCar(c, 1, 1, 0, 1 / 30);
    expect(c.x).toBe(1);
    expect(c.crashes).toBe(1);
  });
});

import { FINISH, newDuel, newRace, stepDuel, stepRace } from './racing';
it('spawns obstacles with a free lane and awards each coin only once', () => {
  let g = newRace(); g.car.dist = 20;
  g = stepRace(g, 0, 0, 0, .02);
  expect(g.items.filter(i => i.kind === 'barrier')).toHaveLength(1);
  expect(g.items[0]!.x).not.toBe(g.items[1]!.x);
  g.items = [{ id: 9, x: 0, ahead: 0, kind: 'coin' }];
  g = stepRace(g, 0, 0, 0, .02);
  expect(g.coins).toBe(1); expect(g.score).toBe(120);
  g = stepRace(g, 0, 0, 0, .02); expect(g.coins).toBe(1);
});
it('collision grants a brief recovery window and the third hit ends the run', () => {
  let g = newRace();
  for (let n = 0; n < 3; n++) {
    g.invulnerable = 0;
    g.items = [{ id: n, x: 0, ahead: 0, kind: 'barrier' }, { id: 20 + n, x: 0, ahead: 0, kind: 'barrier' }];
    g = stepRace(g, 0, 0, 0, .05);
    expect(g.health).toBe(2 - n);
  }
  expect(g.over).toBe(true);
  expect(stepRace(g, 1, 1, 0, .05)).toBe(g);
  expect(newRace().health).toBe(3);
});

it('two players race the same road and the first to the finish wins', () => {
  let d = newDuel(42);
  d = stepDuel(d, [0, 0], .05);
  expect(d.p[0].seed).toBe(d.p[1].seed);
  d.p[0].car.dist = FINISH - 0.01; d.p[0].car.speed = 2;
  d = stepDuel(d, [0, 0], .05);
  expect(d.over).toBe(true); expect(d.winner).toBe(0);
});
it('a boost pad raises the top speed for a moment', () => {
  let g = newRace(); g.car.speed = 2.9;
  g.items = [{ id: 1, x: 0, ahead: 3, kind: 'boost' }];
  g = stepRace(g, 0, 1, 0, .05);
  expect(g.boost).toBeGreaterThan(1);
  for (let i = 0; i < 10; i++) { g.items = []; g = stepRace(g, 0, 1, 0, .05); }
  expect(g.car.speed).toBeGreaterThan(3);
});
