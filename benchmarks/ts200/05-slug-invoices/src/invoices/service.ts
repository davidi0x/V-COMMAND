import { slug } from "./text.ts";

export function invoicesUrl(title: string, id: number): string {
  return `/invoices/${id}-${slug(title)}`;
}
