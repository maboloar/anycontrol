import { expect, it } from 'vitest';
import { FEVER, newFruit, ROUND, stepFruit } from './fruit';
import { newPong, sizeToPaddle, stepPong } from './pong';
import { newRace, STAGE_LEN, stepRace } from './racing';
import { rng } from './fx';

const net = { a: { x: 100, y: 300 }, b: { x: 300, y: 300 } };

it('fruit: catching scores with combo, a bomb costs a life, power-ups apply', () => {
  let g = newFruit(); g.spawnIn = 99; g.eventIn = 99;
  g.drops = [{ id: 1, x: 200, y: 295, vx: 0, vy: 200, rot: 0, vr: 0, kind: 'apple' }, { id: 2, x: 150, y: 295, vx: 0, vy: 200, rot: 0, vr: 0, kind: 'bomb' },
    { id: 3, x: 250, y: 295, vx: 0, vy: 200, rot: 0, vr: 0, kind: 'magnet' }];
  g = stepFruit(g, net, .05);
  expect(g.caught).toBe(1); expect(g.score).toBe(10); expect(g.lives).toBe(2); expect(g.magnet).toBeGreaterThan(5);
  expect(g.fx.parts.length).toBeGreaterThan(0);
});
it('fruit: an event is announced first, then a waterfall pours from one side', () => {
  const r = rng(3);
  let g = newFruit(); g.eventIn = 0.01;
  g = stepFruit(g, net, .05, r);
  expect(g.event?.warn).toBeGreaterThan(0);
  g.event = { kind: 'waterfall', side: -1, t: 4, warn: 0 }; g.drops = []; g.spawnIn = 0;
  for (let i = 0; i < 20; i++) g = stepFruit(g, net, .05, r);
  expect(g.drops.length).toBeGreaterThan(4);
  expect(g.drops.every((d) => d.x < 260)).toBe(true);                       // 왼쪽에서만
});
it('fruit: the last seconds are fever with double points', () => {
  let g = newFruit(); g.time = ROUND - FEVER + 1; g.spawnIn = 99; g.eventIn = 99;
  g.drops = [{ id: 1, x: 200, y: 295, vx: 0, vy: 200, rot: 0, vr: 0, kind: 'apple' }];
  g = stepFruit(g, net, .05);
  expect(g.score).toBe(20);
});
it('pong: object size moves the paddle, the ball bounces, a multi-ball item adds a ball', () => {
  expect(sizeToPaddle(0.35)).toBe(0); expect(sizeToPaddle(-0.35)).toBe(1); expect(sizeToPaddle(null)).toBeNull();
  let g = newPong('2p'); g.serveIn = 0; g.powerIn = 99;
  g.balls = [{ x: 40, y: 200, vx: -300, vy: 0, trail: [] }];
  g = stepPong(g, .5, .5, .05);
  expect(g.balls[0]!.vx).toBeGreaterThan(0); expect(g.lastHit).toBe(0);
  g.power = { x: g.balls[0]!.x + 15, y: g.balls[0]!.y, kind: 'multi', t: 5 };
  g = stepPong(g, .5, .5, .02);
  expect(g.balls.length).toBe(2);
});
it('racing: oil spins you out, stages advance with distance', () => {
  let g = newRace(); g.car.speed = 2;
  g.items = [{ id: 1, x: 0, ahead: 2, kind: 'oil' }];
  g = stepRace(g, 0, 1, 0, .05);
  expect(g.spin).toBeGreaterThan(0);
  let h = newRace(); h.car.dist = STAGE_LEN - 1; h.car.speed = 2;
  h = stepRace(h, 0, 1, 0, .05);
  expect(h.stage).toBe(1); expect(h.bannerT).toBeGreaterThan(0);
});
