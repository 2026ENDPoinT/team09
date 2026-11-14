export function shiftTimetableDate(iso: string, days: number) {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function timetableWeekStart(iso: string) {
  const weekday = new Date(`${iso}T00:00:00Z`).getUTCDay();
  return shiftTimetableDate(iso, -((weekday + 6) % 7));
}
