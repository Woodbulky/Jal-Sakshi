'use client';
import { useMemo } from 'react';
import { getNetwork, getSensorHealth } from '@/lib/api/endpoints';
import { assetsById, toMapAsset, toMapEdge, untrustedSet } from '@/lib/adapters';
import type { Severity } from '@/types/api';
import { useApiResource } from './useApiResource';

/**
 * The live network: nodes, edges and each sensor's latest value.
 *
 * Empty when the backend is unreachable, never a stand-in topology. A map of
 * invented assets is worse than no map: it shows a village a network it does
 * not have, and nothing on screen distinguishes the two. `live` says whether
 * what is displayed came from the backend.
 */
export function useNetwork({
  intervalMs = 10_000,
  incidentSeverityByAsset,
}: {
  intervalMs?: number;
  /** asset_code → severity, so a diagnosed fault colours its asset. */
  incidentSeverityByAsset?: Map<string, Severity>;
} = {}) {
  const network = useApiResource((signal) => getNetwork(undefined, { signal }), {
    intervalMs,
  });
  const health = useApiResource((signal) => getSensorHealth({ signal }), {
    intervalMs: intervalMs * 3,
  });

  const live = network.data !== null;

  const { assets, edges } = useMemo(() => {
    if (!network.data) {
      return {
        assets: [] as ReturnType<typeof toMapAsset>[],
        edges: [] as ReturnType<typeof toMapEdge>[],
      };
    }

    const byId = assetsById(network.data.nodes);
    const untrusted = health.data ? untrustedSet(health.data) : undefined;
    const total = network.data.nodes.length;

    const mapped = network.data.nodes.map((asset, index) =>
      toMapAsset(asset, {
        index,
        total,
        sensors: network.data!.sensors,
        incidentSeverity: incidentSeverityByAsset?.get(asset.asset_code),
        untrustedSensors: untrusted,
      }),
    );

    const dead = new Set(
      mapped.filter((a) => a.status === 'critical').map((a) => a.id),
    );

    return {
      assets: mapped,
      edges: network.data.edges.map((edge) => toMapEdge(edge, byId, dead)),
    };
  }, [network.data, health.data, incidentSeverityByAsset]);

  // Sensors reference assets by UUID; every view in the console shows codes.
  const assetCodeById = useMemo(
    () => new Map((network.data?.nodes ?? []).map((a) => [a.id, a.asset_code])),
    [network.data],
  );

  return {
    assets,
    edges,
    assetCodeById,
    sensors: network.data?.sensors ?? [],
    serviceArea: network.data?.service_area ?? null,
    sensorHealth: health.data ?? [],
    untrusted: health.data ? untrustedSet(health.data) : new Set<string>(),
    live,
    loading: network.loading,
    error: network.error,
    refresh: network.refresh,
  };
}
