export function titleCase(s: string): string {
  return s.split(" ").map((w, i) =>
    i > 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w).join(" ");
}
