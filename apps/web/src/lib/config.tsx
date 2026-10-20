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
import type { AppConfig } from "./types";

interface ConfigContextValue {
  config: AppConfig | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

const ConfigContext = createContext<ConfigContextValue | null>(null);

export function ConfigProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.config();
      setConfig(next);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t));
    }
  }, [t]);

  useEffect(() => {
    let alive = true;
    api
      .config()
      .then((next) => {
        if (!alive) return;
        setConfig(next);
      })
      .catch((err) => {
        if (!alive) return;
        setError(errorMessage(err, t));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [t]);

  const value = useMemo<ConfigContextValue>(
    () => ({ config, loading, error, refresh }),
    [config, loading, error, refresh],
  );

  return <ConfigContext.Provider value={value}>{children}</ConfigContext.Provider>;
}

export function useConfig(): ConfigContextValue {
  const context = useContext(ConfigContext);
  if (!context) throw new Error("useConfig must be used inside ConfigProvider");
  return context;
}