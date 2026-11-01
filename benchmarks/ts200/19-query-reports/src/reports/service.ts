import { parseQuery } from "./query.ts";

export function reportsSearch(url: string): string {
  return parseQuery(url.split("?")[1] ?? "").q ?? "";
}
