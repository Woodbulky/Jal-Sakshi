'use client';
import { useState, useRef, useMemo } from 'react';
import { useNetwork } from '@/hooks/useNetwork';
import type { Asset, AssetConnection, Severity } from '@/types/api';

const STATUS_COLORS: Record<string, string> = {
  normal: '#22B463',
  warn: '#F0A11B',
  critical: '#EF4444',
  offline: '#8296A8',
  maintenance: '#3FC6E8',
};

const STATUS_PULSE: Record<string, string> = {
  normal: '#22B463',
  warn: '#F0A11B',
  critical: '#EF4444',
};

interface Props {
  /** asset_code → severity of the incident sitting on it. */
  severityByAsset?: Map<string, Severity>;
  onSelect?: (asset: Asset) => void;
}

export default function WaterNetworkMap({ severityByAsset, onSelect }: Props) {
  const { assets, edges, serviceArea, live } = useNetwork({
    incidentSeverityByAsset: severityByAsset,
  });
  const [tooltip, setTooltip] = useState<{ x: number; y: number; asset: Asset } | null>(null);
  const [showZones, setShowZones] = useState(true);
  const [showFlow, setShowFlow] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);

  // Topology comes from the backend as asset codes; the map needs coordinates.
  const pipes = useMemo(() => {
    const at = new Map(assets.map((a) => [a.id, a]));
    return edges
      .map((edge: AssetConnection) => {
        const from = at.get(edge.from_asset_id);
        const to = at.get(edge.to_asset_id);
        if (!from || !to || from.x === undefined || to.x === undefined) return null;
        return {
          key: `${edge.from_asset_id}-${edge.to_asset_id}`,
          d: `M${from.x} ${from.y} L${to.x} ${to.y}`,
          dead: edge.status === 'dead',
          trunk: edge.pipe_type.includes('rising') || edge.pipe_type.includes('trunk'),
        };
      })
      .filter((p): p is NonNullable<typeof p> => p !== null);
  }, [assets, edges]);

  const criticalCount = assets.filter((a) => a.status === 'critical').length;

  const viewBox = (() => {
    const w = 1000 / zoom, h = 540 / zoom;
    return `${(1000 - w) / 2} ${(540 - h) / 2} ${w} ${h}`;
  })();

  return (
    <div className="mapwrap" ref={wrapRef} style={{ position: 'relative' }}>
      <svg viewBox={viewBox} style={{ display: 'block', width: '100%', height: 'auto', minHeight: 320 }}>
        <defs>
          <radialGradient id="terrain"><stop offset="0%" stopColor="#2D4A28" /><stop offset="100%" stopColor="#1C3320" /></radialGradient>
          <linearGradient id="river" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#1A4E68" /><stop offset="100%" stopColor="#154060" /></linearGradient>
          <linearGradient id="pipeG" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stopColor="#3FC6E8" /><stop offset="100%" stopColor="#22B463" /></linearGradient>
          <filter id="glow"><feDropShadow dx="0" dy="0" stdDeviation="3" floodColor="#EF4444" floodOpacity=".5" /></filter>
        </defs>

        {/* Terrain background */}
        <rect width="1000" height="540" fill="url(#terrain)" />
        {/* Field parcels */}
        <g opacity=".14">
          {[
            "M40 340 L140 310 L160 380 L50 400Z",
            "M150 310 L280 360 L260 430 L140 400Z",
            "M700 60 L820 40 L840 100 L710 110Z",
            "M820 320 L940 300 L960 370 L830 380Z",
            "M50 100 L170 80 L180 140 L60 150Z",
          ].map((d, i) => <path key={i} d={d} fill="#3D6B32" />)}
        </g>
        {/* Contour lines */}
        <g stroke="#3A6430" strokeWidth="1" fill="none" opacity=".25">
          <path d="M0 480 Q200 440 400 460 T800 420 T1000 450" />
          <path d="M0 400 Q250 360 500 380 T1000 350" />
          <path d="M0 200 Q300 170 600 190 T1000 170" />
        </g>
        {/* River */}
        <path d="M0 220 Q100 200 180 260 Q260 320 380 300 Q500 280 560 320 Q620 360 700 340 Q800 310 900 350 Q960 370 1000 360" fill="none" stroke="url(#river)" strokeWidth="18" opacity=".55" strokeLinecap="round" />
        <path d="M0 220 Q100 200 180 260 Q260 320 380 300 Q500 280 560 320 Q620 360 700 340 Q800 310 900 350 Q960 370 1000 360" fill="none" stroke="#2A6A8A" strokeWidth="2" opacity=".3" strokeDasharray="4 6" />
        {/* Roads */}
        <g stroke="#4A6B4A" strokeWidth="2" opacity=".35" strokeDasharray="8 6">
          <path d="M0 270 L400 250 L600 220 L1000 240" />
          <path d="M500 0 L480 270 L500 540" />
        </g>
        {/* Settlement blocks */}
        <g opacity=".18">
          <rect x="840" y="110" width="80" height="50" rx="3" fill="#5A8A50" />
          <rect x="560" y="280" width="50" height="40" rx="3" fill="#5A8A50" />
        </g>

        {/* Zone polygons */}
        {showZones && (
          <g id="zones">
            <path d="M710 245 L760 220 L860 110 L940 90 L950 160 L870 310 L770 310Z" fill="rgba(239,68,68,.10)" stroke="rgba(239,68,68,.35)" strokeWidth="1.5" strokeDasharray="6 4" />
            <text x="870" y="100" fill="rgba(239,68,68,.65)" fontSize="11" fontWeight="800">ZONE A</text>
            <path d="M710 285 L770 320 L900 440 L840 460 L710 390Z" fill="rgba(34,180,99,.08)" stroke="rgba(34,180,99,.28)" strokeWidth="1.5" strokeDasharray="6 4" />
            <text x="800" y="435" fill="rgba(34,180,99,.5)" fontSize="11" fontWeight="800">ZONE B</text>
            <path d="M490 115 L520 105 L430 300 L300 440 L210 470 L220 380Z" fill="rgba(34,180,99,.08)" stroke="rgba(34,180,99,.28)" strokeWidth="1.5" strokeDasharray="6 4" />
            <text x="280" y="440" fill="rgba(34,180,99,.5)" fontSize="11" fontWeight="800">ZONE C</text>
            <path d="M620 195 L660 190 L620 310 L580 320 L570 280Z" fill="rgba(240,161,27,.10)" stroke="rgba(240,161,27,.30)" strokeWidth="1.5" strokeDasharray="6 4" />
            <text x="580" y="315" fill="rgba(240,161,27,.55)" fontSize="10" fontWeight="800">ZONE D</text>
          </g>
        )}

        {/* Pipeline network — drawn from the live topology */}
        <g strokeLinecap="round">
          {pipes.map((pipe) => (
            <g key={pipe.key}>
              <path
                d={pipe.d}
                stroke={pipe.dead ? '#4A1A1A' : '#0E3B52'}
                strokeWidth={pipe.trunk ? 9 : 7}
              />
              {showFlow && !pipe.dead && (
                <path
                  className="flow-dash"
                  d={pipe.d}
                  stroke="url(#pipeG)"
                  strokeWidth={pipe.trunk ? 4.5 : 3.4}
                />
              )}
            </g>
          ))}
        </g>

        {/* Asset nodes */}
        <g>
          {assets.map((asset) => {
            const col = STATUS_COLORS[asset.status] || '#8296A8';
            const hasPulse = STATUS_PULSE[asset.status];
            const isCritical = asset.status === 'critical';
            const isOffline = asset.status === 'offline';
            const r = asset.type === 'valve' ? 18 : asset.type === 'oht' ? 17 : asset.type === 'pump' ? 16 : asset.type === 'source' ? 14 : asset.type === 'junction' ? 9 : 10;

            return (
              <g
                key={asset.id}
                transform={`translate(${asset.x},${asset.y})`}
                style={{ cursor: 'pointer' }}
                onClick={() => onSelect?.(asset)}
                onMouseEnter={(e) => {
                  const rect = wrapRef.current?.getBoundingClientRect();
                  if (rect) {
                    setTooltip({
                      x: e.clientX - rect.left + 14,
                      y: e.clientY - rect.top - 12,
                      asset,
                    });
                  }
                }}
                onMouseMove={(e) => {
                  const rect = wrapRef.current?.getBoundingClientRect();
                  if (rect) {
                    setTooltip(prev => prev ? {
                      ...prev,
                      x: Math.min(e.clientX - rect.left + 14, rect.width - 180),
                      y: Math.min(e.clientY - rect.top - 12, rect.height - 90),
                    } : null);
                  }
                }}
                onMouseLeave={() => setTooltip(null)}
              >
                {hasPulse && <circle className="node-pulse" r="7" fill={col} opacity=".5" />}
                <circle
                  r={r}
                  fill={isCritical ? '#2C0F0F' : isOffline ? '#1E2A33' : '#0C2C4C'}
                  stroke={col}
                  strokeWidth={isCritical ? 3 : 2.5}
                  strokeDasharray={isOffline ? '3 3' : undefined}
                  filter={isCritical ? 'url(#glow)' : undefined}
                />
                {r > 12 && (
                  <svg x={-r * 0.55} y={-r * 0.55} width={r * 1.1} height={r * 1.1} style={{ color: isCritical ? '#FFB4B4' : asset.status === 'warn' ? '#FBD48A' : '#9BE9C0' }}>
                    <use href={
                      asset.type === 'source' ? '#i-drop' :
                      asset.type === 'pump' ? '#i-pump' :
                      asset.type === 'oht' ? '#i-tank' :
                      asset.type === 'valve' ? '#i-valve' :
                      '#i-asset'
                    } />
                  </svg>
                )}
                {showLabels && (
                  <>
                    <text y={-r - 8} textAnchor="middle" fill={isCritical ? '#FFD9D9' : '#DCEBF5'} fontSize={isCritical ? 12.5 : 12} fontWeight={isCritical ? 800 : 700}>
                      {asset.id}
                    </text>
                    {asset.detail && r > 12 && (
                      <text y={r + 14} textAnchor="middle" fill={isCritical ? '#F1A8A8' : isOffline ? '#8FA3B4' : '#9FBACC'} fontSize="10.5" fontWeight={isCritical ? 600 : 400}>
                        {/* Live sensor readout, truncated to fit the node */}
                        {asset.detail.length > 34 ? `${asset.detail.slice(0, 33)}…` : asset.detail}
                      </text>
                    )}
                  </>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {/* Map badge */}
      <div className="map-badge">
        <div style={{ fontSize: 10, letterSpacing: '.12em', textTransform: 'uppercase' as const, color: '#7FA6C2', fontWeight: 700 }}>
          {serviceArea ? `${serviceArea.name} Distribution Network` : 'Vitpur Distribution Network'}
          {!live && <span style={{ color: '#F0A11B' }}> · demo data</span>}
        </div>
        <div className="row gap12" style={{ marginTop: 4 }}>
          <span className="mono" style={{ fontSize: 11.5 }}>
            {serviceArea?.latitude != null && serviceArea?.longitude != null
              ? `${serviceArea.latitude.toFixed(3)}° N, ${serviceArea.longitude.toFixed(3)}° E`
              : '—'}
          </span>
          <span className="mono" style={{ fontSize: 11.5, color: '#7FA6C2' }}>
            {assets.length} assets · {criticalCount} critical
          </span>
        </div>
      </div>

      {/* Map controls */}
      <div className="map-ctrl">
        <button className={`mc ${showZones ? 'on' : ''}`} title="Toggle zones" onClick={() => setShowZones(v => !v)}>Z</button>
        <button className={`mc ${showFlow ? 'on' : ''}`} title="Toggle flow" onClick={() => setShowFlow(v => !v)}>≈</button>
        <button className={`mc ${showLabels ? 'on' : ''}`} title="Toggle labels" onClick={() => setShowLabels(v => !v)}>T</button>
        <button className="mc" title="Zoom in" onClick={() => setZoom(z => Math.min(z * 1.25, 2.6))}>+</button>
        <button className="mc" title="Zoom out" onClick={() => setZoom(z => Math.max(z / 1.25, 1))}>−</button>
      </div>

      {/* Map legend */}
      <div className="map-legend">
        <span className="lg"><i style={{ background: '#22B463' }} />Normal</span>
        <span className="lg"><i style={{ background: '#F0A11B' }} />Warning</span>
        <span className="lg"><i style={{ background: '#EF4444' }} />Critical</span>
        <span className="lg"><i style={{ background: '#3FC6E8' }} />Restored</span>
        <span className="lg"><i style={{ background: '#8296A8' }} />Sensor offline</span>
        <span className="spacer" />
        <span className="lg" style={{ color: '#8FA3B4' }}>Click any node for asset detail</span>
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div className="maptip" style={{
          opacity: 1,
          left: tooltip.x,
          top: tooltip.y,
        }}>
          <div style={{ fontWeight: 700, fontSize: 12 }}>{tooltip.asset.name}</div>
          <div className="mono" style={{ fontSize: 10.5, color: '#8FB2CC', margin: '2px 0 4px' }}>{tooltip.asset.id}</div>
          <div style={{
            fontSize: 11,
            color: ({ normal: '#7FE3AC', warn: '#FBD48A', critical: '#FFAFAF', offline: '#B6C6D2', maintenance: '#B6C6D2' } as Record<string, string>)[tooltip.asset.status] || '#fff',
          }}>
            {tooltip.asset.detail}
          </div>
        </div>
      )}
    </div>
  );
}
