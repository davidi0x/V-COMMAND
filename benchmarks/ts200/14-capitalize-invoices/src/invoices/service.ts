import { titleCase } from "./case.ts";

export function invoicesHeading(name: string): string {
  return titleCase(name);
}
