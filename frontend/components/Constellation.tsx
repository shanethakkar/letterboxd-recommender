"use client";

import { Layer, LinearInterpolator, OrthographicView } from "@deck.gl/core";
import { IconLayer, LineLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { DeckGL } from "@deck.gl/react";
import { useEffect, useMemo, useState } from "react";

import type { Cluster, GraphNode, GraphPayload, Recommendation } from "@/lib/types";

const LEADER: [number, number, number] = [242, 240, 234];
const BEAM: [number, number, number] = [232, 195, 106];

// Strong ease-out (settle into place) — built-in easings are too weak (emil-design-eng).
const easeOut = (t: number) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));
const CRYSTALLIZE_MS = 1400;

interface ViewState {
  target: [number, number, number];
  zoom: number;
  minZoom: number;
  maxZoom: number;
  transitionDuration?: number;
  transitionInterpolator?: LinearInterpolator;
  transitionEasing?: (t: number) => number;
}

interface Props {
  payload: GraphPayload;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  focusId: string | null;
  visible: (n: GraphNode) => boolean;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  );
}

function initialView(nodes: GraphNode[]): ViewState {
  const xs = nodes.map((n) => n.x);
  const ys = nodes.map((n) => n.y);
  const [minX, maxX] = [Math.min(...xs), Math.max(...xs)];
  const [minY, maxY] = [Math.min(...ys), Math.max(...ys)];
  const span = Math.max(maxX - minX, maxY - minY, 1);
  return {
    target: [(minX + maxX) / 2, (minY + maxY) / 2, 0],
    zoom: Math.log2(620 / span),
    minZoom: -4,
    maxZoom: 11,
  };
}

/** Poster height in px — recommendations are the big stars; seed films are small context. */
function sizeOf(n: GraphNode): number {
  if (n.type === "recommended") return 30 + (n.score ?? 0) * 32; // ~30–60
  return 15 + (n.rating ?? 3) * 4; // ~21–35
}

function thumb(url: string): string {
  return url.replace("/w185/", "/w154/");
}

