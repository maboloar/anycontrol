import { describe, expect, it } from "vitest";
import { calibrationOpacity, selectionFrom, toNorm } from "./overlay";

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
