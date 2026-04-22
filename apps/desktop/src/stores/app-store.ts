import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { ScreenId } from "@/lib/types";
import { coerceScreenId, isPlainObject, safeNumberOrNull, safeStringOrNull } from "@/lib/runtime-guards";

export interface ChatWorkspaceState {
  seenMessageId: number | null;
  draftText: string | null;
  draftSourceMessageId: number | null;
  draftFocusLabel: string | null;
  draftScopeKey: string | null;
  draftUpdatedAt: string | null;
  sentSourceMessageId: number | null;
  sentAt: string | null;
}

export interface ReplyDraftScopeInput {
  sourceMessageId: number | null;
  focusLabel?: string | null;
  sourceMessagePreview?: string | null;
  replyOpportunityMode?: string | null;
}

export interface SaveReplyDraftInput extends ReplyDraftScopeInput {
  text: string;
}

interface AppStoreState {
  activeScreen: ScreenId;
  selectedChatId: number | null;
  favoriteChatIds: number[];
  chatWorkspace: Record<number, ChatWorkspaceState>;
  setActiveScreen: (screen: ScreenId) => void;
  setSelectedChatId: (chatId: number | null) => void;
  toggleFavoriteChat: (chatId: number) => void;
  markChatSeen: (chatId: number, messageId: number | null) => void;
  saveReplyDraft: (chatId: number, draft: SaveReplyDraftInput) => void;
  markReplySent: (chatId: number, sourceMessageId: number | null) => void;
  clearReplyDraft: (chatId: number) => void;
  resetDesktopState: () => void;
}

type PersistedAppStoreState = Pick<
  AppStoreState,
  "activeScreen" | "selectedChatId" | "favoriteChatIds" | "chatWorkspace"
>;

export const APP_STORE_STORAGE_KEY = "astra-desktop-workspace";
export const APP_STORE_VERSION = 3;

const emptyWorkspaceState: ChatWorkspaceState = {
  seenMessageId: null,
  draftText: null,
  draftSourceMessageId: null,
  draftFocusLabel: null,
  draftScopeKey: null,
  draftUpdatedAt: null,
  sentSourceMessageId: null,
  sentAt: null,
};

function createDefaultPersistedState(): PersistedAppStoreState {
  return {
    activeScreen: "dashboard",
    selectedChatId: null,
    favoriteChatIds: [],
    chatWorkspace: {},
  };
}

function getWorkspaceState(
  state: Pick<AppStoreState, "chatWorkspace">,
  chatId: number,
): ChatWorkspaceState {
  return state.chatWorkspace[chatId] || emptyWorkspaceState;
}

function sanitizeChatWorkspaceState(value: unknown): ChatWorkspaceState {
  if (!isPlainObject(value)) {
    return emptyWorkspaceState;
  }

  return {
    seenMessageId: safeNumberOrNull(value.seenMessageId),
    draftText: safeStringOrNull(value.draftText),
    draftSourceMessageId: safeNumberOrNull(value.draftSourceMessageId),
    draftFocusLabel: safeStringOrNull(value.draftFocusLabel),
    draftScopeKey: safeStringOrNull(value.draftScopeKey),
    draftUpdatedAt: safeStringOrNull(value.draftUpdatedAt),
    sentSourceMessageId: safeNumberOrNull(value.sentSourceMessageId),
    sentAt: safeStringOrNull(value.sentAt),
  };
}

function sanitizeChatWorkspaceRecord(value: unknown): Record<number, ChatWorkspaceState> {
  if (!isPlainObject(value)) {
    return {};
  }

  return Object.entries(value).reduce<Record<number, ChatWorkspaceState>>((accumulator, [key, item]) => {
    const chatId = Number.parseInt(key, 10);
    if (!Number.isFinite(chatId)) {
      return accumulator;
    }

    accumulator[chatId] = sanitizeChatWorkspaceState(item);
    return accumulator;
  }, {});
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
    selectedChatId: safeNumberOrNull(value.selectedChatId),
    favoriteChatIds,
    chatWorkspace: sanitizeChatWorkspaceRecord(value.chatWorkspace),
  };
}

export function buildReplyDraftScopeKey(input: ReplyDraftScopeInput): string | null {
  const sourceMessageId = input.sourceMessageId;
  const focusLabel = safeStringOrNull(input.focusLabel)?.trim() || null;
  const sourceMessagePreview = safeStringOrNull(input.sourceMessagePreview)?.trim() || null;
  const replyOpportunityMode = safeStringOrNull(input.replyOpportunityMode)?.trim() || null;

  if (sourceMessageId === null && !focusLabel && !sourceMessagePreview) {
    return null;
  }

  return [
    sourceMessageId ?? "none",
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
      setSelectedChatId: (chatId) => set({ selectedChatId: chatId }),
      toggleFavoriteChat: (chatId) =>
        set((state) => ({
          favoriteChatIds: state.favoriteChatIds.includes(chatId)
            ? state.favoriteChatIds.filter((item) => item !== chatId)
            : [...state.favoriteChatIds, chatId],
        })),
      markChatSeen: (chatId, messageId) =>
        set((state) => ({
          chatWorkspace: {
            ...state.chatWorkspace,
            [chatId]: {
              ...getWorkspaceState(state, chatId),
              seenMessageId: messageId,
            },
          },
        })),
      saveReplyDraft: (chatId, draft) =>
        set((state) => ({
          chatWorkspace: {
            ...state.chatWorkspace,
            [chatId]: {
              ...getWorkspaceState(state, chatId),
              draftText: draft.text,
              draftSourceMessageId: draft.sourceMessageId,
              draftFocusLabel: safeStringOrNull(draft.focusLabel),
              draftScopeKey: buildReplyDraftScopeKey(draft),
              draftUpdatedAt: new Date().toISOString(),
            },
          },
        })),
      markReplySent: (chatId, sourceMessageId) =>
        set((state) => ({
          chatWorkspace: {
            ...state.chatWorkspace,
            [chatId]: {
              ...getWorkspaceState(state, chatId),
              sentSourceMessageId: sourceMessageId,
              sentAt: new Date().toISOString(),
            },
          },
        })),
      clearReplyDraft: (chatId) =>
        set((state) => ({
          chatWorkspace: {
            ...state.chatWorkspace,
            [chatId]: {
              ...getWorkspaceState(state, chatId),
              draftText: null,
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
        selectedChatId: state.selectedChatId,
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
