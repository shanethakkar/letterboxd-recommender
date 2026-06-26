"use client";

import { Layer, OrthographicView } from "@deck.gl/core";
import { IconLayer, ScatterplotLayer } from "@deck.gl/layers";
import { DeckGL } from "@deck.gl/react";
import { useEffect, useMemo, useState } from "react";

import { thumb } from "@/lib/poster";
import type { CascadeNode } from "@/lib/stream";
import type { GraphPayload } from "@/lib/types";

const BEAM: [number, number, number] = [232, 195, 106];
const easeOut = (t: number) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));
const CRYSTALLIZE_MS = 1500;

interface Sprite {
  id: string;
  poster_url: string | null;
  rec: boolean;
}

// A stable scattered cloud position for a node id, filling ~90% of the viewport.
function cloudPos(id: string, vw: number, vh: number): [number, number] {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) h = (h ^ id.charCodeAt(i)) * 16777619;
  const a = ((h >>> 0) % 1000) / 1000;
  const b = ((h >>> 10) % 1000) / 1000;
  const r = Math.sqrt(a); // disc-ish, denser toward centre
  const theta = b * Math.PI * 2;
  return [Math.cos(theta) * r * vw * 0.46, Math.sin(theta) * r * vh * 0.46];
}

// Normalize the final UMAP coords into the same centred pixel space as the cloud (view is zoom 0,
// so 1 world unit = 1 px), fitting ~74% of the viewport with aspect preserved.
function fitFinal(
  nodes: GraphPayload["nodes"],
  vw: number,
  vh: number,
): Map<string, [number, number]> {
  const xs = nodes.map((n) => n.x);
  const ys = nodes.map((n) => n.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const scale = Math.min((vw * 0.74) / Math.max(maxX - minX, 1e-6), (vh * 0.74) / Math.max(maxY - minY, 1e-6));
  const m = new Map<string, [number, number]>();
  for (const n of nodes) m.set(n.id, [(n.x - cx) * scale, (n.y - cy) * scale]);
  return m;
}

export default function RevealStream({
  cloud,
  payload,
  reducedMotion = false,
}: {
  cloud: CascadeNode[];
  payload: GraphPayload | null;
  reducedMotion?: boolean;
}) {
  const dims = useMemo(
    () => ({
      w: typeof window === "undefined" ? 1440 : window.innerWidth,
      h: typeof window === "undefined" ? 900 : window.innerHeight,
    }),
    [],
  );

  const [settled, setSettled] = useState(false);

  // Render the full sprite set (cloud + recs) at cloud positions for a frame, then flip to settled
  // so deck interpolates getPosition cloud → final (recs join the seeds and crystallize).
  useEffect(() => {
    if (!payload) return;
    // setState inside the rAF callback (not synchronously in the effect body). Reduced motion
    // settles next frame; otherwise the cloud paints one frame, then deck interpolates to final.
    const id = reducedMotion
      ? requestAnimationFrame(() => setSettled(true))
      : requestAnimationFrame(() => requestAnimationFrame(() => setSettled(true)));
    return () => cancelAnimationFrame(id);
  }, [payload, reducedMotion]);

  const finalPos = useMemo(
    () => (payload ? fitFinal(payload.nodes, dims.w, dims.h) : null),
    [payload, dims],
  );

  // Sprites: the cascaded watched films, plus (once the result lands) the recommendations.
  const sprites = useMemo<Sprite[]>(() => {
    const seen = new Set<string>();
    const out: Sprite[] = [];
    for (const n of cloud) {
      if (seen.has(n.id)) continue;
      seen.add(n.id);
      out.push({ id: n.id, poster_url: n.poster_url, rec: false });
    }
    if (payload) {
      for (const n of payload.nodes) {
        if (n.type !== "recommended" || seen.has(n.id)) continue;
        seen.add(n.id);
        out.push({ id: n.id, poster_url: n.poster_url, rec: true });
      }
    }
    return out;
  }, [cloud, payload]);

  const withPosters = useMemo(() => sprites.filter((s) => s.poster_url), [sprites]);
  const recSprites = useMemo(() => sprites.filter((s) => s.rec), [sprites]);

  const pos = (s: Sprite): [number, number] =>
    settled && finalPos ? (finalPos.get(s.id) ?? cloudPos(s.id, dims.w, dims.h)) : cloudPos(s.id, dims.w, dims.h);

  // After settling, films that didn't make the map fade out; recs + seeds stay lit.
  const alpha = (s: Sprite): number => {
    if (!settled || !finalPos) return 230;
    return finalPos.has(s.id) ? 255 : 0;
  };

  const layers: Layer[] = [
    new IconLayer<Sprite>({
      id: "reveal-posters",
      data: withPosters,
      getIcon: (s) => ({ url: thumb(s.poster_url as string, "w92"), width: 92, height: 138, id: s.id, mask: false }),
      getPosition: pos,
      getSize: (s) => (settled && s.rec ? 46 : 36),
      sizeUnits: "pixels",
      getColor: (s) => [255, 255, 255, alpha(s)],
      transitions: {
        getPosition: { duration: settled ? CRYSTALLIZE_MS : 0, easing: easeOut },
        getColor: 600,
        getSize: 400,
      },
      updateTriggers: { getPosition: [settled, finalPos], getColor: [settled], getSize: [settled] },
      pickable: false,
    }),
  ];

  if (settled && finalPos) {
    layers.unshift(
      new ScatterplotLayer<Sprite>({
        id: "reveal-rec-rings",
        data: recSprites,
        getPosition: pos,
        getRadius: 30,
        radiusUnits: "pixels",
        filled: false,
        stroked: true,
        getLineColor: [...BEAM, 170],
        getLineWidth: 1.5,
        lineWidthUnits: "pixels",
        transitions: { getPosition: { duration: CRYSTALLIZE_MS, easing: easeOut }, getLineColor: 500 },
        updateTriggers: { getPosition: [settled, finalPos] },
        pickable: false,
      }),
    );
  }

  return (
    <DeckGL
      views={new OrthographicView({ id: "reveal", flipY: true })}
      viewState={{ target: [0, 0, 0], zoom: 0 }}
      controller={false}
      layers={layers}
      style={{ position: "absolute", width: "100%", height: "100%" }}
    />
  );
}
