// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BurgerBuilder } from './BurgerBuilder';
import { useAppStore } from '../store';
import { CUSTOM_BURGER } from '../test/fixtures';

function show(toppings: string[], customBurger = CUSTOM_BURGER) {
  const { applyMenu, applySnapshot } = useAppStore.getState();
  applyMenu({ categories: [], menuItems: {}, customBurger });
  applySnapshot('e1', 1, {
    highlightedCategory: null, highlightedItem: null, orderItems: [], orderTotal: 0,
    orderConfirmed: false, orderNumber: null,
    burgerBuilder: { active: true, patty: 'beef patty', toppings, sauces: [], price: 4300 },
  });
}

describe('BurgerBuilder', () => {
  beforeEach(() => useAppStore.getState().resetAgentUI());

  it('shows the add-on prices the agent sent with the menu', () => {
    show(['bacon']);
    render(<BurgerBuilder />);
    expect(screen.getByText('+AED 6.00')).toBeInTheDocument();
    expect(screen.getByText('AED 43.00')).toBeInTheDocument(); // the total is the server's
  });

  it('follows a price change on the server, with no frontend change', () => {
    show(['bacon'], { ...CUSTOM_BURGER, toppings: [{ name: 'bacon', price: 750 }] });
    render(<BurgerBuilder />);
    expect(screen.getByText('+AED 7.50')).toBeInTheDocument();
  });
});
