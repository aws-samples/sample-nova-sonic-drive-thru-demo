// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MenuItemCard } from './MenuItemCard';
import type { MenuItem } from '../types';

const sampleItem: MenuItem = {
  itemId: 'item-1',
  categoryId: 'cat-1',
  name: 'Classic Burger',
  description: 'A juicy beef patty with lettuce and tomato',
  price: 2900,
  imageUrl: 'https://cdn.example.com/burger.jpg',
  category: 'Burgers',
  featured: false,
  sortOrder: 1,
};

describe('MenuItemCard', () => {
  it('renders item name and formatted price', () => {
    render(<MenuItemCard item={sampleItem} />);

    expect(screen.getByText('Classic Burger')).toBeInTheDocument();
    expect(screen.getByText('AED 29.00')).toBeInTheDocument();
    // The card is kept compact; the description is shown in ItemDetailModal instead
    expect(screen.queryByText('A juicy beef patty with lettuce and tomato')).not.toBeInTheDocument();
  });

  it('renders an image with alt text and correct src', () => {
    render(<MenuItemCard item={sampleItem} />);

    const img = screen.getByRole('img', { name: 'Classic Burger' });
    expect(img).toHaveAttribute('src', 'https://cdn.example.com/burger.jpg');
    expect(img).toHaveAttribute('width', '200');
    expect(img).toHaveAttribute('height', '200');
  });

  it('applies highlighted styles when highlighted is true', () => {
    const { container } = render(<MenuItemCard item={sampleItem} highlighted />);

    const card = container.querySelector('.menu-item-card--highlighted');
    expect(card).toBeInTheDocument();
  });

  it('does not apply highlighted class when highlighted is false', () => {
    const { container } = render(<MenuItemCard item={sampleItem} highlighted={false} />);

    const card = container.querySelector('.menu-item-card--highlighted');
    expect(card).not.toBeInTheDocument();
  });

  it('calls onClick with the item when clicked', () => {
    const handleClick = vi.fn();
    render(<MenuItemCard item={sampleItem} onClick={handleClick} />);

    fireEvent.click(screen.getByRole('button'));
    expect(handleClick).toHaveBeenCalledWith(sampleItem);
  });

  it('calls onClick on Enter key press', () => {
    const handleClick = vi.fn();
    render(<MenuItemCard item={sampleItem} onClick={handleClick} />);

    fireEvent.keyDown(screen.getByRole('button'), { key: 'Enter' });
    expect(handleClick).toHaveBeenCalledWith(sampleItem);
  });

  it('renders without onClick without crashing', () => {
    render(<MenuItemCard item={sampleItem} />);
    fireEvent.click(screen.getByRole('button'));
    // no error thrown
  });
});
