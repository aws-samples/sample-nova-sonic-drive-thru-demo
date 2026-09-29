// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

// Menu data types

export interface Category {
  categoryId: string;
  name: string;
  sortOrder: number;
}

export interface MenuItem {
  itemId: string;
  categoryId: string;
  name: string;
  description: string;
  price: number; // fils (1/100 AED)
  imageUrl: string;
  category: string;
  featured: boolean;
  sortOrder: number;
}

export interface OrderItem {
  itemId: string;
  name: string;
  quantity: number;
  unitPrice: number; // fils (1/100 AED)
  specialInstructions?: string;
}

// Agent-controlled UI state — sent as a complete snapshot via update_ui tool
export interface BurgerBuilderState {
  active: boolean;
  patty: string | null;
  toppings: string[];
  sauces: string[];
  price: number; // fils — running total
}

export interface AgentUIState {
  categories: Category[];
  menuItems: Record<string, MenuItem[]>; // categoryId -> items
  highlightedCategory: string | null;
  highlightedItem: string | null;
  orderItems: OrderItem[];
  orderTotal: number;
  orderConfirmed: boolean;
  orderNumber: string | null;
  burgerBuilder: BurgerBuilderState | null;
}

// The menu: sent by the agent once per connection (CUSTOM "menu" event)
export type MenuData = Pick<AgentUIState, 'categories' | 'menuItems'>;

// Everything else on screen: sent whole after every change (STATE_SNAPSHOT event)
export type ScreenState = Omit<AgentUIState, 'categories' | 'menuItems'>;

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
