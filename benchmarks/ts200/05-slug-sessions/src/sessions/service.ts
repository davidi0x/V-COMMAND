import { slug } from "./text.ts";

export function sessionsUrl(title: string, id: number): string {
  return `/sessions/${id}-${slug(title)}`;
}
