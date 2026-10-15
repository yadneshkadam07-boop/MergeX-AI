import { useQuery } from "@tanstack/react-query";

import { getLiveness, healthKeys } from "@/api/health";

/**
 * Poll backend liveness.
 *
 * Used by the shell to tell "the API is down" apart from "the API answered
 * and there is simply nothing to show yet".
 */
export function useBackendStatus() {
  return useQuery({
    queryKey: healthKeys.liveness,
    queryFn: getLiveness,
    refetchInterval: 30_000,
    retry: 1,
    staleTime: 10_000,
  });
}
