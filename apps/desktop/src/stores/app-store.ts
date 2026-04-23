import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { ScreenId } from "@/lib/types";
import { coerceScreenId, isPlainObject, safeNumberOrNull, safeStringOrNull } from "@/lib/runtime-guards";

export interface ChatWorkspaceState {
  seenMessageKey: string | null;
  seenMessageId: number | null;
  draftText: string | null;
  draftSourceMessageKey: string | null;
  draftSourceMessageId: number | null;
  draftFocusLabel: string | null;
  draftScopeKey: string | null;
  draftUpdatedAt: string | null;
  sentSourceMessageKey: string | null;
  sentSourceMessageId: number | null;
  sentAt: string | null;
}

export interface ReplyDraftScopeInput {
  sourceMessageId: number | null;
  sourceMessageKey?: string | null;
  focusLabel?: string | null;
  sourceMessagePreview?: string | null;
  replyOpportunityMode?: string | null;
}

export interface SaveReplyDraftInput extends ReplyDraftScopeInput {
  text: string;
}

interface AppStoreState {
  activeScreen: ScreenId;
  selectedChatKey: string | null;
  favoriteChatIds: number[];
  chatWorkspace: Record<string, ChatWorkspaceState>;
  setActiveScreen: (screen: ScreenId) => void;
  setSelectedChatKey: (chatKey: string | null) => void;
  toggleFavoriteChat: (chatId: number) => void;
  markChatSeen: (chatKey: string, payload: { messageId?: number | null; messageKey?: string | null }) => void;
  saveReplyDraft: (chatKey: string, draft: SaveReplyDraftInput) => void;
  markReplySent: (chatKey: string, payload: { sourceMessageId?: number | null; sourceMessageKey?: string | null }) => void;
  clearReplyDraft: (chatKey: string) => void;
  resetDesktopState: () => void;
}

type PersistedAppStoreState = Pick<
  AppStoreState,
  "activeScreen" | "selectedChatKey" | "favoriteChatIds" | "chatWorkspace"
>;

export const APP_STORE_STORAGE_KEY = "astra-desktop-workspace";
export const APP_STORE_VERSION = 4;

const emptyWorkspaceState: ChatWorkspaceState = {
  seenMessageKey: null,
  seenMessageId: null,
  draftText: null,
  draftSourceMessageKey: null,
  draftSourceMessageId: null,
  draftFocusLabel: null,
  draftScopeKey: null,
  draftUpdatedAt: null,
  sentSourceMessageKey: null,
  sentSourceMessageId: null,
  sentAt: null,
};

function createDefaultPersistedState(): PersistedAppStoreState {
  return {
    activeScreen: "dashboard",
    selectedChatKey: null,
    favoriteChatIds: [],
    chatWorkspace: {},
  };
}

function getWorkspaceState(
  state: Pick<AppStoreState, "chatWorkspace">,
  chatKey: string,
): ChatWorkspaceState {
  return state.chatWorkspace[chatKey] || emptyWorkspaceState;
}

function sanitizeChatWorkspaceState(value: unknown): ChatWorkspaceState {
  if (!isPlainObject(value)) {
    return emptyWorkspaceState;
  }

  return {
    seenMessageKey: safeStringOrNull(value.seenMessageKey),
    seenMessageId: safeNumberOrNull(value.seenMessageId),
    draftText: safeStringOrNull(value.draftText),
    draftSourceMessageKey: safeStringOrNull(value.draftSourceMessageKey),
    draftSourceMessageId: safeNumberOrNull(value.draftSourceMessageId),
    draftFocusLabel: safeStringOrNull(value.draftFocusLabel),
    draftScopeKey: safeStringOrNull(value.draftScopeKey),
    draftUpdatedAt: safeStringOrNull(value.draftUpdatedAt),
    sentSourceMessageKey: safeStringOrNull(value.sentSourceMessageKey),
    sentSourceMessageId: safeNumberOrNull(value.sentSourceMessageId),
    sentAt: safeStringOrNull(value.sentAt),
  };
}

function sanitizeChatWorkspaceRecord(value: unknown): Record<string, ChatWorkspaceState> {
  if (!isPlainObject(value)) {
    return {};
  }

  return Object.entries(value).reduce<Record<string, ChatWorkspaceState>>((accumulator, [key, item]) => {
    const chatKey = safeStringOrNull(key)?.trim();
    if (!chatKey || !isPersistedWorkspaceChatKey(chatKey)) {
      return accumulator;
    }

    accumulator[chatKey] = sanitizeChatWorkspaceState(item);
    return accumulator;
  }, {});
}

function isPersistedWorkspaceChatKey(value: string): boolean {
  if (/^\d+$/.test(value)) {
    return true;
  }
  return value.includes(":");
}

