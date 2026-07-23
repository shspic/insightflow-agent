import { createContext, useContext, useEffect, useMemo, useState } from "react";
import * as authApi from "../api/auth";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  async function refreshUser() {
    try {
      const currentUser = await authApi.fetchCurrentUser();
      setUser(currentUser);
      return currentUser;
    } catch (error) {
      if (error.status !== 401) {
        throw error;
      }
      setUser(null);
      return null;
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    refreshUser();
    const clear = () => setUser(null);
    const forceChange = () => setUser((current) => (
      current ? { ...current, must_change_password: true } : current
    ));
    window.addEventListener("auth:unauthorized", clear);
    window.addEventListener("auth:password-change-required", forceChange);
    return () => {
      window.removeEventListener("auth:unauthorized", clear);
      window.removeEventListener("auth:password-change-required", forceChange);
    };
  }, []);

  const value = useMemo(() => ({
    user,
    isLoading,
    refreshUser,
    async login(payload) {
      const result = await authApi.login(payload);
      setUser(result.user);
      return result;
    },
    async logout() {
      try {
        await authApi.logout();
      } finally {
        setUser(null);
      }
    },
    async changePassword(payload) {
      const result = await authApi.changePassword(payload);
      setUser(result.user);
      return result;
    },
  }), [user, isLoading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth 必须在 AuthProvider 内使用");
  }
  return context;
}
