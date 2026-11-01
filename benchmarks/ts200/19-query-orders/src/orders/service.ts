import { parseQuery } from "./query.ts";

export function ordersSearch(url: string): string {
  return parseQuery(url.split("?")[1] ?? "").q ?? "";
}
