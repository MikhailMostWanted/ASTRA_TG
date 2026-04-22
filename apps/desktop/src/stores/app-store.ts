import { create } from "zustand";

import type { ScreenId } from "@/lib/types";

interface AppStoreState {
  activeScreen: ScreenId;
  selectedChatId: number | null;
  favoriteChatIds: number[];
  setActiveScreen: (screen: ScreenId) => void;
  setSelectedChatId: (chatId: number | null) => void;
  toggleFavoriteChat: (chatId: number) => void;
}

export const useAppStore = create<AppStoreState>((set) => ({
  activeScreen: "dashboard",
  selectedChatId: null,
  favoriteChatIds: [],
  setActiveScreen: (screen) => set({ activeScreen: screen }),
  setSelectedChatId: (chatId) => set({ selectedChatId: chatId }),
  toggleFavoriteChat: (chatId) =>
    set((state) => ({
      favoriteChatIds: state.favoriteChatIds.includes(chatId)
        ? state.favoriteChatIds.filter((item) => item !== chatId)
        : [...state.favoriteChatIds, chatId],
    })),
}));
