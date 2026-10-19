import { t } from "./i18n";
import type { ObjectInfo, Profile } from "./protocol";
export const objectRef = (o: ObjectInfo): string => `#${o.id}`;
export const findObject = (ref: string, objects: ObjectInfo[]): ObjectInfo | undefined =>
  /^#\d+$/.test(ref) ? objects.find(o => objectRef(o) === ref) : objects.find(o => o.name === ref);
export const objectLabel = (ref: string, objects: ObjectInfo[]): string => ref === "@hand" ? t("맨손", "Bare hand") : findObject(ref, objects)?.name ?? ref;
export function bindObjectRefs(p: Profile, objects: ObjectInfo[]): Profile {
  return { ...p, mappings: p.mappings.map(m => {
    if (!("object" in m.input)) return m;
    const o = findObject(m.input.object, objects);
    return o ? { ...m, input: { ...m.input, object: objectRef(o) } } : m;
  }) };
}
