// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ItemDetailModal } from './ItemDetailModal';
import { useAppStore } from '../store';
import type { MenuItem } from '../types';

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

function highlight(itemId: string | null) {
  const agentUI = useAppStore.getState().agentUI;
  useAppStore.getState().applyAgentUIState({
    ...agentUI,
    menuItems: { burgers: [burger] },
    highlightedItem: itemId,
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
