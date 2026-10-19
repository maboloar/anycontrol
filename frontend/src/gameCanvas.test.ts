import { afterEach, expect, it, vi } from "vitest";
import { gameCanvas } from "./gameCanvas";
afterEach(() => vi.restoreAllMocks());
it('draws at display density while keeping fixed gameplay coordinates', () => {
  const c = document.createElement('canvas'), setTransform = vi.fn();
  vi.spyOn(c, 'getBoundingClientRect').mockReturnValue({ width: 900 } as DOMRect);
  vi.spyOn(window, 'devicePixelRatio', 'get').mockReturnValue(2);
  const g = { setTransform } as unknown as CanvasRenderingContext2D;
  vi.spyOn(c, 'getContext').mockReturnValue(g);
  expect(gameCanvas(c, 640, 400)).toBe(g);
  expect([c.width, c.height]).toEqual([1800, 1125]);
  expect(setTransform).toHaveBeenCalledWith(1800 / 640, 0, 0, 1125 / 400, 0, 0);
});
