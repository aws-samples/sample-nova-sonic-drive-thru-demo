// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, it, expect, afterEach } from 'vitest';
import fc from 'fast-check';
import { cleanup, render, screen } from '@testing-library/react';
import { MenuItemCard } from './MenuItemCard';
import { formatPrice } from '../utils/formatPrice';
import type { MenuItem } from '../types';

afterEach(cleanup);

// --- Arbitrary ---

/** Generate a non-empty, non-whitespace-only string (safe for DOM text queries). */
const arbVisibleString = (max = 50) =>
  fc
    .array(fc.constantFrom(...'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'), {
      minLength: 1,
      maxLength: max,
    })
    .map((chars) => chars.join(''));

const arbMenuItem: fc.Arbitrary<MenuItem> = fc.record({
  itemId: fc.string({ minLength: 1, maxLength: 20 }),
  categoryId: fc.string({ minLength: 1, maxLength: 20 }),
  name: arbVisibleString(50),
  description: arbVisibleString(80),
  price: fc.integer({ min: 1, max: 99999 }),
  imageUrl: fc.webUrl(),
  category: fc.string({ minLength: 1, maxLength: 30 }),
  featured: fc.boolean(),
  sortOrder: fc.integer({ min: 0, max: 999 }),
});

// ============================================================
// Property 2: Menu item rendering includes all required information
// Validates: Requirements 1.2
// ============================================================
describe('Property 2: Menu item rendering includes all required information', () => {
  it('rendered MenuItemCard contains name, formatted price, and image with valid src', () => {
    /**
     * **Validates: Requirements 1.2**
     * For any MenuItem, the rendered card should contain the item's name, formatted
     * price, and an image element with a valid src attribute. The description is shown
     * in the item detail modal (see ItemDetailModal.test.tsx), not on the card.
     */
    fc.assert(
      fc.property(arbMenuItem, (item) => {
        cleanup();
        render(<MenuItemCard item={item} />);

        // Name is rendered
        expect(screen.getByText(item.name)).toBeDefined();

        // Formatted price is rendered. formatPrice uses a non-breaking space, which
        // testing-library's default normalizer collapses to a plain space in DOM text.
        const priceText = formatPrice(item.price).replace(/\s+/g, ' ');
        expect(screen.getByText(priceText)).toBeDefined();

        // Image element with correct src and alt
        const img = screen.getByRole('img', { name: item.name });
        expect(img).toBeDefined();
        expect(img.getAttribute('src')).toBe(item.imageUrl);
      }),
      { numRuns: 100 },
    );
  });
});
