// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { create } from 'zustand';
import type { AppState, AgentUIState } from '../types';

interface AppActions {
  applyAgentUIState: (state: AgentUIState) => void;
  setVoiceSession: (active: boolean) => void;
  setListening: (listening: boolean) => void;
  setMicPermission: (permission: 'granted' | 'denied' | 'prompt') => void;
  endVoiceSession: () => void;
  /** Back to the welcome screen for the next customer. */
  resetAgentUI: () => void;
}

const initialAgentUI: AgentUIState = {
  categories: [],
  menuItems: {},
  highlightedCategory: null,
  highlightedItem: null,
  orderItems: [],
  orderTotal: 0,
  orderConfirmed: false,
  orderNumber: null,
  burgerBuilder: null,
};

const initialState: AppState = {
  agentUI: initialAgentUI,
  voice: {
    sessionActive: false,
    listening: false,
    micPermission: 'prompt',
  },
};

export const useAppStore = create<AppState & AppActions>()((set) => ({
  ...initialState,

  applyAgentUIState: (agentUI: AgentUIState) =>
    set(() => ({ agentUI })),

  setVoiceSession: (active) =>
    set((s) => ({ voice: { ...s.voice, sessionActive: active } })),

  setListening: (listening) =>
    set((s) => ({ voice: { ...s.voice, listening } })),

  setMicPermission: (permission) =>
    set((s) => ({ voice: { ...s.voice, micPermission: permission } })),

  endVoiceSession: () =>
    set((s) => ({ voice: { ...s.voice, sessionActive: false, listening: false } })),

  resetAgentUI: () =>
    set(() => ({ agentUI: initialAgentUI })),
}));
