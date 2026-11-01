import { slug } from "./text.ts";

export function ordersUrl(title: string, id: number): string {
  return `/orders/${id}-${slug(title)}`;
}
