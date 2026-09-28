// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Format a price in fils (1/100 of a UAE dirham) as a string like "AED 29.00".
 * A non-breaking space keeps the currency code and amount on the same line.
 */
export function formatPrice(fils: number): string {
  const dirhams = (fils / 100).toFixed(2);
  return `AED\u00A0${dirhams}`;
}
