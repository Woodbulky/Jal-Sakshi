'use client';
import { useMemo } from 'react';
import { getNetwork, getSensorHealth } from '@/lib/api/endpoints';
import { assetsById, toMapAsset, toMapEdge, untrustedSet } from '@/lib/adapters';
import { ASSETS, ASSET_CONNECTIONS } from '@/lib/mock-data';
import type { Severity } from '@/types/api';
import { useApiResource } from './useApiResource';

/**
 * The live network: nodes, edges and each sensor's latest value.
 *
 * Falls back to the Vitpur mock topology when the backend is unreachable so a
 * demo never shows a blank map — `live` says which one is on screen.
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
      return { assets: ASSETS, edges: ASSET_CONNECTIONS };
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
