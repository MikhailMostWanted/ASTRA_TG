import { describe, expect, it } from "vitest";

import {
  buildReplyDraftScopeKey,
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
          "telegram:-10015": {
            seenMessageKey: "broken",
            seenMessageId: "bad",
            draftText: "Черновик",
            draftSourceMessageKey: null,
            draftSourceMessageId: 201,
            draftFocusLabel: "вопрос",
            draftScopeKey: "201::вопрос::direct_reply::Когда вернёшься?",
            draftUpdatedAt: "2026-04-22T10:00:00.000Z",
            sentSourceMessageKey: null,
            sentSourceMessageId: null,
            sentAt: null,
          },
          broken: "nope",
        },
      }),
    ).toEqual({
      activeScreen: "dashboard",
      selectedChatKey: null,
      favoriteChatIds: [7, 11],
      chatWorkspace: {
        "telegram:-10015": {
          seenMessageKey: "broken",
          seenMessageId: null,
          draftText: "Черновик",
          draftSourceMessageKey: null,
          draftSourceMessageId: 201,
          draftFocusLabel: "вопрос",
          draftScopeKey: "201::вопрос::direct_reply::Когда вернёшься?",
          draftUpdatedAt: "2026-04-22T10:00:00.000Z",
          sentSourceMessageKey: null,
          sentSourceMessageId: null,
          sentAt: null,
        },
      },
    });
  });

  it("resets in-memory desktop state and clears persisted storage", () => {
    useAppStore.setState({
      activeScreen: "chats",
      selectedChatKey: "telegram:-10088",
      favoriteChatIds: [88],
      chatWorkspace: {
        "telegram:-10088": {
          seenMessageKey: "telegram:-10088:501",
          seenMessageId: 501,
          draftText: "Нужно ответить",
          draftSourceMessageKey: "telegram:-10088:501",
          draftSourceMessageId: 501,
          draftFocusLabel: "вопрос",
          draftScopeKey: "501::вопрос::direct_reply::Когда файл?",
          draftUpdatedAt: "2026-04-22T12:00:00.000Z",
          sentSourceMessageKey: null,
          sentSourceMessageId: null,
          sentAt: null,
        },
      },
    });
    localStorage.setItem("astra-desktop-workspace", '{"state":{"activeScreen":"chats"},"version":1}');

    resetPersistedDesktopState();

    const state = useAppStore.getState();
    expect(state.activeScreen).toBe("dashboard");
    expect(state.selectedChatKey).toBeNull();
    expect(state.favoriteChatIds).toEqual([]);
    expect(state.chatWorkspace).toEqual({});
    expect(localStorage.getItem("astra-desktop-workspace")).toBeNull();
  });

  it("scopes drafts by chat and reply focus", () => {
    useAppStore.getState().resetDesktopState();

    const store = useAppStore.getState();
    store.saveReplyDraft("telegram:-10088", {
      text: "Черновик по бюджету",
      sourceMessageId: 501,
      sourceMessageKey: "telegram:-10088:501",
      focusLabel: "вопрос",
      sourceMessagePreview: "Когда сможешь скинуть файл?",
      replyOpportunityMode: "direct_reply",
    });
    store.saveReplyDraft("telegram:-10099", {
      text: "Другой чат",
      sourceMessageId: 701,
      sourceMessageKey: "telegram:-10099:701",
      focusLabel: "просьба",
      sourceMessagePreview: "Скинь, пожалуйста, итог.",
      replyOpportunityMode: "follow_up_after_self",
    });

    const state = useAppStore.getState();
    expect(state.chatWorkspace["telegram:-10088"]?.draftText).toBe("Черновик по бюджету");
    expect(state.chatWorkspace["telegram:-10099"]?.draftText).toBe("Другой чат");
    expect(state.chatWorkspace["telegram:-10088"]?.draftScopeKey).toBe(
      buildReplyDraftScopeKey({
        sourceMessageId: 501,
        sourceMessageKey: "telegram:-10088:501",
        focusLabel: "вопрос",
        sourceMessagePreview: "Когда сможешь скинуть файл?",
        replyOpportunityMode: "direct_reply",
      }),
    );
    expect(state.chatWorkspace["telegram:-10099"]?.draftScopeKey).toBe(
      buildReplyDraftScopeKey({
        sourceMessageId: 701,
        sourceMessageKey: "telegram:-10099:701",
        focusLabel: "просьба",
        sourceMessagePreview: "Скинь, пожалуйста, итог.",
        replyOpportunityMode: "follow_up_after_self",
      }),
    );
    expect(state.chatWorkspace["telegram:-10088"]?.draftScopeKey).not.toBe(
      state.chatWorkspace["telegram:-10099"]?.draftScopeKey,
    );
  });
});
