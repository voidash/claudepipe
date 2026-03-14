import { useState, useEffect, useCallback } from "react";
import type { FootageManifest } from "../types/manifest";
import { fetchManifest, fetchUnitManifest } from "../api/client";

interface UseManifestResult {
  manifest: FootageManifest | null;
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
}

export function useManifest(): UseManifestResult {
  const [manifest, setManifest] = useState<FootageManifest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchManifest();
      setManifest(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load manifest");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  return { manifest, loading, error, reload };
}

interface UseUnitManifestResult {
  unitManifest: FootageManifest | null;
  loading: boolean;
  error: string | null;
}

export function useUnitManifest(unitId: string | null): UseUnitManifestResult {
  const [unitManifest, setUnitManifest] = useState<FootageManifest | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!unitId) {
      setUnitManifest(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchUnitManifest(unitId)
      .then((data) => {
        if (!cancelled) setUnitManifest(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load unit manifest");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [unitId]);

  return { unitManifest, loading, error };
}
