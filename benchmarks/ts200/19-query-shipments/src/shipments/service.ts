import { parseQuery } from "./query.ts";

export function shipmentsSearch(url: string): string {
  return parseQuery(url.split("?")[1] ?? "").q ?? "";
}
