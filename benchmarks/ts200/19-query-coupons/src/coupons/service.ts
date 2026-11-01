import { parseQuery } from "./query.ts";

export function couponsSearch(url: string): string {
  return parseQuery(url.split("?")[1] ?? "").q ?? "";
}
