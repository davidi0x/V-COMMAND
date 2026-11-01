import { titleCase } from "./case.ts";

export function ticketsHeading(name: string): string {
  return titleCase(name);
}
