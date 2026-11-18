// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import type { CustomBurgerOptions } from '../types';

/** Burger options as the agent sends them with the menu (a subset of agent/custom_burger.py). */
export const CUSTOM_BURGER: CustomBurgerOptions = {
  basePrice: 3300,
  patties: ['beef patty', 'chicken patty'],
  toppings: [
    { name: 'cheddar cheese', price: 400 },
    { name: 'bacon', price: 600 },
    { name: 'lettuce', price: 0 },
  ],
  sauces: ['ketchup'],
};
