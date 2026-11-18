// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

// Generated from agent/protocol.py: run `python -m agent.protocol`, then `npm run gen:protocol`.
// Do not edit by hand.

/**
 * One JSON text frame from the server.
 */
export type ServerMessage = MenuEvent | StateSnapshotEvent | SessionEndedEvent | InterruptionEvent;

export interface MenuEvent {
  type: 'CUSTOM';
  name: 'menu';
  value: Menu;
}
export interface Menu {
  categories: Category[];
  menuItems: {
    [k: string]: MenuItem[];
  };
}
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
  /**
   * An amount in fils (100 fils = 1 AED).
   */
  price: number;
  imageUrl: string;
  category: string;
  featured: boolean;
  sortOrder: number;
}
export interface StateSnapshotEvent {
  type: 'STATE_SNAPSHOT';
  epoch: string;
  version: number;
  snapshot: ScreenState;
}
/**
 * Everything the screen shows apart from the menu. Only the agent's tools change it.
 */
export interface ScreenState {
  highlightedCategory: string | null;
  highlightedItem: string | null;
  orderItems: OrderItem[];
  /**
   * An amount in fils (100 fils = 1 AED).
   */
  orderTotal: number;
  orderConfirmed: boolean;
  orderNumber: string | null;
  burgerBuilder: BurgerBuilder | null;
}
export interface OrderItem {
  itemId: string;
  name: string;
  quantity: number;
  /**
   * An amount in fils (100 fils = 1 AED).
   */
  unitPrice: number;
  specialInstructions: string;
}
/**
 * The build-your-own burger in progress, priced by the server.
 */
export interface BurgerBuilder {
  active: boolean;
  patty: string | null;
  toppings: string[];
  sauces: string[];
  /**
   * An amount in fils (100 fils = 1 AED).
   */
  price: number;
}
export interface SessionEndedEvent {
  type: 'CUSTOM';
  name: 'session_ended';
  value: SessionEnded;
}
export interface SessionEnded {
  reason: 'order-complete' | 'idle-timeout' | 'conversation-ended' | 'agent-error';
}
export interface InterruptionEvent {
  type: 'bidi_interruption';
  reason: string;
}

/**
 * The format of every binary frame, in both directions. Nova Sonic is configured for it.
 */
export interface AudioFormat {
  sampleRate: 16000;
  channels: 1;
  encoding: 'pcm_s16le';
}

/** The format of every binary frame, in both directions. */
export const AUDIO_FORMAT = {
  sampleRate: 16000,
  channels: 1,
  encoding: 'pcm_s16le',
} as const satisfies AudioFormat;
