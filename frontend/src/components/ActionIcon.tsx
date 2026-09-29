type IconName = "play" | "pause" | "stop" | "virtual" | "real" | "link" | "target" | "reset" | "check" | "tune" | "save" | "key" | "flip" | "power" | "trash";
const paths: Record<IconName, string> = {
  play: "M8 5l11 7-11 7Z", pause: "M8 5v14M16 5v14", stop: "M6 6h12v12H6Z",
  virtual: "M3 4h18v12H3ZM8 20h8M12 16v4", real: "m13 2-8 12h7l-1 8 8-12h-7Z",
  link: "m10 13 4-4M8 16l-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0M16 8l1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0",
  target: "M12 3v4M12 17v4M3 12h4M17 12h4M19 12a7 7 0 1 1-14 0 7 7 0 0 1 14 0M13 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0",
  reset: "M3 11a9 9 0 1 1 2 7M3 4v7h7", check: "m5 12 4 4L19 6",
  tune: "M4 6h16M4 12h16M4 18h16M8 3v6M16 9v6M10 15v6",
  save: "M5 3h12l4 4v14H3V3ZM7 3v6h10V3M7 21v-7h10v7",
  key: "M15 8a5 5 0 1 1-10 0 5 5 0 0 1 10 0M13 12l8 8M17 16l3-3",
  flip: "M3 8h18m-4-4 4 4-4 4M21 16H3m4-4-4 4 4 4", power: "M12 2v10M6 5a9 9 0 1 0 12 0",
  trash: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7",
};
/** Decorative: the button's text remains its accessible name. */
export function ActionIcon({ name }: { name: IconName }) {
  return <svg className="action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={paths[name]} /></svg>;
}
