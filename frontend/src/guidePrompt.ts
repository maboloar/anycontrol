import { create } from "zustand";
export const GUIDE_IDLE_MS = 20_000;
/** dismissed: 사용자가 × 로 닫았다. 다음 시연 화면(리셋)이 뜨기 전까지 다시 띄우지 않는다. 메모리에만 있어 새로고침하면 풀린다. */
export const useGuidePrompt = create<{ visible: boolean; returning: boolean; dismissed: boolean }>(() => ({ visible: false, returning: false, dismissed: false }));
export const showGuidePrompt = (returning = false) => { if (!useGuidePrompt.getState().dismissed) useGuidePrompt.setState({ visible: true, returning: returning || useGuidePrompt.getState().returning }); };
export const dismissGuidePrompt = () => useGuidePrompt.setState({ visible: false, returning: false, dismissed: true });
/** 시연 화면으로 리셋될 때: × 로 닫았던 것을 풀어 다음 방문자에게 다시 보이게 한다 */
export const allowGuidePrompt = () => useGuidePrompt.setState({ dismissed: false });
export const hideGuidePrompt = () => useGuidePrompt.setState({ visible: false, returning: false });
