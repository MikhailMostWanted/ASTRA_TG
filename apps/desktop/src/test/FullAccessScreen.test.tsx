import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FullAccessScreen } from "@/screens/FullAccessScreen";
import type { FullAccessOverviewPayload, RuntimeAuthPayload } from "@/lib/types";


const apiMock = vi.hoisted(() => ({
  newRuntimeAuthStatus: vi.fn(),
  requestNewRuntimeCode: vi.fn(),
  submitNewRuntimeCode: vi.fn(),
  submitNewRuntimePassword: vi.fn(),
  logoutNewRuntime: vi.fn(),
  resetNewRuntime: vi.fn(),
  fullaccess: vi.fn(),
  fullaccessChats: vi.fn(),
  requestFullaccessCode: vi.fn(),
  loginFullaccess: vi.fn(),
  logoutFullaccess: vi.fn(),
  syncFullaccessChat: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: apiMock,
}));


describe("FullAccessScreen", () => {
  beforeEach(() => {
    Object.values(apiMock).forEach((mockFn) => mockFn.mockReset());
  });

  it("renders the new runtime code flow and submits the code from desktop", async () => {
    apiMock.newRuntimeAuthStatus.mockResolvedValue({
      status: buildRuntimeAuthStatus({
        state: "awaiting_code",
        authState: "authorizing",
        awaitingCode: true,
        canSubmitCode: true,
        sessionState: "available",
        reasonCode: "awaiting_code",
        reason: "Код отправлен. Введи его в Desktop или CLI.",
      }),
    });
    apiMock.fullaccess.mockResolvedValue(buildFullAccessOverview());
    apiMock.submitNewRuntimeCode.mockResolvedValue({
      kind: "password_required",
      message: "Telegram запросил пароль 2FA.",
      status: buildRuntimeAuthStatus({
        state: "awaiting_password",
        authState: "authorizing",
        awaitingCode: false,
        awaitingPassword: true,
        canSubmitCode: false,
        canSubmitPassword: true,
        sessionState: "available",
        reasonCode: "awaiting_password",
        reason: "Telegram требует пароль 2FA.",
      }),
    });

    renderScreen();

    expect(await screen.findByText("Новый Telegram runtime")).toBeInTheDocument();
    expect(screen.getAllByText("ждёт код").length).toBeGreaterThan(0);

    fireEvent.change(
      screen.getByPlaceholderText("Код Telegram для нового runtime"),
      { target: { value: "24680" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить код" }));

    await waitFor(() => {
      expect(apiMock.submitNewRuntimeCode).toHaveBeenCalledWith({ code: "24680" });
    });
    expect(screen.getByText("Legacy full-access остаётся fallback")).toBeInTheDocument();
  });

  it("renders the new runtime password state with the last auth error", async () => {
    apiMock.newRuntimeAuthStatus.mockResolvedValue({
      status: buildRuntimeAuthStatus({
        state: "awaiting_password",
        authState: "authorizing",
        awaitingCode: false,
        awaitingPassword: true,
        canRequestCode: false,
        canSubmitCode: false,
        canSubmitPassword: true,
        canLogout: true,
        canReset: true,
        sessionState: "available",
        reasonCode: "awaiting_password",
        reason: "Telegram требует пароль 2FA.",
        error: {
          code: "password_invalid",
          message: "Пароль 2FA не подошёл. Попробуй ещё раз.",
          at: "2026-04-23T10:05:00+00:00",
        },
      }),
    });
    apiMock.fullaccess.mockResolvedValue(buildFullAccessOverview());

    renderScreen();

    expect((await screen.findAllByText("ждёт пароль")).length).toBeGreaterThan(0);
    expect(screen.getByPlaceholderText("Пароль 2FA для нового runtime")).toBeInTheDocument();
    expect(screen.getByText("Последняя auth-ошибка")).toBeInTheDocument();
    expect(screen.getByText("Пароль 2FA не подошёл. Попробуй ещё раз.")).toBeInTheDocument();
  });
});


function renderScreen() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <FullAccessScreen />
    </QueryClientProvider>,
  );
}


function buildFullAccessOverview(): FullAccessOverviewPayload {
  return {
    status: {
      enabled: false,
      apiCredentialsConfigured: false,
      phoneConfigured: false,
      sessionPath: "/tmp/fullaccess.session",
      sessionExists: false,
      authorized: false,
      telethonAvailable: true,
      requestedReadonly: true,
      effectiveReadonly: true,
      syncLimit: 50,
      pendingLogin: false,
      syncedChatCount: 0,
      syncedMessageCount: 0,
      readyForManualSync: false,
      readyForManualSend: false,
      reason: "Legacy full-access выключен.",
    },
    instructions: ["astratg fullaccess login"],
    localLoginCommand: "astratg fullaccess login",
    onboarding: "Legacy full-access остаётся резервным путём.",
  };
}


function buildRuntimeAuthStatus(overrides: Partial<RuntimeAuthPayload>): RuntimeAuthPayload {
  return {
    state: "idle",
    authState: "unauthorized",
    sessionState: "missing",
    authorized: false,
    awaitingCode: false,
    awaitingPassword: false,
    canRequestCode: true,
    canSubmitCode: false,
    canSubmitPassword: false,
    canLogout: false,
    canReset: true,
    user: {
      id: null,
      username: null,
      phoneHint: "+***1122",
    },
    device: {
      id: null,
      name: "desktop",
    },
    session: {
      path: "/tmp/new-runtime.session",
      stored: false,
    },
    updatedAt: "2026-04-23T10:00:00+00:00",
    stateChangedAt: "2026-04-23T10:00:00+00:00",
    codeRequestedAt: null,
    authorizedAt: null,
    logoutStartedAt: null,
    lastCheckedAt: "2026-04-23T10:00:00+00:00",
    timestamps: {
      updatedAt: "2026-04-23T10:00:00+00:00",
      stateChangedAt: "2026-04-23T10:00:00+00:00",
      codeRequestedAt: null,
      authorizedAt: null,
      logoutStartedAt: null,
      lastCheckedAt: "2026-04-23T10:00:00+00:00",
      errorAt: null,
    },
    reasonCode: "login_required",
    reason: "Новый runtime ждёт авторизацию в Telegram.",
    error: null,
    ...overrides,
  };
}
