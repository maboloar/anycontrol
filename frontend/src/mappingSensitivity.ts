import type { Mapping } from "./protocol";
import { defaultTransform } from "./mapping";
/** A stable baseline from input/output types, independent of labels, language and jack view. */
export function sensitivityBase(m: Mapping): [number, number] {
  return defaultTransform(m.input, m.output).range;
}
export function sensitivity(m: Mapping): number {
  const b = sensitivityBase(m), r = m.transform.range;
  return (b[1] - b[0]) / Math.max(.000001, r[1] - r[0]);
}
export function withSensitivity(m: Mapping, value: number): Mapping {
  const v = Math.max(.000001, Number.isFinite(value) ? value : sensitivity(m));
  const r = m.transform.range, ratio = sensitivity(m) / v;
  const center = (r[0] + r[1]) / 2, half = (r[1] - r[0]) * ratio / 2;
  // Keep trigger zero anchors (including negative brake ranges) and calibrated axis centers.
  const range: [number, number] = r[0] === 0 || r[1] === 0 ? [r[0] * ratio, r[1] * ratio] : [center - half, center + half];
  return { ...m, transform: { ...m.transform, range } };
}
