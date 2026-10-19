import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api } from "./api";
import { errorMessage, useI18n } from "./i18n";
import type { AppConfig, Me } from "./types";

interface MeContextValue {
  me: Me | null;
  config: AppConfig | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  setMe: (me: Me) => void;
  logout: () => Promise<void>;
}

const MeContext = createContext<MeContextValue | null>(null);

export function MeProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [me, setMeState] = useState<Me | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.me();
      setMeState(next);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t));
    }
  }, [t]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [nextMe, nextConfig] = await Promise.all([api.me(), api.config()]);
        if (!alive) return;
        setMeState(nextMe);
        setConfig(nextConfig);
      } catch (err) {
        if (!alive) return;
        setError(errorMessage(err, t));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [t]);

  const setMe = useCallback((next: Me) => {
    setMeState(next);
    setError(null);
  }, []);

  const logout = useCallback(async () => {
    await api.logout();
    await refresh();
  }, [refresh]);

  const value = useMemo<MeContextValue>(
    () => ({ me, config, loading, error, refresh, setMe, logout }),
    [me, config, loading, error, refresh, setMe, logout],
  );

  return <MeContext.Provider value={value}>{children}</MeContext.Provider>;
}

export function useMe(): MeContextValue {
  const context = useContext(MeContext);
  if (!context) throw new Error("useMe must be used inside MeProvider");
  return context;
}
