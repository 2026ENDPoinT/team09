import { departments } from "./seoultech-departments.js";
import type { Dorm } from "./lms.js";

export const residences = [
  ["seonglim", "성림학사"], ["surim", "수림학사"], ["kb", "KB학사"],
  ["nuri", "누리학사"], ["buram", "불암학사"], ["none", "기숙사 거주 아님"],
] as const;

export type StudentPreferences = {
  residence: typeof residences[number][0];
  departmentId: string;
};

// The housing office publishes menus by dining hall, which some residences share.
export const residenceDiningHall: Record<StudentPreferences["residence"], Dorm | undefined> = {
  seonglim: "seonglim",
  surim: "surim",
  kb: "kb",
  nuri: "seonglim",
  buram: "kb",
  none: undefined,
};

export function parseStudentPreferences(input: unknown): StudentPreferences | null {
  if (!input || typeof input !== "object") return null;
  const { residence, departmentId } = input as Partial<StudentPreferences>;
  if (!residence || !residences.some(([id]) => id === residence) ||
      !departmentId || !departments.some(({ id }) => id === departmentId)) return null;
  return { residence, departmentId };
}
