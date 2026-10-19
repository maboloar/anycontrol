// One shared draft and ordered writer survive panel remounts.
import { useEffect } from "react";
import { create } from "zustand";
import { getMapping, putMapping } from "./api";
import type { Profile } from "./protocol";
import { useApp } from "./store";
import { normalizeGameProfile } from "./gameFunctions";
import { bindObjectRefs } from "./objectRefs";
interface DraftState { draft: Profile | null; err: string | null; set: (p: Profile | null) => void; setErr: (e: string | null) => void }
export const useDraftStore = create<DraftState>((set) => ({ draft: null, err: null, set: (draft) => set({ draft }), setErr: (err) => set({ err }) }));
let timer: number | undefined, revision = 0, epoch = 0, loaded = -1;
let pending: Profile | null = null, writing = false;
let writeWaiters: (() => void)[] = [];
const errText = (e: unknown) => String(e instanceof Error ? e.message : e).replace(/^\d+ /, "");
const deletedRefs = new Set<string>();
function currentProfile(p: Profile): Profile {
  const bound = bindObjectRefs(normalizeGameProfile(p), useApp.getState().objects);
  return { ...bound, mappings: bound.mappings.filter(m => !("object" in m.input && deletedRefs.has(m.input.object))) };
}
useApp.subscribe((s, prev) => {
  if (s.conn !== prev.conn) { epoch++; loaded = -1; }
  if (s.objects === prev.objects) return;
  const ids = new Set(s.objects.map(o => o.id));
  s.objects.forEach(o => deletedRefs.delete(`#${o.id}`));
  const removed = prev.objects.filter(o => !ids.has(o.id));
  if (!removed.length) return;
  removed.forEach(o => deletedRefs.add(`#${o.id}`));
  const draft = useDraftStore.getState().draft;
  if (!draft) return;
  const bound = bindObjectRefs(draft, prev.objects);
  const next = currentProfile(bound);
  if (next.mappings.length !== draft.mappings.length) editDraft(next, true);
});
async function flush(): Promise<void> {
  if (writing || !pending) return;
  const p = currentProfile(pending), rev = revision;
  pending = null; writing = true;
  try {
    const i = await putMapping(p);
    const latest = useDraftStore.getState().draft;
    useApp.getState().setMappingInfo({ ...i, profile: latest ?? i.profile });
    if (rev === revision) useDraftStore.getState().setErr(null);
  } catch (e) {
    if (rev === revision) { pending = p; useDraftStore.getState().setErr(errText(e)); return; }
  } finally { writing = false; const waiters = writeWaiters; writeWaiters = []; waiters.forEach(w => w()); }
  if (pending) void flush();
}
export function editDraft(p: Profile, immediate = false): void {
  if (useApp.getState().resetBusy) return;
  p = currentProfile(p);
  revision++; pending = p;
  useDraftStore.getState().set(p);
  window.clearTimeout(timer);
  if (immediate) void flush(); else timer = window.setTimeout(() => void flush(), 300);
}
export function useMappingDraft(): { draft: Profile | null; edit: typeof editDraft; err: string | null } {
  const conn = useApp(s => s.conn);
  const draft = useDraftStore(s => s.draft), err = useDraftStore(s => s.err);
  useEffect(() => {
    if (conn !== "open" || loaded === epoch) return;
    loaded = epoch;
    if (pending || writing) { void flush(); return; }
    const rev = revision, session = epoch;
    getMapping().then(i => {
      if (revision !== rev || epoch !== session) return;
      useApp.getState().setMappingInfo(i);
      useDraftStore.getState().set(currentProfile(i.profile));
    }, e => { if (revision === rev && epoch === session) { loaded = -1; useDraftStore.getState().setErr(errText(e)); } });
  }, [conn]);
  return { draft, edit: editDraft, err };
}

/** Let an already-sent PUT finish before the reset API, so it cannot restore old mappings. */
export async function settleDraftForReset(): Promise<void> {
  window.clearTimeout(timer); pending = null; revision++;
  if (writing) await new Promise<void>(resolve => writeWaiters.push(resolve));
}
export function replaceDraftAfterReset(p: Profile): void {
  revision++; pending = null; loaded = epoch;
  useDraftStore.getState().set(p); useDraftStore.getState().setErr(null);
}
