export function parseQuery(q: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of q.replace(/^\?/, "").split("&")) {
    if (!part) continue;
    const [k, v = ""] = part.split("=");
    out[decodeURIComponent(k)] = decodeURIComponent(v.replace(/\+/g, " "));
  }
  return out;
}
