export function slug(s: string): string {
  return (s.match(/[A-Za-z0-9]+/g) ?? []).join("-");
}
