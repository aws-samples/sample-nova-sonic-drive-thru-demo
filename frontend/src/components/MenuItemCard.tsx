// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import type { MenuItem } from '../types';
import { formatPrice } from '../utils/formatPrice';

interface MenuItemCardProps {
  item: MenuItem;
  highlighted?: boolean;
}

/** A display-only menu card: ordering is purely by voice, so the card is not interactive. */
export function MenuItemCard({ item, highlighted = false }: MenuItemCardProps) {
  return (
    <article
      className={`menu-item-card${highlighted ? ' menu-item-card--highlighted' : ''}`}
      style={{
        border: highlighted ? '2px solid #e67e22' : '1px solid #ddd',
        borderRadius: '8px',
        padding: '12px',
        backgroundColor: highlighted ? '#fef9e7' : '#fff',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        transition: 'border-color 0.2s, background-color 0.2s',
      }}
    >
      <img
        src={item.imageUrl}
        alt={item.name}
        width={200}
        height={200}
        style={{ width: 200, height: 200, objectFit: 'cover', borderRadius: '6px' }}
        onError={(e) => {
          const img = e.target as HTMLImageElement;
          img.onerror = null; // prevent infinite loop
          img.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" fill="%23eee"/><text x="100" y="105" text-anchor="middle" font-family="sans-serif" font-size="14" fill="%23999">No image</text></svg>';
        }}
      />
      <h3 style={{ margin: '8px 0 4px' }}>{item.name}</h3>
      <span style={{ fontWeight: 'bold', color: '#27ae60' }}>{formatPrice(item.price)}</span>
    </article>
  );
}
