import { slug } from "./text.ts";

export function reportsUrl(title: string, id: number): string {
  return `/reports/${id}-${slug(title)}`;
}
