import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clampFloating, isPartlyHidden } from "./components/CameraView";
import { tipPosition } from "./components/Info";
import { BUDDY_H, BUDDY_W, buddyPixels } from "./components/CameraBuddy";
import { STEPS, Tutorial } from "./components/Tutorial";
import { useApp } from "./store";
import { TOUR_KEY, markTourSeen, placeCard, tourSeen, unionBox } from "./tutorial";

const VP = { width: 1200, height: 800 };
const CARD = { width: 400, height: 200 };

describe("placeCard (튜토리얼 말풍선 위치)", () => {
  it("centers when there is no target", () => {
    const p = placeCard(null, CARD, VP);
    expect(p).toEqual({ left: 400, top: 300, side: "center" });
  });

  it("goes below a target near the top, centered on it", () => {
    const p = placeCard({ left: 500, top: 50, width: 200, height: 40 }, CARD, VP);
    expect(p.side).toBe("below");
    expect(p.top).toBe(50 + 40 + 16);
    expect(p.left).toBe(400);
  });

  it("goes above a target near the bottom", () => {
    const p = placeCard({ left: 500, top: 700, width: 200, height: 40 }, CARD, VP);
    expect(p.side).toBe("above");
    expect(p.top + CARD.height).toBeLessThanOrEqual(700);
  });

  it("goes beside a tall target and stays inside the viewport", () => {
    const right = placeCard({ left: 20, top: 20, width: 500, height: 760 }, CARD, VP);
    expect(right.side).toBe("right");
    const left = placeCard({ left: 700, top: 20, width: 480, height: 760 }, CARD, VP);
    expect(left.side).toBe("left");
    for (const p of [right, left]) {
      expect(p.left).toBeGreaterThanOrEqual(12);
      expect(p.left + CARD.width).toBeLessThanOrEqual(VP.width - 12);
      expect(p.top).toBeGreaterThanOrEqual(12);
    }
  });

  it("overlaps at the bottom when the target fills the screen", () => {
    const p = placeCard({ left: 0, top: 0, width: 1200, height: 800 }, CARD, VP);
    expect(p.side).toBe("overlap");
    expect(p.top + CARD.height).toBeLessThanOrEqual(VP.height);
  });

  it("clamps horizontally near the right edge", () => {
    const p = placeCard({ left: 1150, top: 50, width: 40, height: 20 }, CARD, VP);
    expect(p.left + CARD.width).toBeLessThanOrEqual(VP.width - 12);
  });
});

describe("unionBox", () => {
  it("wraps visible boxes and ignores hidden ones", () => {
    expect(unionBox([
      { left: 10, top: 20, width: 100, height: 50 },
      { left: 50, top: 90, width: 200, height: 10 },
      { left: 0, top: 0, width: 0, height: 0 },
    ])).toEqual({ left: 10, top: 20, width: 240, height: 80 });
    expect(unionBox([{ left: 5, top: 5, width: 0, height: 10 }])).toBeNull();
    expect(unionBox([])).toBeNull();
  });
});

describe("tipPosition (정보 아이콘 말풍선)", () => {
  it("sits above the icon, or below when there is no room", () => {
    const above = tipPosition({ left: 500, top: 300, width: 15, height: 15 }, { width: 200, height: 60 }, VP);
    expect(above.below).toBe(false);
    expect(above.top).toBe(300 - 8 - 60);
    const below = tipPosition({ left: 500, top: 20, width: 15, height: 15 }, { width: 200, height: 60 }, VP);
    expect(below.below).toBe(true);
    expect(below.top).toBe(20 + 15 + 8);
  });

  it("never leaves the viewport horizontally", () => {
    expect(tipPosition({ left: 2, top: 300, width: 15, height: 15 }, { width: 200, height: 60 }, VP).left).toBe(8);
    const r = tipPosition({ left: 1190, top: 300, width: 15, height: 15 }, { width: 200, height: 60 }, VP);
    expect(r.left + 200).toBeLessThanOrEqual(VP.width - 8);
  });
});

describe("isPartlyHidden (영상 띄우기)", () => {
  it("floats once a third of the video is scrolled above the top", () => {
    expect(isPartlyHidden({ top: 0, height: 300 })).toBe(false);
    expect(isPartlyHidden({ top: -99, height: 300 })).toBe(false); // 아직 1/3 미만 가려짐
    expect(isPartlyHidden({ top: -100, height: 300 })).toBe(true);
    expect(isPartlyHidden({ top: -500, height: 300 })).toBe(true);
    expect(isPartlyHidden({ top: 300, height: 300 })).toBe(false); // 아래에 있음
    expect(isPartlyHidden({ top: -10, height: 0 })).toBe(false);
  });
});

