import { useEffect } from "react";
import { getReal, putReal } from "./api";
import type { MouseInfo, RealInfo } from "./protocol";
import { useApp } from "./store";

let revision = 0;
let changing = 0;
export function publishReal(info: RealInfo): void {
  revision++;
  const app = useApp.getState();
  app.setLive({ ...app.live, real: info });
}
export async function changeRealOutput(on: boolean): Promise<void> {
  const rev = ++revision;
  changing++;
  try { const r = await putReal(on); if (rev === revision) publishReal(r); }
  finally { changing--; }
}
/** One poller in the header, independent of output panel position/collapse/video pause. */
export function useRealStatus(): void {
  const conn = useApp(s => s.conn);
  useEffect(() => {
    const pendingStop = () => { revision++; };
    const stopped = (event: Event) => {
      const app = useApp.getState(), info = app.live.real;
      if (info) publishReal({ ...info, state: "off", remaining_s: null, stopped_by: "stop" });
      else revision++;
      const mouse = (event as CustomEvent<MouseInfo>).detail;
      if (mouse) app.setMouseInfo(mouse);
      if (app.mappingInfo) app.setMappingInfo({ ...app.mappingInfo, mode: "observe" });
    };
    window.addEventListener("anycontrol-stop", pendingStop);
    window.addEventListener("anycontrol.real-stopped", stopped);
    return () => { window.removeEventListener("anycontrol-stop", pendingStop); window.removeEventListener("anycontrol.real-stopped", stopped); };
  }, []);
  useEffect(() => {
    if (conn !== "open") return;
    let active = true, timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const rev = revision, observed = useApp.getState().live.real;
      try {
        const r = await getReal();
        // Do not overwrite a newer WS state, a button request or an acknowledged stop.
        if (active && !changing && rev === revision && useApp.getState().live.real === observed) publishReal(r);
      } catch { /* Keep the last indication and retry; never claim a failed stop succeeded. */ }
      if (active) timer = setTimeout(() => void poll(), 300);
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [conn]);
}
