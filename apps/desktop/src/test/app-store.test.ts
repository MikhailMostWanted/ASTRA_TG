import { describe, expect, it } from "vitest";

import {
  resetPersistedDesktopState,
  sanitizePersistedAppState,
  useAppStore,
} from "@/stores/app-store";

describe("app-store persistence", () => {
  it("sanitizes incompatible persisted desktop state", () => {
    expect(
      sanitizePersistedAppState({
        activeScreen: "chatz",
        selectedChatId: "42",
        favoriteChatIds: [7, "broken", 7, 11],
        chatWorkspace: {
          "15": {
            seenMessageId: "bad",
            draftText: "Черновик",
            draftSourceMessageId: 201,
            draftUpdatedAt: "2026-04-22T10:00:00.000Z",
            sentSourceMessageId: null,
            sentAt: null,
          },
          broken: "nope",
        },
      }),
    ).toEqual({
      activeScreen: "dashboard",
      selectedChatId: null,
      favoriteChatIds: [7, 11],
      chatWorkspace: {
        15: {
          seenMessageId: null,
          draftText: "Черновик",
          draftSourceMessageId: 201,
          draftUpdatedAt: "2026-04-22T10:00:00.000Z",
          sentSourceMessageId: null,
          sentAt: null,
        },
      },
    });
  });

  it("resets in-memory desktop state and clears persisted storage", () => {
    useAppStore.setState({
      activeScreen: "chats",
      selectedChatId: 88,
      favoriteChatIds: [88],
      chatWorkspace: {
        88: {
          seenMessageId: 501,
          draftText: "Нужно ответить",
          draftSourceMessageId: 501,
          draftUpdatedAt: "2026-04-22T12:00:00.000Z",
          sentSourceMessageId: null,
          sentAt: null,
        },
      },
    });
    localStorage.setItem("astra-desktop-workspace", '{"state":{"activeScreen":"chats"},"version":1}');

    resetPersistedDesktopState();

    const state = useAppStore.getState();
    expect(state.activeScreen).toBe("dashboard");
    expect(state.selectedChatId).toBeNull();
    expect(state.favoriteChatIds).toEqual([]);
    expect(state.chatWorkspace).toEqual({});
    expect(localStorage.getItem("astra-desktop-workspace")).toBeNull();
  });
});
