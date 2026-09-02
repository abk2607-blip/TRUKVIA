import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";

/**
 * Iter132c C2 · Feature-flag probe for CN/DN UI.
 *
 * The backend gates every CN/DN endpoint by ENABLE_CDN=1 and returns 404
 * when the flag is unset (Iter130 fail-secure pattern). We call the
 * lightest possible list endpoint (limit=1) and cache the result for the
 * whole session. Any 404/network error → fail-secure hidden UI.
 *
 * Zero new backend endpoint; reuses the CN list endpoint the /notes page
 * would call anyway.
 */
export function useCdnEnabled() {
  const q = useQuery({
    queryKey: ["cdn-enabled"],
    queryFn: async () => {
      const r = await api.get("/credit-notes", { params: { limit: 1 } });
      return Array.isArray(r.data);
    },
    staleTime: Infinity,
    retry: false,
  });
  return q.data === true;
}

/** Same probe but surfaces loading/settled state so pages that want to
 *  hard-redirect on disabled can avoid the initial-render race where
 *  q.data is undefined before the query resolves. */
export function useCdnEnabledState() {
  const q = useQuery({
    queryKey: ["cdn-enabled"],
    queryFn: async () => {
      const r = await api.get("/credit-notes", { params: { limit: 1 } });
      return Array.isArray(r.data);
    },
    staleTime: Infinity,
    retry: false,
  });
  return { enabled: q.data === true, settled: q.isFetched };
}
