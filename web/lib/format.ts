export function formatAsOfDate(yyyymmdd: string | null): string {
  if (!yyyymmdd || yyyymmdd.length !== 8) return yyyymmdd ?? "-";
  const year = yyyymmdd.slice(0, 4);
  const month = yyyymmdd.slice(4, 6);
  const day = yyyymmdd.slice(6, 8);
  return `${year}년 ${month}월 ${day}일`;
}
