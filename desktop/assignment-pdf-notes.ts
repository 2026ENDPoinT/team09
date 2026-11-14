export type PdfNotes = {
  id: string;
  name: string;
  overview: string;
  coverage: "complete" | "partial";
  sections: { from: number; to: number; text: string; visuals: string }[];
};

export type PdfNotesBundle = { documents: PdfNotes[]; omittedFiles: string[] };
export type PdfInput = { type: "input_file"; filename: string; file_data: string; detail?: "high" };

type PdfSource = { inputFile: string; originalName: string; id: string };
type Fields = Record<string, unknown>;

function object(value: unknown): value is Fields {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export const pdfNotesFormat = {
  type: "json_schema", name: "assignment_pdf_notes", strict: true,
  schema: {
    type: "object", additionalProperties: false, required: ["markdown", "documents"],
    properties: {
      markdown: { type: "string" },
      documents: { type: "array", items: {
        type: "object", additionalProperties: false, required: ["inputFile", "overview", "coverage", "sections"],
        properties: {
          inputFile: { type: "string" }, overview: { type: "string" },
          coverage: { type: "string", enum: ["complete", "partial"] },
          sections: { type: "array", items: {
            type: "object", additionalProperties: false, required: ["from", "to", "text", "visuals"],
            properties: { from: { type: "integer" }, to: { type: "integer" }, text: { type: "string" }, visuals: { type: "string" } },
          } },
        },
      } },
    },
  },
};

export const pdfNotesInstructions = `
응답의 markdown에는 학습 가이드만 써요. documents에는 다음 질문에도 근거로 쓸 수 있도록 PDF 원문 정보를 가이드와 별개로 정리해요.
전달된 각 파일의 inputFile을 그대로 써요. overview에는 주제, 필요한 선행 개념과 결과물 또는 요구사항을 압축해요.
sections는 PDF 실제 페이지 번호(첫 페이지는 1)에 따라 정리해요. 짧은 자료는 페이지별로, 긴 자료는 관련 연속 페이지를 묶어요. text에는 지문·제약·코드 골격·함수명과 입출력 예시 등 핵심 내용을 구체적으로 남겨요. visuals에는 그림·표·스크린샷·그래프의 라벨과 관계, 시각적으로만 확인할 수 있는 값과 예시를 남겨요. 없는 항목은 빈 문자열로 둬요. 같은 내용은 반복하지 않아요.
실제 확인한 범위만 기록해요. 확인하지 못한 페이지나 판독할 수 없는 정보가 있으면 coverage를 partial로 표시해요. 확인할 수 없는 코드나 수치를 만들어 넣지 않아요. 자료에서 가져온 요구사항과 모델의 조언을 섞지 않아요.`;

function boundedText(value: unknown, limit: number) {
  return typeof value === "string" ? value.trim().slice(0, limit) : "";
}

export function parsePdfNotes(value: unknown, sources: PdfSource[]): PdfNotes[] {
  if (!Array.isArray(value)) return [];
  return sources.flatMap(({ inputFile, originalName, id }) => {
    const note = value.find((item) => object(item) && item.inputFile === inputFile);
    if (!object(note) || !Array.isArray(note.sections)) return [];
    const overview = boundedText(note.overview, 1200);
    const sections = note.sections.slice(0, 96).flatMap((section) => {
      if (!object(section) || typeof section.from !== "number" || typeof section.to !== "number" ||
          !Number.isSafeInteger(section.from) || !Number.isSafeInteger(section.to) || section.from < 1 || section.to < section.from) return [];
      const text = boundedText(section.text, 2400);
      const visuals = boundedText(section.visuals, 1600);
      return text || visuals ? [{ from: section.from, to: section.to, text, visuals }] : [];
    }).sort((a, b) => a.from - b.from || a.to - b.to);
    if (!overview && !sections.length) return [];
    return [{ id, name: originalName, overview, coverage: note.coverage === "complete" && sections.length === note.sections.length &&
      sections[0]?.from === 1 && sections.every((section, i) => i === 0 || section.from <= sections[i - 1].to + 1)
      ? "complete" as const : "partial" as const, sections }];
  });
}

export function storedPdfNotes(value: unknown, files: readonly { id: string; name: string }[]): PdfNotes[] | undefined {
  if (!Array.isArray(value)) return;
  const sources = files.map(({ id, name }) => ({ inputFile: id, originalName: name, id }));
  return parsePdfNotes(value.filter(object).map((item) => ({ ...item, inputFile: item.id })), sources);
}

export function pdfNotesForQuestion(bundle: PdfNotesBundle, question: string) {
  const normalized = question.toLowerCase();
  const pages = [...normalized.matchAll(/(\d{1,4})\s*(?:쪽|페이지|p\b)/g)].map((match) => Number(match[1]));
  const words = [...new Set(normalized.match(/[\p{L}\p{N}_]{2,}/gu) ?? [])].slice(0, 40);
  const named = bundle.documents.filter(({ name }) => normalized.includes(name.toLowerCase()));
  const documents = named.length ? named : bundle.documents;
  const ranked = documents.flatMap((document) => document.sections.map((section) => {
    const content = (section.text + " " + section.visuals).toLowerCase();
    const matchesPage = pages.some((page) => section.from <= page && section.to >= page);
    return { id: document.id, ...section, matchesPage, rank: words.filter((word) => content.includes(word)).length };
  })).sort((a, b) => Number(b.matchesPage) - Number(a.matchesPage) || b.rank - a.rank);

  let remaining = 9200;
  const selected = [];
  for (const { rank: _rank, matchesPage: _matchesPage, ...section } of ranked) {
    const size = JSON.stringify(section).length;
    if (size > remaining) continue;
    selected.push(section);
    remaining -= size;
  }
  return {
    documents: documents.map(({ id, name, overview, coverage, sections }) => ({
      id, name, overview: overview.slice(0, 700), coverage,
      pagesInNotes: sections.map(({ from, to }) => from === to ? String(from) : `${from}-${to}`).join(", "),
    })),
    sections: selected,
    excerpted: selected.length < ranked.length,
    omittedFiles: bundle.omittedFiles,
  };
}
