// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { create } from 'zustand';
import type { AppState, AgentUIState, MenuData, ScreenState } from '../types';

interface AppActions {
  /** The menu, sent by the agent when the connection opens. */
  applyMenu: (menu: MenuData) => void;
  /** A whole-screen snapshot from the agent. Returns false if it was out of date and ignored. */
  applySnapshot: (epoch: string, version: number, snapshot: ScreenState) => boolean;
  setVoiceSession: (active: boolean) => void;
  setListening: (listening: boolean) => void;
  setReconnecting: (reconnecting: boolean) => void;
  setMicPermission: (permission: 'granted' | 'denied' | 'prompt') => void;
  endVoiceSession: () => void;
  /** Back to the welcome screen for the next customer. */
  resetAgentUI: () => void;
}

const initialAgentUI: AgentUIState = {
  categories: [],
  menuItems: {},
  customBurger: null,
  highlightedCategory: null,
  highlightedItem: null,
  orderItems: [],
  orderTotal: 0,
  orderConfirmed: false,
  orderNumber: null,
  burgerBuilder: null,
};

const initialSync: AppState['sync'] = { epoch: null, version: -1 };

const initialState: AppState = {
  agentUI: initialAgentUI,
  sync: initialSync,
  voice: {
    sessionActive: false,
    listening: false,
    reconnecting: false,
    micPermission: 'prompt',
  },
};

export const useAppStore = create<AppState & AppActions>()((set, get) => ({
  ...initialState,

  applyMenu: (menu) =>
    set((s) => ({
      agentUI: { ...s.agentUI, categories: menu.categories, menuItems: menu.menuItems, customBurger: menu.customBurger },
    })),

  applySnapshot: (epoch, version, snapshot) => {
    const { sync } = get();
    if (epoch === sync.epoch && version <= sync.version) return false;
    set((s) => ({ agentUI: { ...s.agentUI, ...snapshot }, sync: { epoch, version } }));
    return true;
  },

  setVoiceSession: (active) =>
    set((s) => ({ voice: { ...s.voice, sessionActive: active } })),

  setListening: (listening) =>
    set((s) => ({ voice: { ...s.voice, listening } })),

  setReconnecting: (reconnecting) =>
    set((s) => ({ voice: { ...s.voice, reconnecting } })),

  setMicPermission: (permission) =>
    set((s) => ({ voice: { ...s.voice, micPermission: permission } })),

  endVoiceSession: () =>
    set((s) => ({ voice: { ...s.voice, sessionActive: false, listening: false, reconnecting: false } })),

  resetAgentUI: () =>
    set(() => ({ agentUI: initialAgentUI, sync: initialSync })),
}));
