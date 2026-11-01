import { titleCase } from "./case.ts";

export function productsHeading(name: string): string {
  return titleCase(name);
}
