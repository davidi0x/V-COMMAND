import { parseQuery } from "./query.ts";

export function ticketsSearch(url: string): string {
  return parseQuery(url.split("?")[1] ?? "").q ?? "";
}