export default function Constellation({ payload, selectedId, onSelect, focusId, visible }: Props) {
  const reduced = useMemo(() => prefersReducedMotion(), []);
  const [hovered, setHovered] = useState<string | null>(null);
  const [settled, setSettled] = useState(reduced); // reduced-motion → no fly-in
  const [view, setView] = useState<ViewState>(() => initialView(payload.nodes));

  // Crystallize: render the scattered cloud once, then flip to the real layout (deck
  // interpolates getPosition). Double rAF guarantees the cloud frame paints first.
  useEffect(() => {
    if (reduced) return;
    const id = requestAnimationFrame(() => requestAnimationFrame(() => setSettled(true)));
    return () => cancelAnimationFrame(id);
  }, [reduced]);

  const nodeById = useMemo(() => {
    const m = new Map<string, GraphNode>();
    for (const n of payload.nodes) m.set(n.id, n);
    return m;
  }, [payload.nodes]);

  // A loose cloud start position for each node (deterministic; scattered around centre).
  const cloud = useMemo(() => {
    const v = initialView(payload.nodes);
    const [cx, cy] = v.target;
    const spread = Math.pow(2, -v.zoom) * 520;
    const m = new Map<string, [number, number]>();
    payload.nodes.forEach((n, i) => {
      const a = ((i * 2654435761) % 1000) / 1000;
      const r = (((i * 40503) % 1000) / 1000) ** 0.5;
      m.set(n.id, [cx + Math.cos(a * 6.283) * r * spread, cy + Math.sin(a * 6.283) * r * spread]);
    });
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

  // Fly the camera to a node when the rail selects one.
  useEffect(() => {
    if (!focusId) return;
    const n = nodeById.get(focusId);
    if (!n) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- imperative camera fly-to on selection
    setView((v) => ({
      ...v,
      target: [n.x, n.y, 0],
      zoom: Math.min(v.maxZoom, Math.max(v.zoom, 3)),
      transitionDuration: reduced ? 0 : 650,
      transitionInterpolator: new LinearInterpolator(["target", "zoom"]),
      transitionEasing: (t) => 1 - Math.pow(1 - t, 3),
    }));
  }, [focusId, nodeById, reduced]);

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
  const pos = (n: GraphNode): [number, number] => (settled ? [n.x, n.y] : cloud.get(n.id)!);
  const posId = (id: string): [number, number] => {
    const n = nodeById.get(id);
    return n ? pos(n) : [0, 0];
  };

  const recs = nodes.filter((n) => n.type === "recommended");
  const withPosters = nodes.filter((n) => n.poster_url);
  const selectedNode = selectedId ? nodeById.get(selectedId) ?? null : null;

  // Size glyphs in WORLD units (so they scale with zoom — pixel units never would), scaled so
  // the default-zoom look is unchanged, then clamped to sane pixel bounds. Hovering enlarges
  // a poster for an instant read without clicking.
  const span = useMemo(() => {
    const xs = payload.nodes.map((n) => n.x);
    const ys = payload.nodes.map((n) => n.y);
    return Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 1);
  }, [payload.nodes]);
  const worldScale = span / 620; // matches the fit zoom in initialView
  const bump = (n: GraphNode) => (n.id === hovered ? 1.7 : 1);

  const posTransition = { getPosition: { duration: reduced ? 0 : CRYSTALLIZE_MS, easing: easeOut } };

  const layers: Layer[] = [
    // faint backing dot (also catches posterless nodes)
    new ScatterplotLayer<GraphNode>({
      id: "dots",
      data: nodes,
      getPosition: pos,
      getRadius: (n) => sizeOf(n) * 0.5,
      radiusUnits: "common",
      radiusScale: worldScale,
      radiusMinPixels: 2,
      radiusMaxPixels: 150,
      getFillColor: (n) => [...LEADER, isLit(n.id) ? 45 : 12],
      transitions: posTransition,
      updateTriggers: { getPosition: [settled], getFillColor: [active] },
      pickable: false,
    }),
    // persistent amber ring marking every recommendation (the stars)
    new ScatterplotLayer<GraphNode>({
      id: "rec-rings",
      data: recs,
      getPosition: pos,
      getRadius: (n) => sizeOf(n) * 0.62 * bump(n),
      radiusUnits: "common",
      radiusScale: worldScale,
      radiusMinPixels: 9,
      radiusMaxPixels: 210,
      filled: false,
      stroked: true,
      getLineColor: (n) => [...BEAM, n.id === selectedId ? 235 : isLit(n.id) ? 150 : 60],
      getLineWidth: (n) => (n.id === selectedId ? 2 : 1),
      lineWidthUnits: "pixels",
      transitions: { ...posTransition, getRadius: 160 },
      updateTriggers: {
        getPosition: [settled],
        getRadius: [hovered],
        getLineColor: [active, selectedId],
      },
      pickable: false,
    }),
    new IconLayer<GraphNode>({
      id: "posters",
      data: withPosters,
      getIcon: (n) => ({ url: thumb(n.poster_url as string), width: 154, height: 231, id: n.id, mask: false }),
      getPosition: pos,
      getSize: (n) => sizeOf(n) * bump(n),
      sizeUnits: "common",
      sizeScale: worldScale,
      sizeMinPixels: 12,
      sizeMaxPixels: 340,
      getColor: (n) => [255, 255, 255, isLit(n.id) ? 255 : n.type === "recommended" ? 90 : 55],
      transitions: { ...posTransition, getSize: 160 },
      updateTriggers: { getPosition: [settled], getSize: [hovered], getColor: [active] },
      pickable: true,
      onHover: (info) => setHovered((info.object as GraphNode | null)?.id ?? null),
      onClick: (info) => onSelect((info.object as GraphNode | null)?.id ?? null),
    }),
  ];

  // Edges, "why" edges, labels, and the selected halo come in only once settled — so the
  // crystallization is clean posters flying home, not a tangle of lines.
  if (settled) {
    const simEdges = payload.edges.filter(
      (e) => visibleIds.has(e.source) && visibleIds.has(e.target),
    );
    const rec = active ? recById.get(active) : null;
    const becauseEdges = rec
      ? rec.because.filter((b) => visibleIds.has(b.id)).map((b) => ({ from: rec.id, to: b.id, w: b.contribution }))
      : [];
    const labelled = payload.clusters.filter((c) => c.label);

    layers.push(
      new TextLayer<Cluster>({
        id: "cluster-labels",
        data: labelled,
        getPosition: (c) => c.centroid,
        getText: (c) => (c.label ?? "").toUpperCase(),
        getSize: 12,
        sizeUnits: "pixels",
        getColor: [...LEADER, 55],
        fontFamily: "monospace",
        getTextAnchor: "middle",
        characterSet: "auto",
        pickable: false,
      }),
      new LineLayer<(typeof simEdges)[number]>({
        id: "edges",
        data: simEdges,
        getSourcePosition: (e) => posId(e.source),
        getTargetPosition: (e) => posId(e.target),
        getColor: (e) => [...LEADER, isLit(e.source) && isLit(e.target) ? 24 + e.weight * 110 : 7],
        getWidth: (e) => 0.5 + e.weight * 1.3,
        widthUnits: "pixels",
        transitions: { getColor: 200 },
        updateTriggers: { getColor: [active] },
        pickable: false,
      }),
      new LineLayer<(typeof becauseEdges)[number]>({
        id: "because",
        data: becauseEdges,
        getSourcePosition: (e) => posId(e.from),
        getTargetPosition: (e) => posId(e.to),
        getColor: [...BEAM, 225],
        getWidth: (e) => 1 + e.w * 6,
        widthUnits: "pixels",
        pickable: false,
      }),
    );
    if (selectedNode) {
      layers.push(
        new ScatterplotLayer<GraphNode>({
          id: "halo",
          data: [selectedNode],
          getPosition: (n) => [n.x, n.y],
          getRadius: sizeOf(selectedNode) * 0.98 * bump(selectedNode),
          radiusUnits: "common",
          radiusScale: worldScale,
          radiusMinPixels: 14,
          radiusMaxPixels: 360,
          getFillColor: [...BEAM, 45],
          stroked: true,
          getLineColor: [...BEAM, 230],
          getLineWidth: 1.5,
          lineWidthUnits: "pixels",
          pickable: false,
        }),
      );
    }
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
