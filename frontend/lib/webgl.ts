/** True if the browser can create a WebGL2 context (deck.gl's requirement). */
export function hasWebGL(): boolean {
  if (typeof document === "undefined") return true; // assume yes during SSR; re-checked on mount
  try {
    const canvas = document.createElement("canvas");
    return !!canvas.getContext("webgl2");
  } catch {
    return false;
  }
}
