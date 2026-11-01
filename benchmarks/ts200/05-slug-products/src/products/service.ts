import { slug } from "./text.ts";

export function productsUrl(title: string, id: number): string {
  return `/products/${id}-${slug(title)}`;
}
