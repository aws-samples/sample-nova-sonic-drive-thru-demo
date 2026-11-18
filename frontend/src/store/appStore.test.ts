// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, it, expect, beforeEach } from 'vitest';
import { useAppStore } from './appStore';
import type { ScreenState } from '../types';
import { CUSTOM_BURGER } from '../test/fixtures';

const screen = (overrides: Partial<ScreenState> = {}): ScreenState => ({
  highlightedCategory: null,
  highlightedItem: null,
  orderItems: [],
  orderTotal: 0,
  orderConfirmed: false,
  orderNumber: null,
  burgerBuilder: null,
  ...overrides,
});

describe('agent screen state', () => {
  beforeEach(() => useAppStore.getState().resetAgentUI());

  it('keeps the menu when a snapshot arrives', () => {
    const { applyMenu, applySnapshot } = useAppStore.getState();
    applyMenu({ categories: [{ categoryId: 'drinks', name: 'Drinks', sortOrder: 1 }], menuItems: { drinks: [] }, customBurger: CUSTOM_BURGER });
    applySnapshot('e1', 1, screen({ orderTotal: 900 }));
    const { agentUI } = useAppStore.getState();
    expect(agentUI.categories).toHaveLength(1);
    expect(agentUI.orderTotal).toBe(900);
  });

  it('ignores a snapshot older than the one on screen', () => {
    const { applySnapshot } = useAppStore.getState();
    expect(applySnapshot('e1', 2, screen({ orderTotal: 1800 }))).toBe(true);
    expect(applySnapshot('e1', 1, screen({ orderTotal: 900 }))).toBe(false);
    expect(applySnapshot('e1', 2, screen({ orderTotal: 900 }))).toBe(false);
    expect(useAppStore.getState().agentUI.orderTotal).toBe(1800);
  });

  it('accepts any version from a new agent session', () => {
    const { applySnapshot } = useAppStore.getState();
    applySnapshot('e1', 7, screen({ orderTotal: 1800 }));
    expect(applySnapshot('e2', 0, screen())).toBe(true);
    expect(useAppStore.getState().agentUI.orderTotal).toBe(0);
  });

  it('starts over after a reset, for the next customer', () => {
    const { applySnapshot, resetAgentUI } = useAppStore.getState();
    applySnapshot('e1', 7, screen({ orderConfirmed: true }));
    resetAgentUI();
    expect(useAppStore.getState().agentUI.orderConfirmed).toBe(false);
    expect(applySnapshot('e1', 0, screen())).toBe(true);
  });
});
