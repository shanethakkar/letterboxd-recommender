"use client";

import { Layer, OrthographicView } from "@deck.gl/core";
import { IconLayer, LineLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { DeckGL } from "@deck.gl/react";
import { useMemo, useState } from "react";

import type { Cluster, GraphNode, GraphPayload, Recommendation } from "@/lib/types";

const LEADER: [number, number, number] = [242, 240, 234];
const BEAM: [number, number, number] = [232, 195, 106];

interface ViewState {
  target: [number, number, number];
  zoom: number;
  minZoom: number;
  maxZoom: number;
}

interface Props {
  payload: GraphPayload;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  visible: (n: GraphNode) => boolean;
}

function initialView(nodes: GraphNode[]): ViewState {
  const xs = nodes.map((n) => n.x);
  const ys = nodes.map((n) => n.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const span = Math.max(maxX - minX, maxY - minY, 1);
  return {
    target: [(minX + maxX) / 2, (minY + maxY) / 2, 0],
    zoom: Math.log2(720 / span), // fit the data into ~720px on first paint
    minZoom: -4,
    maxZoom: 8,
  };
}

/** Small thumbnail for the icon atlas — posters draw at ~30–50px, so w92 is plenty and
 * keeps the packed texture well under GPU limits (and far lighter to load). */
function thumb(url: string): string {
  return url.replace("/w185/", "/w92/");
}

/** Poster height in px — watched sized by rating, recommendations by score. */
function sizeOf(n: GraphNode): number {
  if (n.type === "watched") return 22 + (n.rating ?? 3) * 6; // 25–52
  return 20 + (n.score ?? 0) * 28; // ~20–48
}

export default function Constellation({ payload, selectedId, onSelect, visible }: Props) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [view, setView] = useState<ViewState>(() => initialView(payload.nodes));

  const nodeById = useMemo(() => {
    const m = new Map<string, GraphNode>();
    for (const n of payload.nodes) m.set(n.id, n);
    return m;
  }, [payload.nodes]);

  const recById = useMemo(() => {
    const m = new Map<string, Recommendation>();
    for (const r of payload.recommendations) m.set(r.id, r);
    return m;
  }, [payload.recommendations]);

  const neighbours = useMemo(() => {
    const m = new Map<string, Set<string>>();
    const add = (a: string, b: string) => {
      let s = m.get(a);
      if (!s) m.set(a, (s = new Set()));
      s.add(b);
    };
    for (const e of payload.edges) {
      add(e.source, e.target);
      add(e.target, e.source);
    }
    return m;
  }, [payload.edges]);

  const active = selectedId ?? hovered;
  const nodes = useMemo(() => payload.nodes.filter(visible), [payload.nodes, visible]);
  const visibleIds = useMemo(() => new Set(nodes.map((n) => n.id)), [nodes]);

  const lit = useMemo(() => {
    if (!active) return null;
    const s = new Set<string>([active]);
    for (const nb of neighbours.get(active) ?? []) s.add(nb);
    const rec = recById.get(active);
    if (rec) for (const b of rec.because) s.add(b.id);
    return s;
  }, [active, neighbours, recById]);

  const isLit = (id: string) => !lit || lit.has(id);

  const becauseEdges = useMemo(() => {
    const rec = active ? recById.get(active) : null;
    if (!rec) return [];
    return rec.because
      .filter((b) => nodeById.has(b.id) && visibleIds.has(b.id))
      .map((b) => ({ from: rec.id, to: b.id, contribution: b.contribution }));
  }, [active, recById, nodeById, visibleIds]);

  const simEdges = useMemo(
    () => payload.edges.filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target)),
    [payload.edges, visibleIds],
  );

  const pos = (id: string): [number, number] => {
    const n = nodeById.get(id);
    return n ? [n.x, n.y] : [0, 0];
  };

  const withPosters = nodes.filter((n) => n.poster_url);
  const labelled = payload.clusters.filter((c) => c.label);
  const selectedNode = selectedId ? nodeById.get(selectedId) ?? null : null;

  const layers: Layer[] = [
    new TextLayer<Cluster>({
      id: "cluster-labels",
      data: labelled,
      getPosition: (c) => c.centroid,
      getText: (c) => (c.label ?? "").toUpperCase(),
      getSize: 13,
      sizeUnits: "pixels",
      getColor: [...LEADER, 60],
      fontFamily: "monospace",
      getTextAnchor: "middle",
      characterSet: "auto",
      pickable: false,
    }),
    new LineLayer<(typeof simEdges)[number]>({
      id: "edges",
      data: simEdges,
      getSourcePosition: (e) => pos(e.source),
      getTargetPosition: (e) => pos(e.target),
      getColor: (e) => [
        ...LEADER,
        isLit(e.source) && isLit(e.target) ? 26 + e.weight * 120 : 8,
      ],
      getWidth: (e) => 0.5 + e.weight * 1.5,
      widthUnits: "pixels",
      updateTriggers: { getColor: [active] },
      pickable: false,
    }),
    new LineLayer<(typeof becauseEdges)[number]>({
      id: "because",
      data: becauseEdges,
      getSourcePosition: (e) => pos(e.from),
      getTargetPosition: (e) => pos(e.to),
      getColor: [...BEAM, 220],
      getWidth: (e) => 1 + e.contribution * 6,
      widthUnits: "pixels",
      pickable: false,
    }),
    new ScatterplotLayer<GraphNode>({
      id: "dots",
      data: nodes,
      getPosition: (n) => [n.x, n.y],
      getRadius: (n) => sizeOf(n) * 0.5,
      radiusUnits: "pixels",
      getFillColor: (n) => [...LEADER, isLit(n.id) ? 50 : 14],
      updateTriggers: { getFillColor: [active] },
      pickable: false,
    }),
    new IconLayer<GraphNode>({
      id: "posters",
      data: withPosters,
      getIcon: (n) => ({
        url: thumb(n.poster_url as string),
        width: 92,
        height: 138,
        id: n.id,
        mask: false,
      }),
      getPosition: (n) => [n.x, n.y],
      getSize: (n) => sizeOf(n),
      sizeUnits: "pixels",
      getColor: (n) => [255, 255, 255, isLit(n.id) ? 255 : 55],
      updateTriggers: { getColor: [active] },
      pickable: true,
      onHover: (info) => setHovered((info.object as GraphNode | null)?.id ?? null),
      onClick: (info) => onSelect((info.object as GraphNode | null)?.id ?? null),
    }),
  ];

  if (selectedNode) {
    layers.push(
      new ScatterplotLayer<GraphNode>({
        id: "halo",
        data: [selectedNode],
        getPosition: (n) => [n.x, n.y],
        getRadius: sizeOf(selectedNode) * 0.95,
        radiusUnits: "pixels",
        getFillColor: [...BEAM, 60],
        stroked: true,
        getLineColor: [...BEAM, 220],
        getLineWidth: 1.5,
        lineWidthUnits: "pixels",
        pickable: false,
      }),
    );
  }

  return (
    <DeckGL
      views={new OrthographicView({ id: "ortho", flipY: true })}
      viewState={view}
      controller
      onViewStateChange={(e) => setView(e.viewState as ViewState)}
      getCursor={({ isHovering }) => (isHovering ? "pointer" : "grab")}
      onClick={(info) => {
        if (!info.object) onSelect(null);
      }}
      layers={layers}
      style={{ position: "absolute", width: "100%", height: "100%" }}
    />
  );
}
