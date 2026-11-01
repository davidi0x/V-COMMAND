export function chunk<T>(xs: T[], n: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i + n <= xs.length; i += n) out.push(xs.slice(i, i + n));
  return out;
}
