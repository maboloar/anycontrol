// 미니 레이싱 물리 (순수 함수). x: 도로 가로 위치 -1..1 (벗어나면 이탈), speed: 0..2
export interface Car {
  x: number;
  speed: number;
  dist: number;
  heading: number;
  crashes: number;
}

export function stepCar(c: Car, steer: number, throttle: number, brake: number, dt: number): Car {
  let speed = c.speed + (throttle * 0.8 - brake * 1.6 - 0.15 * c.speed) * dt;
  speed = Math.max(0, Math.min(2, speed));
  const heading = steer * 0.5;
  let x = c.x + Math.sin(heading) * speed * dt * 1.5;
  let crashes = c.crashes;
  if (Math.abs(x) > 1) {
    x = Math.sign(x) * 1;
    if (Math.abs(c.x) <= 1 - 1e-9) crashes += 1;
    speed *= 0.5;
  }
  return { x, speed, dist: c.dist + speed * dt * 30, heading, crashes };
}

export interface RoadItem { id: number; x: number; ahead: number; kind: 'barrier' | 'coin'; }
export interface Race {
  car: Car; items: RoadItem[]; health: number; score: number; coins: number;
  nextSpawn: number; invulnerable: number; nextId: number; over: boolean;
}
export function newRace(): Race {
  return { car: { x: 0, speed: 0, dist: 0, heading: 0, crashes: 0 }, items: [], health: 3,
    score: 0, coins: 0, nextSpawn: 18, invulnerable: 0, nextId: 1, over: false };
}
/** 도로 한 줄에 장애물은 하나만 배치해 항상 통과할 공간을 남긴다. */
export function stepRace(old: Race, steer: number, throttle: number, brake: number, dt: number, random = Math.random): Race {
  if (old.over) return old;
  dt = Math.max(0, Math.min(.05, dt));
  const car = stepCar(old.car, steer, throttle, brake, dt);
  const moved = car.dist - old.car.dist;
  const s: Race = { ...old, car, items: old.items.map(o => ({ ...o, ahead: o.ahead - moved })), invulnerable: Math.max(0, old.invulnerable - dt) };
  const hit = () => {
    if (s.invulnerable > 0) return;
    s.health--; s.invulnerable = 1.3; s.car.speed *= .4;
  };
  if (car.crashes > old.car.crashes) hit();
  for (const item of s.items) {
    if (item.ahead < 4 && item.ahead > -4 && Math.abs(item.x - car.x) < (item.kind === 'coin' ? .23 : .27)) {
      if (item.kind === 'coin') { s.coins++; item.ahead = -20; }
      else { hit(); item.ahead = -20; }
    }
  }
  s.items = s.items.filter(o => o.ahead > -12);
  if (car.dist >= s.nextSpawn) {
    const lane = Math.min(2, Math.floor(random() * 3));
    s.items.push({ id: s.nextId++, x: (lane - 1) * .65, ahead: 105, kind: 'barrier' });
    s.items.push({ id: s.nextId++, x: ((lane + 1 + Math.floor(random() * 2)) % 3 - 1) * .65, ahead: 115, kind: 'coin' });
    s.nextSpawn = car.dist + Math.max(32, 60 - car.dist / 140) + random() * 12;
  }
  s.score = Math.floor(car.dist) + s.coins * 100;
  s.over = s.health <= 0;
  return s;
}
