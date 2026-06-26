"use client";

/* The constellation, receded: a static field of heavily-blurred posters drifting
   slowly behind the glass, with projector beams and a scrim that keeps glass text
   crisp. Static <img>s by design — never a live WebGL canvas behind backdrop-filter
   (fixing-motion-performance). */

// Fixed bokeh slots (top/left/size/opacity), tuned to read as an out-of-focus
// constellation; payload posters are zipped onto them in order.
const SLOTS: { top: string; left: string; size: number; opacity: number }[] = [
  { top: "-6%", left: "4%", size: 280, opacity: 0.5 },
  { top: "12%", left: "22%", size: 200, opacity: 0.35 },
  { top: "-4%", left: "44%", size: 240, opacity: 0.42 },
  { top: "6%", left: "70%", size: 300, opacity: 0.5 },
  { top: "20%", left: "88%", size: 220, opacity: 0.4 },
  { top: "38%", left: "-3%", size: 260, opacity: 0.45 },
  { top: "44%", left: "16%", size: 180, opacity: 0.3 },
  { top: "52%", left: "82%", size: 280, opacity: 0.46 },
  { top: "66%", left: "30%", size: 220, opacity: 0.36 },
  { top: "74%", left: "6%", size: 260, opacity: 0.42 },
  { top: "70%", left: "60%", size: 240, opacity: 0.4 },
  { top: "84%", left: "84%", size: 300, opacity: 0.46 },
  { top: "30%", left: "48%", size: 200, opacity: 0.3 },
  { top: "88%", left: "44%", size: 220, opacity: 0.36 },
];

export default function GlassBackground({ posters }: { posters: string[] }) {
  // Zip posters onto the fixed slots (cycle if fewer posters than slots).
  const field = posters.length
    ? SLOTS.map((slot, i) => ({ ...slot, url: posters[i % posters.length] }))
    : [];

  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      <div className="bokeh absolute inset-0">
        {field.map((b, i) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={i}
            src={b.url}
            alt=""
            style={{
              top: b.top,
              left: b.left,
              width: b.size,
              height: b.size * 1.5,
              opacity: b.opacity,
            }}
            className="absolute rounded-[2rem] object-cover"
          />
        ))}
      </div>

      {/* projector beams — the one warm accent, raking across the field */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(60% 50% at 18% 8%, rgba(232,195,106,0.10), transparent 60%)," +
            "radial-gradient(50% 60% at 88% 78%, rgba(232,195,106,0.07), transparent 60%)",
        }}
      />
      {/* darken the field just enough that glass text stays crisp, while the
          constellation still reads as soft light behind it */}
      <div className="absolute inset-0 bg-void/30" />
      <div
        className="absolute inset-0"
        style={{ background: "radial-gradient(125% 95% at 50% 28%, transparent 58%, rgba(8,9,11,0.78))" }}
      />
    </div>
  );
}
