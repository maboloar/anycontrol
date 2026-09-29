import { describe, expect, it } from "vitest";
import { applySuggestion, defaultTransform, makeMapping, outputKind, preset, shape, withOutput } from "./mapping";

describe("mapping helpers", () => {
  it("default range follows output kind", () => {
    const inp = { source: "object", object: "펜", axis: "angle" } as const;
    expect(defaultTransform(inp, { target: "gamepad_axis", axis: "left_x" }).range).toEqual([-45, 45]);
    expect(defaultTransform(inp, { target: "gamepad_axis", axis: "rt" }).range).toEqual([0, 45]);
    expect(defaultTransform(inp, { target: "key", key: "w" }).on_lost).toBe("release");
  });

  it("switching output kind resets range", () => {
    const m = makeMapping([], { source: "object", object: "펜", axis: "x" }, { target: "gamepad_axis", axis: "left_x" });
    const m2 = withOutput(m, { target: "gamepad_axis", axis: "rt" });
    expect(m2.transform.range).toEqual([0, 0.3]);
    expect(withOutput(m, { target: "gamepad_axis", axis: "right_y" }).transform).toBe(m.transform);
  });

  it("applies learn suggestion by output kind", () => {
    const s = { axis: "y", score: 1, range: [-0.1, 0.1], range_positive: [-0.1, 0], invert_for_positive: true } as const;
    const pad = makeMapping([], { source: "hand", gesture: "pinch" }, { target: "gamepad_axis", axis: "left_y" });
    expect(applySuggestion(pad, "컵", { ...s, range: [-0.1, 0.1], range_positive: [-0.1, 0] }).transform.range).toEqual([-0.1, 0.1]);
    const key = makeMapping([], { source: "hand", gesture: "pinch" }, { target: "key", key: "w" });
    const k2 = applySuggestion(key, "컵", { ...s, range: [-0.1, 0.1], range_positive: [-0.1, 0] });
    expect(k2.transform.range).toEqual([-0.1, 0]);
    expect(k2.transform.invert).toBe(true);
    expect(k2.input).toEqual({ source: "object", object: "컵", axis: "y" });
  });

  it("shape matches backend rules", () => {
    const t = defaultTransform({ source: "object", object: "a", axis: "angle" }, { target: "gamepad_axis", axis: "left_x" });
    t.deadzone = 0.1;
    expect(shape(0, t, "bipolar")).toBe(0);
    expect(shape(45, t, "bipolar")).toBeCloseTo(1);
    expect(shape(-90, t, "bipolar")).toBeCloseTo(-1);
    expect(shape(4, t, "bipolar")).toBe(0);
  });

  it("presets have unique ids and valid kinds", () => {
    for (const k of ["racing", "wasd", "mouse"] as const) {
      const p = preset(k, "펜");
      const ids = p.mappings.map((m) => m.id);
      expect(new Set(ids).size).toBe(ids.length);
      for (const m of p.mappings) {
        expect(m.transform.range[1]).toBeGreaterThan(m.transform.range[0]);
        if (outputKind(m.output) === "digital") expect(m.transform.off).toBeLessThanOrEqual(m.transform.on);
      }
    }
  });
});

it('provides analog game joystick profiles separately from mouse and WASD', () => {
  const p = preset('joystick', '물체');
  expect(p.mappings.slice(0, 2).map(m => m.output)).toEqual([
    { target: 'gamepad_axis', axis: 'left_x' }, { target: 'gamepad_axis', axis: 'left_y' },
  ]);
  expect(p.mappings.some(m => m.output.target === 'key')).toBe(false);
  expect(preset('zombie', '물체').mappings[0]?.output).toEqual({ target: 'gamepad_button', button: 'a' });
});
