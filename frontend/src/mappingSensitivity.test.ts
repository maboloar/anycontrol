import { expect, it } from "vitest";
import { buildGameMapping } from "./gameMapping";
import { sensitivity, withSensitivity } from "./mappingSensitivity";
it('scales racing brake/gas without changing zero anchors, direction or calibrated centers', () => {
  const p = buildGameMapping({ version: 1, name: 'test', description: '', mappings: [] }, 'race', 1, 'x', ['#1']);
  const brake = p.mappings.find(m => m.output.target === 'gamepad_axis' && m.output.axis === 'lt')!;
  const next = withSensitivity(brake, sensitivity(brake) * 2);
  expect(next.transform.range).toEqual([-.175, 0]); expect(next.transform.invert).toBe(brake.transform.invert);
  const offset = { ...brake, transform: { ...brake.transform, range: [.1, .5] as [number, number] } };
  const adjusted = withSensitivity(offset, sensitivity(offset) * 2);
  expect(adjusted.transform.range[0]).toBeCloseTo(.2); expect(adjusted.transform.range[1]).toBeCloseTo(.4);
  expect(sensitivity({ ...brake, label: 'renamed' })).toBe(sensitivity(brake));
});
