export function slug(s: string): string {
  return (s.toLowerCase().match(/[a-z0-9]+/g) ?? []).join("-");
}
