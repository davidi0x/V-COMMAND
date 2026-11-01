import { parseQuery } from "./query.ts";

export function sessionsSearch(url: string): string {
  return parseQuery(url.split("?")[1] ?? "").q ?? "";
}
