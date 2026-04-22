import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { ScreenId } from "@/lib/types";

export interface ChatWorkspaceState {
  seenMessageId: number | null;
  draftText: string | null;
  draftSourceMessageId: number | null;
  draftUpdatedAt: string | null;
  sentSourceMessageId: number | null;
  sentAt: string | null;
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
  saveReplyDraft: (chatId: number, text: string, sourceMessageId: number | null) => void;
  markReplySent: (chatId: number, sourceMessageId: number | null) => void;
  clearReplyDraft: (chatId: number) => void;
}

const emptyWorkspaceState: ChatWorkspaceState = {
  seenMessageId: null,
  draftText: null,
  draftSourceMessageId: null,
  draftUpdatedAt: null,
  sentSourceMessageId: null,
  sentAt: null,
};

function getWorkspaceState(
  state: AppStoreState,
  chatId: number,
): ChatWorkspaceState {
  return state.chatWorkspace[chatId] || emptyWorkspaceState;
}

export const useAppStore = create<AppStoreState>()(
  persist(
    (set) => ({
      activeScreen: "dashboard",
      selectedChatId: null,
      favoriteChatIds: [],
      chatWorkspace: {},
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
      saveReplyDraft: (chatId, text, sourceMessageId) =>
        set((state) => ({
          chatWorkspace: {
            ...state.chatWorkspace,
            [chatId]: {
              ...getWorkspaceState(state, chatId),
              draftText: text,
              draftSourceMessageId: sourceMessageId,
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
              draftUpdatedAt: null,
            },
          },
        })),
    }),
    {
      name: "astra-desktop-workspace",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        activeScreen: state.activeScreen,
        selectedChatId: state.selectedChatId,
        favoriteChatIds: state.favoriteChatIds,
        chatWorkspace: state.chatWorkspace,
      }),
    },
  ),
);
