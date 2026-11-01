import { parseQuery } from "./query.ts";

export function productsSearch(url: string): string {
  return parseQuery(url.split("?")[1] ?? "").q ?? "";
}
