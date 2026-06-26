// TMDB poster URLs come in at w185; swap to a smaller render size where the sprite is small.
// Smaller sizes also keep the deck.gl icon atlas under the SwiftShader/WebGL texture limit when
// hundreds of posters render at once (the reveal cascade).
export function thumb(url: string, size: "w92" | "w154" = "w154"): string {
  return url.replace("/w185/", `/${size}/`);
}
