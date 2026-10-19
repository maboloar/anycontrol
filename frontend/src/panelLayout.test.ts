import { expect, it } from "vitest";
import { DEFAULT_LAYOUT, moveSlot, validLayout } from "./panelLayout";

it("default puts performance under output and objects under it, mouse under camera", () => {
  expect(DEFAULT_LAYOUT[1]).toEqual(["real", "hud", "objects"]);
  expect(DEFAULT_LAYOUT[2]).toEqual(["source", "mouse"]);
});

it("moves panels within and across columns", () => {
  expect(moveSlot(DEFAULT_LAYOUT, "objects", 1, 0)[1]).toEqual(["objects", "real", "hud"]);
  expect(moveSlot(DEFAULT_LAYOUT, "real", 1, 3)[1]).toEqual(["hud", "objects", "real"]);   // 같은 열 끝으로
  const l = moveSlot(DEFAULT_LAYOUT, "camera", 2, 1);
  expect(l[0]).toEqual(["mapping", "demo"]);
  expect(l[2]).toEqual(["source", "camera", "mouse"]);
  expect(validLayout(l)).toBe(true);
  expect(validLayout([["camera"], [], []])).toBe(false);
});
