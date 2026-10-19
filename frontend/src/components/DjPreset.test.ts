import { expect, it } from 'vitest';
import { djPreset } from './DjDemo';
import { connect, cables } from '../patch';
import type { ObjectInfo, Profile } from '../protocol';
const empty: Profile = { version: 1, name: 'test', description: '', mappings: [] };
const objects = [{ id: 1, name: 'A', kind: 'object', box: [.1, .2, .3, .5] }, { id: 2, name: 'B', kind: 'object', box: [.6, .2, .8, .5] }] as ObjectInfo[];
it('uses one object for both decks, with editable cables and an independent lift-to-clap input', () => {
  const p = djPreset(empty, objects.slice(0, 1));
  expect(p.mappings).toHaveLength(5); expect(cables(p)).toHaveLength(5);
  expect(p.mappings.filter(m => m.input.source === 'touch')).toHaveLength(0);   // 물체 1개 예시에는 터치 배정 없음
  expect(p.mappings.find(m => m.output.target === 'control' && m.output.name === 'dj.horn')!.input).toMatchObject({ source: 'object', axis: 'y' });
});
it('assigns two objects to different decks, respects input mirroring, and preserves non-DJ connections', () => {
  const base = connect(empty, '#1', 'race-steer1');
  const p = djPreset(base, objects, true);
  expect(p.mappings).toHaveLength(10); expect(p.mappings[0]).toEqual(base.mappings[0]);
  expect(p.mappings.find(m => m.output.target === 'control' && m.output.name === 'dj.playA')!.input).toMatchObject({ object: '#2' });
  expect(p.mappings.find(m => m.output.target === 'control' && m.output.name === 'dj.playB')!.input).toMatchObject({ object: '#1' });
  expect(djPreset(p, objects.slice(0, 1)).mappings).toHaveLength(6);
  expect(() => djPreset(empty, [])).toThrow();
});
