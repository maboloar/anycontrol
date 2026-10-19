import { useApp } from "./store";
const owners = new Map<symbol, (object: string, fn: string) => void>();
export function registerPatchConnection(handler: (object: string, fn: string) => void): () => void {
  const token = Symbol(); owners.set(token, handler);
  const dispatch = (object: string, fn: string) => [...owners.values()].at(-1)?.(object, fn);
  useApp.getState().setPatchConnect(dispatch);
  return () => {
    owners.delete(token);
    if (!owners.size) { useApp.getState().setPatchConnect(null); useApp.getState().setPatchDrag(null); }
  };
}
