import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DepthCompareView } from "./DepthCompareView";
import { downloadDepthModel, getDepthCompare, getDepthModel } from "../api";
import type { DepthCompareData, DepthModelStatus, DepthRollInfo } from "../protocol";

vi.mock("../api", () => ({ getDepthModel: vi.fn(), downloadDepthModel: vi.fn(), getDepthCompare: vi.fn() }));

const missing: DepthModelStatus = { available: false, downloading: false, error: null, downloaded_mb: 0, size_mb: 50,
  license: "Apache-2.0", source: "huggingface.co/x", path: "/tmp/x" };
const info = (o: Partial<DepthRollInfo> = {}): DepthRollInfo => ({ enabled: true, available: true, deg: 4.4, n: 5, applied: true, a: -97.6,
  source: "depth", error: null, ...o });
const cmp: DepthCompareData = { ready: true, size: [518, 294], ms: 31.2, depth_image: "data:image/png;base64,AA==",
  fit_image: "data:image/png;base64,AA==", touch_image: "data:image/png;base64,AA==", plane_rms: 0.02, inlier_frac: 0.9,
  corr: 0.99, angle_deg: 2.5, roll_depth_deg: 1.3, roll_touch_deg: 3.9 };

beforeEach(() => { vi.resetAllMocks(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("shows one status line for each state and never touches the network on its own", () => {
  const { rerender } = render(<DepthCompareView id={1} info={info()} />);
  expect(screen.getByRole("status").textContent).toContain("적용 중 · 롤 4.4°");
  rerender(<DepthCompareView id={1} info={info({ applied: false, deg: null, n: 1 })} />);
  expect(screen.getByRole("status").textContent).toContain("측정 중 (1/3)");
  rerender(<DepthCompareView id={1} info={info({ available: false, applied: false, deg: null, n: 0, source: "touch" })} />);
  expect(screen.getByRole("status").textContent).toContain("모델 미설치");
  rerender(<DepthCompareView id={1} info={info({ enabled: false })} />);
  expect(screen.getByRole("status").textContent).toContain("꺼짐");
  expect(getDepthModel).not.toHaveBeenCalled();
  expect(downloadDepthModel).not.toHaveBeenCalled();
});

it("downloads only after the user confirms", async () => {
  vi.mocked(getDepthModel).mockResolvedValue(missing);
  vi.mocked(downloadDepthModel).mockResolvedValue({ ...missing, downloading: true });
  const confirm = vi.fn(() => false);
  vi.stubGlobal("confirm", confirm);
  render(<DepthCompareView id={1} info={info({ available: false, applied: false, deg: null, n: 0, source: "touch" })} />);
  fireEvent.click(screen.getByRole("button", { name: "깊이 모델 내려받기" }));
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
  expect(downloadDepthModel).not.toHaveBeenCalled();
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "깊이 모델 내려받기" }));
  await waitFor(() => expect(downloadDepthModel).toHaveBeenCalledTimes(1));
  expect(await screen.findByText(/내려받는 중/)).toBeTruthy();
});

it("shows comparison images only on request and explains when it is not ready", async () => {
  vi.mocked(getDepthCompare).mockResolvedValueOnce(cmp).mockResolvedValueOnce({ ready: false, reason: "learning" });
  render(<DepthCompareView id={7} info={info()} />);
  expect(screen.queryByAltText("깊이 모델 출력")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "비교 이미지" }));
  expect(await screen.findByAltText("깊이 모델 출력")).toBeTruthy();
  expect(screen.getByText(/롤 깊이 1.3° \/ 터치 3.9°/)).toBeTruthy();
  expect(getDepthCompare).toHaveBeenCalledWith(7);
  fireEvent.click(screen.getByRole("button", { name: "지금 프레임으로 다시" }));
  expect(await screen.findByText(/더 배워야/)).toBeTruthy();
});
