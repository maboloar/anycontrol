import { describe, expect, it } from "vitest";
import { calibrationOpacity, drawObjects, drawPenSkeleton, selectionFrom, toNorm } from "./overlay";
import type { ObjectInfo, PenSkeleton } from "./protocol";

const rect = { left: 100, top: 50, width: 800, height: 450 } as DOMRect;

describe("toNorm", () => {
  it("maps client coords into 0..1 and clamps outside points", () => {
    expect(toNorm(500, 275, rect)).toEqual([0.5, 0.5]);
    expect(toNorm(0, 1000, rect)).toEqual([0, 1]);
  });
  it("returns canonical selection coordinates for a mirrored preview", () => {
    expect(toNorm(300, 275, rect, true)).toEqual([.75, .5]);
  });
});

it("shows calibration for one second, fades during the next, and supports a persistent toggle", () => {
  expect(calibrationOpacity(1000, 1000, false)).toBe(1);
  expect(calibrationOpacity(1999, 1000, false)).toBe(1);
  expect(calibrationOpacity(2500, 1000, false)).toBe(.5);
  expect(calibrationOpacity(3001, 1000, false)).toBe(0);
  expect(calibrationOpacity(10000, 1000, true)).toBe(1);
});

describe("selectionFrom", () => {
  it("treats a tiny drag as a click", () => {
    expect(selectionFrom([0.5, 0.5], [0.503, 0.502], rect)).toEqual({ kind: "point", point: [0.503, 0.502] });
  });

  it("normalizes a reversed drag into x1<x2, y1<y2", () => {
    expect(selectionFrom([0.6, 0.7], [0.2, 0.3], rect)).toEqual({ kind: "box", box: [0.2, 0.3, 0.6, 0.7] });
  });
});

describe("drawPenSkeleton", () => {
  const calls: string[] = [];
  const dashes: number[][] = [];
  const ctx = new Proxy({}, { get: (_t, k: string) => k === "setLineDash" ? (d: number[]) => { dashes.push(d); } : () => { calls.push(k); }, set: () => true }) as unknown as CanvasRenderingContext2D;
  const sk: PenSkeleton = { tip: [200, 100], tail: [100, 300], state: "tail_hidden", evidence: "skin",
    visible: [[[100, 250], [200, 100]]], hidden: [[[100, 300], [100, 250]]] };
  it("draws visible parts solid and the hidden part dashed, plus both end dots", () => {
    calls.length = 0; dashes.length = 0;
    drawPenSkeleton(ctx, sk, [400, 400], 800, 800);
    expect(calls.filter((c) => c === "lineTo")).toHaveLength(2);
    expect(calls.filter((c) => c === "arc")).toHaveLength(2);
    expect(dashes.some((d) => d.length === 2 && d[0]! > 0)).toBe(true);
  });
});

describe("drawObjects anchor point", () => {
  const make = () => {
    const arcs: number[][] = [];
    const ctx = new Proxy({}, { get: (_t, k: string) => k === "arc" ? (...a: number[]) => { arcs.push(a); } : () => undefined, set: () => true }) as unknown as CanvasRenderingContext2D;
    return { ctx, arcs };
  };
  const obj = (anchor: [number, number] | null): ObjectInfo => ({ id: 1, name: "a", color: "#88f", state: "tracking", confidence: 1, kind: "object",
    box: [.2, .2, .6, .5], contour: [], axes: {}, texture: 0, contrast: 0, warnings: [], candidates: 1, candidate_index: 0, anchor, debug: {} } as unknown as ObjectInfo);
  it("always draws the cursor anchor of each object, mirrored with the view", () => {
    const { ctx, arcs } = make();
    drawObjects(ctx, [obj([.4, .45])], null, 1000, 500);
    expect(arcs.length).toBe(3);                       // 바깥 검은 고리, 채움, 흰 테두리
    expect(arcs[0]![0]).toBeCloseTo(400); expect(arcs[0]![1]).toBeCloseTo(225);
    const m = make();
    drawObjects(m.ctx, [obj([.4, .45])], null, 1000, 500, true);
    expect(m.arcs[0]![0]).toBeCloseTo(600);
  });
  it("draws nothing while the object (and so the anchor) is not visible", () => {
    const { ctx, arcs } = make();
    drawObjects(ctx, [obj(null)], null, 1000, 500);
    expect(arcs.length).toBe(0);
  });
});
