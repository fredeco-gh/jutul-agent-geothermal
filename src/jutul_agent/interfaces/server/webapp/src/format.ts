// Small display formatters shared across the UI.

/** A short, human relative time ("just now", "5m ago", "3d ago", else a date). */
export function timeAgo(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (Number.isNaN(seconds)) return "";
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 7 * 86400) return `${Math.floor(seconds / 86400)}d ago`;
  return new Date(iso).toLocaleDateString();
}

/** Token counts as compact figures: 1500 -> "1.5k", 24000 -> "24k". */
export function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
  return String(n);
}

/** Round long floats to a few significant digits so a metrics grid stays readable. */
export function fmtNum(v: unknown): string {
  return typeof v === "number" && Number.isFinite(v)
    ? String(Number(v.toPrecision(4)))
    : String(v);
}
