import { slug } from "./text.ts";

export function ticketsUrl(title: string, id: number): string {
  return `/tickets/${id}-${slug(title)}`;
}