describe("clampFloating (떠 있는 카메라 옮기기)", () => {
  it("keeps the window inside the viewport", () => {
    const size = { width: 300, height: 200 };
    expect(clampFloating({ left: -50, top: -20 }, size, VP)).toEqual({ left: 8, top: 8 });
    expect(clampFloating({ left: 5000, top: 5000 }, size, VP)).toEqual({ left: VP.width - 300 - 8, top: VP.height - 40 - 8 });
    expect(clampFloating({ left: 400, top: 300 }, size, VP)).toEqual({ left: 400, top: 300 });
  });
});

describe("CameraBuddy", () => {
  it("draws a small flat pixel webcam inside its grid", () => {
    const px = buddyPixels(false);
    expect(px.length).toBeGreaterThan(40);
    for (const p of px) {
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThan(BUDDY_W);
      expect(p.y).toBeLessThan(BUDDY_H);
      expect(p.c).toMatch(/^#[0-9a-f]{6}$/);
    }
    expect(new Set(px.map((p) => p.c)).size).toBeLessThanOrEqual(5); // 단색 머리·받침 + 렌즈·반짝임·녹화등
  });

  it("blinks like a shutter: the lens shrinks to one row", () => {
    const lens = (b: boolean) => buddyPixels(b).filter((p) => p.c === "#1b1f27");
    expect(new Set(lens(false).map((p) => p.y)).size).toBe(5);
    expect(new Set(lens(true).map((p) => p.y)).size).toBe(1);
  });
});

describe("Tutorial", () => {
  beforeEach(() => {
    localStorage.clear();
    act(() => useApp.setState({ tourOpen: true }));
  });
  afterEach(cleanup);

  it("remembers when it has been seen", () => {
    expect(tourSeen()).toBe(false);
    markTourSeen();
    expect(tourSeen()).toBe(true);
    expect(localStorage.getItem(TOUR_KEY)).toBe("done");
  });

  it("covers the required topics with unique steps", () => {
    const ids = STEPS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ["caution", "camera", "object", "pen", "hand", "paper", "bye"]) expect(ids).toContain(id);
    // 예전 시작 안내(주의사항)의 내용이 튜토리얼에 들어 있다
    render(<Tutorial />);
    for (let i = 0; i < STEPS.findIndex((st) => st.id === "caution"); i++) fireEvent.click(screen.getByText("다음 →"));
    const text = screen.getByRole("dialog").textContent ?? "";
    for (const w of ["macOS", "연속성 카메라", "권한", "ESC"]) expect(text).toContain(w);
    expect(STEPS.length).toBeLessThanOrEqual(10); // 너무 길지 않게
  });

  it("steps through with the buttons and finishes on the last step", () => {
    render(<Tutorial />);
    expect(screen.getByRole("heading").textContent).toBe(STEPS[0]!.title);
    fireEvent.click(screen.getByText("다음 →"));
    expect(screen.getByRole("heading").textContent).toBe(STEPS[1]!.title);
    fireEvent.click(screen.getByText("← 이전"));
    expect(screen.getByRole("heading").textContent).toBe(STEPS[0]!.title);
    for (let i = 1; i < STEPS.length; i++) fireEvent.click(screen.getByText("다음 →"));
    expect(screen.getByRole("heading").textContent).toBe(STEPS[STEPS.length - 1]!.title);
    expect(screen.getByRole("heading").closest(".tour")?.textContent).toContain("창(탭)을 닫으면 끝");
    fireEvent.click(screen.getByText("시작하기"));
    expect(useApp.getState().tourOpen).toBe(false);
    expect(tourSeen()).toBe(true);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("can be skipped, and arrow keys move between steps", () => {
    render(<Tutorial />);
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByRole("heading").textContent).toBe(STEPS[1]!.title);
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(screen.getByRole("heading").textContent).toBe(STEPS[0]!.title);
    fireEvent.click(screen.getByText("건너뛰기"));
    expect(useApp.getState().tourOpen).toBe(false);
    expect(tourSeen()).toBe(true);
  });

  it("starts from the first step when reopened", () => {
    render(<Tutorial />);
    fireEvent.click(screen.getByText("다음 →"));
    fireEvent.click(screen.getByText("건너뛰기"));
    act(() => useApp.getState().setTour(true));
    expect(screen.getByRole("heading").textContent).toBe(STEPS[0]!.title);
  });
});
