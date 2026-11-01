import { titleCase } from "./case.ts";

export function reportsHeading(name: string): string {
  return titleCase(name);
}
