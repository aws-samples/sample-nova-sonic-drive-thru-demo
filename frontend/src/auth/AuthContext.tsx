// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import {
  useState,
  useEffect,
  useCallback,
  useRef,
  type ReactNode,
} from 'react';
import {
  signIn as amplifySignIn,
  signOut as amplifySignOut,
  getCurrentUser,
  fetchAuthSession,
} from 'aws-amplify/auth';
import { AuthContext, type AuthContextValue, type AuthState } from './useAuth';



const TOKEN_REFRESH_INTERVAL_MS = 10 * 60 * 1000; // 10 minutes (tokens expire in 15 min)

function friendlyAuthError(err: unknown): string {
  if (err instanceof Error) {
    if (err.name === 'NotAuthorizedException') {
      return 'Incorrect username or password.';
    }
    if (err.name === 'UserNotFoundException') {
      return 'Account not found. Please check your username.';
    }
    if (err.name === 'UserNotConfirmedException') {
      return 'Account not confirmed. Please verify your email.';
    }
    return err.message;
  }
  return 'An unexpected error occurred.';
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    authenticated: false,
    userId: null,
    loading: true,
    error: null,
  });
  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearRefreshTimer = useCallback(() => {
    if (refreshTimerRef.current) {
      clearInterval(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
  }, []);

  const startRefreshTimer = useCallback(() => {
    clearRefreshTimer();
    refreshTimerRef.current = setInterval(async () => {
      try {
        await fetchAuthSession({ forceRefresh: true });
      } catch {
        // Refresh failed — session may have expired
      }
    }, TOKEN_REFRESH_INTERVAL_MS);
  }, [clearRefreshTimer]);

  // Check for existing session on mount
  useEffect(() => {
    let cancelled = false;
    async function checkSession() {
      try {
        const user = await getCurrentUser();
        if (!cancelled) {
          setState({
            authenticated: true,
            userId: user.userId,
            loading: false,
            error: null,
          });
          startRefreshTimer();
        }
      } catch {
        if (!cancelled) {
          setState({
            authenticated: false,
            userId: null,
            loading: false,
            error: null,
          });
        }
      }
    }
    void checkSession();
    return () => {
      cancelled = true;
    };
  }, [startRefreshTimer]);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => clearRefreshTimer();
  }, [clearRefreshTimer]);

  const signIn = useCallback(
    async (username: string, password: string) => {
      setState((prev) => ({ ...prev, loading: true, error: null }));
      try {
        await amplifySignIn({ username, password });
        const user = await getCurrentUser();
        setState({
          authenticated: true,
          userId: user.userId,
          loading: false,
          error: null,
        });
        startRefreshTimer();
      } catch (err) {
        setState((prev) => ({
          ...prev,
          loading: false,
          error: friendlyAuthError(err),
        }));
        throw err;
      }
    },
    [startRefreshTimer],
  );

  const signOut = useCallback(async () => {
    try {
      await amplifySignOut();
    } finally {
      clearRefreshTimer();
      setState({
        authenticated: false,
        userId: null,
        loading: false,
        error: null,
      });
    }
  }, [clearRefreshTimer]);

  const getJwtToken = useCallback(async (): Promise<string> => {
    const session = await fetchAuthSession();
    const token = session.tokens?.idToken?.toString();
    if (!token) {
      throw new Error('No JWT token available.');
    }
    return token;
  }, []);

  const getAwsCredentials = useCallback(async () => {
    const session = await fetchAuthSession();
    const creds = session.credentials;
    if (!creds) {
      throw new Error('No AWS credentials available.');
    }
    return {
      accessKeyId: creds.accessKeyId,
      secretAccessKey: creds.secretAccessKey,
      sessionToken: creds.sessionToken,
    };
  }, []);

  const refreshToken = useCallback(async (): Promise<string> => {
    const session = await fetchAuthSession({ forceRefresh: true });
    const token = session.tokens?.idToken?.toString();
    if (!token) {
      throw new Error('Token refresh failed.');
    }
    return token;
  }, []);

  const value: AuthContextValue = {
    ...state,
    signIn,
    signOut,
    getJwtToken,
    getAwsCredentials,
    refreshToken,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
