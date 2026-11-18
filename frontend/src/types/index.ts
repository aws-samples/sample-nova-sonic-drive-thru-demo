// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

// The menu and screen types come from the protocol, which is defined once in agent/protocol.py
// and generated into ../protocol/messages.ts. Prices are integers in fils (1/100 AED).
import type { BurgerBuilder, CustomBurgerOptions, Menu, ScreenState } from '../protocol/messages';

export type { BurgerTopping, Category, CustomBurgerOptions, MenuItem, OrderItem, ScreenState } from '../protocol/messages';

// The build-your-own burger in progress, as the agent shows it
export type BurgerBuilderState = BurgerBuilder;

// The menu: sent by the agent once per connection (CUSTOM "menu" event)
export type MenuData = Menu;

// Everything the agent shows: the menu (with the burger options, null until it arrives), and
// the screen state it sends whole after every change (STATE_SNAPSHOT event)
export type AgentUIState = Omit<MenuData, 'customBurger'> & { customBurger: CustomBurgerOptions | null } & ScreenState;

// Full application state
export interface AppState {
  agentUI: AgentUIState;
  // Which snapshot the screen shows. A snapshot from the same epoch with a version no newer
  // than this is out of date and ignored; a new epoch means the agent started a new session.
  sync: { epoch: string | null; version: number };
  voice: {
    sessionActive: boolean;
    listening: boolean;
    reconnecting: boolean;
    micPermission: 'granted' | 'denied' | 'prompt';
  };
}
