// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, it, expect } from 'vitest';
import { formatPrice } from './formatPrice';

// formatPrice separates the currency code and amount with a non-breaking space.
const NBSP = '\u00A0';

describe('formatPrice', () => {
  it('formats zero fils as AED 0.00', () => {
    expect(formatPrice(0)).toBe(`AED${NBSP}0.00`);
  });

  it('formats 100 fils as AED 1.00', () => {
    expect(formatPrice(100)).toBe(`AED${NBSP}1.00`);
  });

  it('formats 999 fils as AED 9.99', () => {
    expect(formatPrice(999)).toBe(`AED${NBSP}9.99`);
  });

  it('formats 1 fils as AED 0.01', () => {
    expect(formatPrice(1)).toBe(`AED${NBSP}0.01`);
  });

  it('formats 1050 fils as AED 10.50', () => {
    expect(formatPrice(1050)).toBe(`AED${NBSP}10.50`);
  });

  it('formats large values correctly', () => {
    expect(formatPrice(99999)).toBe(`AED${NBSP}999.99`);
  });
});
