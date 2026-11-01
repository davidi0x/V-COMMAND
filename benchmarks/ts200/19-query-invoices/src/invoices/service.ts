import { parseQuery } from "./query.ts";

export function invoicesSearch(url: string): string {
  return parseQuery(url.split("?")[1] ?? "").q ?? "";
}
