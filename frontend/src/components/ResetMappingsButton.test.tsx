import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ResetMappingsButton } from "./ResetMappingsButton";
import type { Profile } from "../protocol";

afterEach(cleanup);
const profile = (n: number) => ({ name: "p", mappings: Array.from({ length: n }, (_, i) => ({ id: `m${i}` })) }) as unknown as Profile;

it("stays armed when re-rendered with an equal new draft object (live updates) and clears everything on confirm", () => {
  const edit = vi.fn();
  const { rerender } = render(<ResetMappingsButton draft={profile(3)} edit={edit} />);
  fireEvent.click(screen.getByRole("button"));
  rerender(<ResetMappingsButton draft={profile(3)} edit={edit} />);   // 매 프레임 새 객체
  fireEvent.click(screen.getByRole("button"));
  expect(edit).toHaveBeenCalledWith(expect.objectContaining({ mappings: [] }), true);
});
