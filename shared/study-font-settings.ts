export type StudyFontSettings = {
  summaryFont: number;
  tutorFont: number;
};

export const defaultStudyFonts: StudyFontSettings = { summaryFont: 20, tutorFont: 18 };
export const studyFontMin = 6;
export const studyFontMax = 64;
