import { slug } from "./text.ts";

export function paymentsUrl(title: string, id: number): string {
  return `/payments/${id}-${slug(title)}`;
}
