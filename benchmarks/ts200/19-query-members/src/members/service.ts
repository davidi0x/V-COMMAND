import { parseQuery } from "./query.ts";

export function membersSearch(url: string): string {
  return parseQuery(url.split("?")[1] ?? "").q ?? "";
}
