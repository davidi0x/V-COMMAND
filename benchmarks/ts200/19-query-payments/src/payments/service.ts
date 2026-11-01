import { parseQuery } from "./query.ts";

export function paymentsSearch(url: string): string {
  return parseQuery(url.split("?")[1] ?? "").q ?? "";
}