export function sanitizePersistedAppState(value: unknown): PersistedAppStoreState {
  if (!isPlainObject(value)) {
    return createDefaultPersistedState();
  }

  const favoriteChatIds = Array.isArray(value.favoriteChatIds)
    ? Array.from(
        new Set(
          value.favoriteChatIds.filter(
            (item): item is number => typeof item === "number" && Number.isFinite(item),
          ),
        ),
      )
    : [];

  return {
    activeScreen: coerceScreenId(value.activeScreen),
    selectedChatKey: safeStringOrNull(value.selectedChatKey),
    favoriteChatIds,
    chatWorkspace: sanitizeChatWorkspaceRecord(value.chatWorkspace),
  };
}

export function buildReplyDraftScopeKey(input: ReplyDraftScopeInput): string | null {
  const sourceMessageKey = safeStringOrNull(input.sourceMessageKey)?.trim() || null;
  const sourceMessageId = input.sourceMessageId;
  const focusLabel = safeStringOrNull(input.focusLabel)?.trim() || null;
  const sourceMessagePreview = safeStringOrNull(input.sourceMessagePreview)?.trim() || null;
  const replyOpportunityMode = safeStringOrNull(input.replyOpportunityMode)?.trim() || null;

  if (sourceMessageKey === null && sourceMessageId === null && !focusLabel && !sourceMessagePreview) {
    return null;
  }

  return [
    sourceMessageKey ?? sourceMessageId ?? "none",
    focusLabel ?? "none",
    replyOpportunityMode ?? "none",
    sourceMessagePreview ?? "none",
  ].join("::");
}

export const useAppStore = create<AppStoreState>()(
  persist(
    (set) => ({
      ...createDefaultPersistedState(),
      setActiveScreen: (screen) => set({ activeScreen: screen }),
      setSelectedChatKey: (chatKey) => set({ selectedChatKey: chatKey }),
      toggleFavoriteChat: (chatId) =>
        set((state) => ({
          favoriteChatIds: state.favoriteChatIds.includes(chatId)
            ? state.favoriteChatIds.filter((item) => item !== chatId)
            : [...state.favoriteChatIds, chatId],
        })),
      markChatSeen: (chatKey, payload) =>
        set((state) => ({
          chatWorkspace: {
            ...state.chatWorkspace,
            [chatKey]: {
              ...getWorkspaceState(state, chatKey),
              seenMessageKey: safeStringOrNull(payload.messageKey),
              seenMessageId: safeNumberOrNull(payload.messageId),
            },
          },
        })),
      saveReplyDraft: (chatKey, draft) =>
        set((state) => ({
          chatWorkspace: {
            ...state.chatWorkspace,
            [chatKey]: {
              ...getWorkspaceState(state, chatKey),
              draftText: draft.text,
              draftSourceMessageKey: safeStringOrNull(draft.sourceMessageKey),
              draftSourceMessageId: draft.sourceMessageId,
              draftFocusLabel: safeStringOrNull(draft.focusLabel),
              draftScopeKey: buildReplyDraftScopeKey(draft),
              draftUpdatedAt: new Date().toISOString(),
            },
          },
        })),
      markReplySent: (chatKey, payload) =>
        set((state) => ({
          chatWorkspace: {
            ...state.chatWorkspace,
            [chatKey]: {
              ...getWorkspaceState(state, chatKey),
              sentSourceMessageKey: safeStringOrNull(payload.sourceMessageKey),
              sentSourceMessageId: safeNumberOrNull(payload.sourceMessageId),
              sentAt: new Date().toISOString(),
            },
          },
        })),
      clearReplyDraft: (chatKey) =>
        set((state) => ({
          chatWorkspace: {
            ...state.chatWorkspace,
            [chatKey]: {
              ...getWorkspaceState(state, chatKey),
              draftText: null,
              draftSourceMessageKey: null,
              draftSourceMessageId: null,
              draftFocusLabel: null,
              draftScopeKey: null,
              draftUpdatedAt: null,
            },
          },
        })),
      resetDesktopState: () => set(createDefaultPersistedState()),
    }),
    {
      name: APP_STORE_STORAGE_KEY,
      version: APP_STORE_VERSION,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        activeScreen: state.activeScreen,
        selectedChatKey: state.selectedChatKey,
        favoriteChatIds: state.favoriteChatIds,
        chatWorkspace: state.chatWorkspace,
      }),
      migrate: (persistedState) => sanitizePersistedAppState(persistedState),
      merge: (persistedState, currentState) => ({
        ...currentState,
        ...sanitizePersistedAppState(persistedState),
      }),
    },
  ),
);

export function resetPersistedDesktopState() {
  useAppStore.getState().resetDesktopState();
  void useAppStore.persist.clearStorage();
}
