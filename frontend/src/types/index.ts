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

// The event the agent sends over WebSocket
export interface UIStateUpdateEvent {
  type: 'ui_state_update';
  state: AgentUIState;
}

// Legacy UI_Event types kept for backward compat (can be removed later)
export type UIEvent = UIStateUpdateEvent;

// Frontend -> Agent
export interface UIState {
  visibleCategory: string | null;
  selectedItem: string | null;
  orderItems: OrderItem[];
  orderTotal: number;
}

// Full application state
export interface AppState {
  agentUI: AgentUIState;
  voice: {
    sessionActive: boolean;
    listening: boolean;
    micPermission: 'granted' | 'denied' | 'prompt';
  };
}
