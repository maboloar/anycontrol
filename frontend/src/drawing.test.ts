import { describe, expect, it } from "vitest";
import { fitStrokes, mapHandStrokes, type Stroke } from "./drawing";

describe("fitStrokes", () => {
  it("keeps aspect ratio, centers, and puts far (large Z) at the top", () => {
    const sq: [number, number][] = [[0, 0], [1, 0], [1, 1], [0, 1]];
    const [s] = fitStrokes([sq], 200, 100, 10);
    const xs = s!.map((p) => p[0]);
    const ys = s!.map((p) => p[1]);
    expect(Math.max(...xs) - Math.min(...xs)).toBeCloseTo(80); // 정사각형 유지 (높이 기준)
    expect(Math.max(...ys) - Math.min(...ys)).toBeCloseTo(80);
    expect(s![2]![1]).toBeLessThan(s![0]![1]); // Z=1 이 위
  });

  it("handles empty input", () => {
    expect(fitStrokes([], 100, 100, 5)).toEqual([]);
  });

  it("can show the near-camera side at the top", () => {
    const [stroke] = fitStrokes([[[0, 0], [0, 1]]], 100, 100, 5, true);
    expect(stroke![0]![1]).toBeLessThan(stroke![1]![1]);
  });
});

describe("mapHandStrokes", () => {
  it("mirrors drawing display without changing saved strokes", () => {
    const stroke: Stroke = [[.2, .3], [.3, .4]];
    const saved = JSON.stringify(stroke);
    const [normal] = mapHandStrokes([stroke], 640, 400, 24, 1.6);
    const [mirrored] = mapHandStrokes([stroke], 640, 400, 24, 1.6, false, true);
    expect(mirrored![0]![0]).toBeCloseTo(640 - normal![0]![0]);
    expect(mirrored![0]![1]).toBe(normal![0]![1]);
    expect(JSON.stringify(stroke)).toBe(saved);
  });
  it("keeps existing strokes fixed as the hand draws elsewhere", () => {
    const stroke: Stroke = [[.2, .3], [.3, .4]];
    const [before] = mapHandStrokes([stroke], 640, 400, 24, 16 / 9);
    const [after] = mapHandStrokes([stroke, [[.9, .9]]], 640, 400, 24, 16 / 9);
    expect(after).toEqual(before);
  });

  it("preserves the camera aspect ratio and can flip vertical movement", () => {
    const stroke: Stroke = [[0, 0], [1, 1]];
    const [mapped] = mapHandStrokes([stroke], 640, 400, 24, 4 / 3);
    expect((mapped![1]![0] - mapped![0]![0]) / (mapped![1]![1] - mapped![0]![1])).toBeCloseTo(4 / 3);
    expect(mapped![1]![1]).toBeGreaterThan(mapped![0]![1]);
    const [flipped] = mapHandStrokes([stroke], 640, 400, 24, 4 / 3, true);
    expect(flipped![1]![1]).toBeLessThan(flipped![0]![1]);
  });
});

import { drawingView } from './drawing';
it('uses the same transform for hover and strokes, and mirrors both consistently', () => {
  const strokes: Stroke[] = [[[0, 1], [.4, 2]]];
  const project = drawingView(strokes, [0, 0], 640, 400, true, false);
  const mirror = drawingView(strokes, [0, 0], 640, 400, true, true);
  expect(project(strokes[0]![1]!)).toEqual(project([.4, 2]));
  expect(mirror([.4, 2])[0]).toBeCloseTo(640 - project([.4, 2])[0]);
  const baseline = project([.2, 1.5]);
  project([200, 100]);
  expect(project([.2, 1.5])).toEqual(baseline); // 떠 있는 커서는 배율을 바꾸지 않는다.
  const empty = drawingView([], [1, 1], 640, 400, true, false);
  expect(empty([1.1, 1])[0]).toBeGreaterThan(empty([1, 1])[0]);
});
