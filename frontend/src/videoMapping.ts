import { objectRef } from "./objectRefs";
import type { ObjectInfo } from "./protocol";
import { useApp } from "./store";
import type { Norm } from "./overlay";

function inside(p: Norm, polygon: number[][]): boolean {
  let hit = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[j]!, b = polygon[i]!;
    const cross = (p[0] - a[0]!) * (b[1]! - a[1]!) - (p[1] - a[1]!) * (b[0]! - a[0]!);
    if (Math.abs(cross) < 1e-8 && p[0] >= Math.min(a[0]!, b[0]!) && p[0] <= Math.max(a[0]!, b[0]!) && p[1] >= Math.min(a[1]!, b[1]!) && p[1] <= Math.max(a[1]!, b[1]!)) return true;
    if ((a[1]! > p[1]) !== (b[1]! > p[1]) && p[0] < (b[0]! - a[0]!) * (p[1] - a[1]!) / (b[1]! - a[1]!) + a[0]!) hit = !hit;
  }
  return hit;
}

/** Hit the same visible contour drawn on screen, last drawn first. Hand gesture overlays are not targets. */
export function videoObjectAt(point: Norm, objects: ObjectInfo[]): ObjectInfo | undefined {
  return [...objects].reverse().find(o => (o.kind === "object" || o.kind === "pen") && (o.state === "tracking" || o.state === "grasped") && o.box &&
    point[0] >= o.box[0] && point[0] <= o.box[2] && point[1] >= o.box[1] && point[1] <= o.box[3] &&
    (!o.contour || o.contour.length < 3 || inside(point, o.contour)));
}

/** Direction is deliberate: a function cable may end on video, never start there. */
export function connectVideoObject(point: Norm, objects: ObjectInfo[]): ObjectInfo | undefined {
  const app = useApp.getState(), drag = app.patchDrag;
  if (drag?.from.kind !== "fn" || !app.patchConnect) return;
  const registered = new Set(app.objects.map(o => o.id));
  const object = videoObjectAt(point, objects.filter(o => registered.has(o.id)));
  if (!object) return;
  app.setPatchDrag(null);
  app.select(object.id);
  app.patchConnect(objectRef(object), drag.from.id);
  return object;
}

/** Visible image inside a resizable object-fit:contain floating preview. */
export function fittedVideoRect(rect: DOMRect, width: number, height: number): DOMRect {
  if (width <= 0 || height <= 0) return rect;
  const scale = Math.min(rect.width / width, rect.height / height);
  const w = width * scale, h = height * scale;
  return new DOMRect(rect.left + (rect.width - w) / 2, rect.top + (rect.height - h) / 2, w, h);
}
