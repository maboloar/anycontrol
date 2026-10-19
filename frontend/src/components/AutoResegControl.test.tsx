import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AutoResegControl } from "./AutoResegControl";
import { getAutoReseg, putAutoReseg } from "../api";
import { useApp } from "../store";

vi.mock("../api", () => ({ getAutoReseg: vi.fn(), putAutoReseg: vi.fn() }));

beforeEach(() => { vi.resetAllMocks(); localStorage.clear(); useApp.setState({ devMode: true, conn: "open" }); });
afterEach(cleanup);

it("toggles auto re-segmentation and edits the long-stillness seconds (developer mode only)", async () => {
  vi.mocked(getAutoReseg).mockResolvedValue({ enabled: true, long_s: 15 });
  vi.mocked(putAutoReseg).mockImplementation(async (b) => ({ enabled: b.enabled ?? true, long_s: b.long_s ?? 15 }));
  const { rerender } = render(<AutoResegControl />);
  const box = await screen.findByRole("checkbox", { name: "자동 분할 재지정" });
  await waitFor(() => expect((box as HTMLInputElement).checked).toBe(true));
  fireEvent.click(box);
  await waitFor(() => expect(putAutoReseg).toHaveBeenCalledWith({ enabled: false }));
  const num = screen.getByRole("spinbutton", { name: "오래 정지 기준 (초)" });
  expect((num as HTMLInputElement).value).toBe("15");
  fireEvent.change(num, { target: { value: "40" } });
  fireEvent.blur(num);
  await waitFor(() => expect(putAutoReseg).toHaveBeenCalledWith({ long_s: 40 }));
  fireEvent.change(num, { target: { value: "1" } });
  fireEvent.blur(num);
  expect(screen.getByText("3~600초 사이로 입력하세요.")).toBeTruthy();
  act(() => useApp.getState().setDevMode(false));
  rerender(<AutoResegControl />);
  expect(screen.queryByRole("checkbox", { name: "자동 분할 재지정" })).toBeNull();
});
