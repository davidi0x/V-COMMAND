import { slug } from "./text.ts";

export function couponsUrl(title: string, id: number): string {
  return `/coupons/${id}-${slug(title)}`;
}
