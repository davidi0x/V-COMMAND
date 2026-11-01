import { slug } from "./text.ts";

export function shipmentsUrl(title: string, id: number): string {
  return `/shipments/${id}-${slug(title)}`;
}
