import { resetSettings } from "./api";
import { settleDraftForReset, replaceDraftAfterReset } from "./mappingDraft";
import { useApp } from "./store";
import { setLang } from "./i18n";
let inFlight: Promise<void> | null = null;
export function resetAllSettings(): Promise<void> {
  if (inFlight) return inFlight;
  useApp.setState({ resetBusy: true });
  window.dispatchEvent(new Event("anycontrol-stop"));
  inFlight = (async () => {
    await settleDraftForReset();
    const result = await resetSettings();
    // Saved profiles live on the server. Keep user-created jack definitions here.
    try { Object.keys(localStorage).filter(k => k.startsWith("anycontrol.") && k !== "anycontrol.customJacks").forEach(k => localStorage.removeItem(k)); } catch { /* in-memory reset still works */ }
    const current = useApp.getState();
    useApp.setState({ ...useApp.getInitialState(), conn: current.conn, serverVersion: current.serverVersion,
      telemetry: current.telemetry, client: current.client, frameSize: current.frameSize, previewMirror: current.previewMirror,
      dormant: current.dormant, patchConnect: current.patchConnect, resetBusy: true, resetGeneration: current.resetGeneration + 1,
      devMode: false, idleShowcase: true, idleSeconds: 120, floatingCamera: true, tourOpen: false,
      handInputEnabled: true, touchOverlay: false, mouseInfo: result.mouse, mappingInfo: result.mapping });
    replaceDraftAfterReset(result.mapping.profile);
    setLang("ko");
    document.documentElement.style.fontSize = "14px";
    ["anycontrol.resize.reset", "anycontrol.layout.reset", "anycontrol.settings.reset"].forEach(name => window.dispatchEvent(new Event(name)));
  })().finally(() => { useApp.setState({ resetBusy: false }); inFlight = null; });
  return inFlight;
}
