import { expect, it } from "vitest";
import { cables, connect, disconnect } from "./patch";
import type { Profile } from "./protocol";

const empty: Profile = { version: 1, name: "기본", description: "", mappings: [] };

it("connects an object to a function jack, one cable per jack, many per object", () => {
  let p = connect(empty, "컵", "steer");
  expect(p.mappings).toHaveLength(1);
  expect(p.mappings[0]).toMatchObject({ input: { source: "object", object: "컵", axis: "x" }, output: { target: "gamepad_axis", axis: "left_x" } });
  p = connect(p, "컵", "gas");
  expect(cables(p).map((c) => c.fn)).toEqual(["steer", "gas"]);
  p = connect(p, "지갑", "steer");                               // 같은 잭에 새 물체 → 예전 선은 빠진다
  expect(cables(p)).toEqual([expect.objectContaining({ object: "컵", fn: "gas" }), expect.objectContaining({ object: "지갑", fn: "steer" })]);
  p = disconnect(p, cables(p)[0]!.id);
  expect(cables(p).map((c) => c.fn)).toEqual(["steer"]);
});

it("lift-to-press jacks invert the upward y movement", () => {
  const m = connect(empty, "컵", "space").mappings[0]!;
  expect(m.output).toEqual({ target: "key", key: "space" });
  expect(m.transform).toMatchObject({ range: [-0.12, 0], invert: true });
});

it("shows hand-gesture cables and ignores unknown jacks", () => {
  const p: Profile = { ...empty, mappings: [{ id: "m1", label: "", enabled: true, input: { source: "hand", gesture: "pinch" },
    output: { target: "gamepad_button", button: "a" }, transform: connect(empty, "x", "button-a").mappings[0]!.transform }] };
  expect(cables(p)).toEqual([{ id: "m1", object: "@hand", fn: "button-a" }]);
  expect(connect(p, "컵", "nope")).toBe(p);
});

it("connects hand buttons as pinches and analog jacks as palm motion", () => {
  const button = connect(empty, "@hand", "button-a").mappings[0]!;
  expect(button.input).toEqual({ source: "hand", gesture: "pinch" });
  expect(button.transform.range).toEqual([0, 1]);
  expect(connect(empty, "@hand", "steer").mappings[0]!).toMatchObject({ input: { source: "hand", gesture: "x" }, transform: { range: [-.3, .3] } });
});
