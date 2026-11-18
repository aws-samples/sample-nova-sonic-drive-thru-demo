// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ItemDetailModal } from './ItemDetailModal';
import { useAppStore } from '../store';
import type { MenuItem } from '../types';
import { CUSTOM_BURGER } from '../test/fixtures';

const burger: MenuItem = {
  itemId: 'classic-burger',
  categoryId: 'burgers',
  name: 'Classic Burger',
  description: 'Quarter-pound beef patty with lettuce, tomato, onion, and pickles',
  price: 2900,
  imageUrl: 'images/classic-burger.png',
  category: 'Burgers',
  featured: true,
  sortOrder: 1,
};

let version = 0;

function highlight(itemId: string | null) {
  const { applyMenu, applySnapshot, agentUI } = useAppStore.getState();
  applyMenu({ categories: [], menuItems: { burgers: [burger] }, customBurger: CUSTOM_BURGER });
  applySnapshot('test-epoch', ++version, {
    highlightedCategory: agentUI.highlightedCategory,
    highlightedItem: itemId,
    orderItems: agentUI.orderItems,
    orderTotal: agentUI.orderTotal,
    orderConfirmed: agentUI.orderConfirmed,
    orderNumber: agentUI.orderNumber,
    burgerBuilder: agentUI.burgerBuilder,
  });
}

describe('ItemDetailModal', () => {
  beforeEach(() => highlight(null));

  it('shows the highlighted item with its description and price (Requirement 1.2)', () => {
    highlight('classic-burger');
    render(<ItemDetailModal />);

    expect(screen.getByRole('heading', { name: 'Classic Burger' })).toBeInTheDocument();
    expect(screen.getByText(burger.description)).toBeInTheDocument();
    expect(screen.getByText('AED 29.00')).toBeInTheDocument();
  });

  it('renders nothing when no item is highlighted', () => {
    const { container } = render(<ItemDetailModal />);
    expect(container).toBeEmptyDOMElement();
  });

  it('stays closed for the build-your-own burger, which has its own builder', () => {
    highlight('custom-burger');
    const { container } = render(<ItemDetailModal />);
    expect(container).toBeEmptyDOMElement();
  });
});
