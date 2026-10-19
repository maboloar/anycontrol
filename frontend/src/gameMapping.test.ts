import { expect, it } from "vitest";
import { buildGameMapping, mappingWarning } from "./gameMapping";
import { GAME_AXES, GAME_PRESETS, normalizeGameProfile, requiredControls } from "./gameFunctions";
import { cables } from "./patch";
import { preset, shape } from "./mapping";
import type { ObjectInfo, Profile } from "./protocol";
const empty: Profile = { version: 1, name: "empty", description: "", mappings: [] };
const objects = [{ id: 1, name: "A" }, { id: 2, name: "B" }] as ObjectInfo[];
it.each(GAME_PRESETS)('creates visible editable jacks for $id', p => {
  const profile = buildGameMapping(empty, p.game, p.players, p.style, ['#1', '#2']);
  expect(mappingWarning(profile, p.game, p.players, objects, true)).toBeNull();
  expect(cables(profile)).toHaveLength(profile.mappings.length);
  for (const name of requiredControls(p.game, p.players)) expect(profile.mappings.some(m => m.output.target === 'gamepad_axis' && m.output.axis === GAME_AXES[name])).toBe(true);
  expect(new Set(profile.mappings.map(m => m.id)).size).toBe(profile.mappings.length);
});
it('replaces pad axes on preset change and keeps unrelated keyboard/DJ mappings', () => {
  const race = buildGameMapping(empty, 'race', 2, 'angle', ['#1', '#2']);
  const key = preset('wasd', '#1').mappings[0]!;
  const fruit = buildGameMapping({ ...race, mappings: [...race.mappings, key] }, 'fruit', 2, 'depth', ['#1', '#2']);
  const changed = buildGameMapping(fruit, 'fruit', 1, 'y', ['#2']);
  expect(race.mappings).toHaveLength(2); expect(fruit.mappings).toHaveLength(5); expect(changed.mappings).toHaveLength(3);
  expect(changed.mappings).toContainEqual(key);
  expect(changed.mappings.find(m => m.output.target === 'gamepad_axis' && m.output.axis === 'left_y')!.input).toEqual({ source: 'object', object: '#2', axis: 'y' });
  expect(changed.mappings.some(m => m.output.target === 'gamepad_axis' && m.output.axis.startsWith('right'))).toBe(false);
});
it('uses size for desk height and image Y when held, with editable direction and sensitivity', () => {
  const desk = buildGameMapping(empty, 'fruit', 1, 'depth', ['#1']).mappings[1]!;
  const held = buildGameMapping(empty, 'fruit', 1, 'y', ['#1']).mappings[1]!;
  expect(desk.input).toMatchObject({ axis: 'depth' }); expect(desk.transform.invert).toBe(true);
  expect(held.input).toMatchObject({ axis: 'y' }); expect(held.transform.invert).toBe(false);
  const v = shape(.1, held.transform, 'bipolar');
  expect(shape(.1, { ...held.transform, range: [-.15, .15] }, 'bipolar')).toBeGreaterThan(v);
  expect(shape(.1, { ...held.transform, invert: true }, 'bipolar')).toBeCloseTo(-v);
});
it('maps hand XY for movement and rejects incomplete, missing or disabled sources', () => {
  const p = buildGameMapping(empty, 'hockey', 1, 'depth', ['@hand']);
  expect(p.mappings.map(m => m.input)).toEqual([{ source: 'hand', gesture: 'x' }, { source: 'hand', gesture: 'y' }]);
  expect(mappingWarning(p, 'hockey', 1, [], false)).toContain('자동 매핑');
  expect(mappingWarning(p, 'hockey', 1, [], true)).toBeNull();
  expect(() => buildGameMapping(empty, 'race', 2, 'x', ['#1', '#1'])).toThrow();
  expect(mappingWarning(buildGameMapping(empty, 'race', 1, 'x', ['#1']), 'race', 1, [], true)).toContain('자동 매핑');
});
it('legacy racing and zombie preset API targets the same game jacks', () => {
  expect(mappingWarning(preset('racing', '#1'), 'race', 1, objects, true)).toBeNull();
  expect(mappingWarning(preset('zombie', '#1'), 'survival', 1, objects, true)).toBeNull();
});

it('keeps both hand gas and brake neutral at the center and separates their directions', () => {
  const p = buildGameMapping(empty, 'race', 1, 'x', ['@hand']);
  const gas = p.mappings.find(m => m.output.target === 'gamepad_axis' && m.output.axis === 'rt')!;
  const brake = p.mappings.find(m => m.output.target === 'gamepad_axis' && m.output.axis === 'lt')!;
  expect(shape(0, gas.transform, 'unipolar')).toBe(0); expect(shape(0, brake.transform, 'unipolar')).toBe(0);
  expect(shape(-.2, gas.transform, 'unipolar')).toBeGreaterThan(.5); expect(shape(-.2, brake.transform, 'unipolar')).toBe(0);
  expect(shape(.2, brake.transform, 'unipolar')).toBeGreaterThan(.5); expect(shape(.2, gas.transform, 'unipolar')).toBe(0);
});

it('migrates old private controls to pad axes with the last channel owner winning', () => {
  const p = buildGameMapping(empty, 'fruit', 1, 'depth', ['#1']);
  const legacy: Profile = { ...p, mappings: [
    { ...p.mappings[0]!, output: { target: 'control', name: 'race.steer1', kind: 'bipolar' } },
    { ...p.mappings[1]!, output: { target: 'control', name: 'fruit.x1', kind: 'bipolar' } },
  ] };
  const converted = normalizeGameProfile(legacy);
  expect(converted.mappings).toHaveLength(1);
  expect(converted.mappings[0]!.input).toEqual(p.mappings[1]!.input);
  expect(converted.mappings[0]!.output).toEqual({ target: 'gamepad_axis', axis: 'left_x' });
  expect(legacy.mappings[0]!.output.target).toBe('control');
});
