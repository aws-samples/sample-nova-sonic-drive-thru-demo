// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { createContext, useContext } from 'react';

export interface AuthState {
  authenticated: boolean;
  userId: string | null;
  loading: boolean;
  error: string | null;
}

export interface AuthContextValue extends AuthState {
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  getJwtToken: () => Promise<string>;
  getAwsCredentials: () => Promise<{
    accessKeyId: string;
    secretAccessKey: string;
    sessionToken?: string;
  }>;
  refreshToken: () => Promise<string>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
