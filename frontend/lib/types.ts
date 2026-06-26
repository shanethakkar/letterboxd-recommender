// Mirrors the backend graph payload contract (SPEC §5). Keep in lockstep with
// backend/models.py (GraphPayload).

export type NodeType = "watched" | "recommended";

export interface GraphNode {
  id: string; // "tmdb:{id}"
  type: NodeType;
  title: string;
  year: number | null;
  poster_url: string | null;
  x: number;
  y: number;
  cluster: number;
  rating: number | null; // present for watched
  score: number | null; // present for recommended
  genres: string[];
  director: string | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  weight: number;
  shared: string; // "director" | "cast" | "keyword" | "genre"
}

export interface Because {
  id: string;
  title: string;
  contribution: number;
}

export interface Recommendation {
  id: string;
  tmdb_id: number;
  title: string;
  year: number | null;
  score: number;
  because: Because[];
  shared_traits: string[];
}

export interface Cluster {
  id: number;
  label: string | null;
  centroid: [number, number];
}

export interface Stats {
  rated: number;
  avg_rating: number;
  clusters: number;
}

export interface GraphPayload {
  username: string;
  generated_at: string;
  stats: Stats;
  nodes: GraphNode[];
  edges: GraphEdge[];
  recommendations: Recommendation[];
  clusters: Cluster[];
}
