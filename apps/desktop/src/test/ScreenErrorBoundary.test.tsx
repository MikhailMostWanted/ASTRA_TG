import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ScreenErrorBoundary } from "@/components/system/ScreenErrorBoundary";

function Boom(): null {
  throw new Error("render crash в ChatsScreen");
}

describe("ScreenErrorBoundary", () => {
  it("shows fallback and restores the screen on retry", async () => {
    const user = userEvent.setup();
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    function Harness() {
      const [shouldThrow, setShouldThrow] = useState(true);

      return (
        <ScreenErrorBoundary
          screenId="chats"
          screenLabel="Чаты"
          onRetry={() => setShouldThrow(false)}
          onGoDashboard={() => setShouldThrow(false)}
          onResetState={() => setShouldThrow(false)}
        >
          {shouldThrow ? <Boom /> : <div>Экран восстановлен</div>}
        </ScreenErrorBoundary>
      );
    }

    render(<Harness />);

    expect(screen.getByText("Экран «Чаты» упал")).toBeInTheDocument();
    expect(screen.getByText("render crash в ChatsScreen")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Повторить" }));

    expect(screen.getByText("Экран восстановлен")).toBeInTheDocument();
    errorSpy.mockRestore();
  });

  it("exposes reset action instead of leaving a blank area", async () => {
    const user = userEvent.setup();
    const resetSpy = vi.fn();
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ScreenErrorBoundary
        screenId="chats"
        screenLabel="Чаты"
        onRetry={() => {}}
        onGoDashboard={() => {}}
        onResetState={resetSpy}
      >
        <Boom />
      </ScreenErrorBoundary>,
    );

    await user.click(screen.getByRole("button", { name: "Сбросить локальное desktop-состояние" }));

    expect(resetSpy).toHaveBeenCalledTimes(1);
    errorSpy.mockRestore();
  });
});
