import { useState, type ReactNode } from "react";
import type { ChatSource } from "../shared/chat.js";
import "./chat-answer.css";

type AnswerBlock = { kind: "prose"; text: string } | { kind: "code"; text: string; language: string };

function splitAnswer(text: string): AnswerBlock[] {
  const blocks: AnswerBlock[] = [];
  const lines = text.split(/\r\n?|\n/);
  let proseStart = 0;

  function appendProse(end: number) {
    const prose = lines.slice(proseStart, end).join("\n").replace(/^(?:[ \t]*\n)+|(?:\n[ \t]*)+$/g, "");
    if (prose.trim()) blocks.push({ kind: "prose", text: prose });
  }

  for (let index = 0; index < lines.length; index++) {
    const opening = /^( {0,3})(`{3,}|~{3,})(.*)$/.exec(lines[index]);
    if (!opening) continue;
    const [, indent, marker, info] = opening;
    if (marker.startsWith("`") && info.includes("`")) continue;

    appendProse(index);
    const code: string[] = [];
    for (index++; index < lines.length; index++) {
      const line = lines[index];
      const closing = /^ {0,3}(`{3,}|~{3,})[ \t]*$/.exec(line)?.[1];
      if (closing && closing[0] === marker[0] && closing.length >= marker.length) break;
      const leadingSpaces = line.match(/^ */)![0].length;
      code.push(line.slice(Math.min(indent.length, leadingSpaces)));
    }
    blocks.push({ kind: "code", text: code.join("\n"), language: info.trim().split(/\s+/, 1)[0] });
    proseStart = index + 1;
  }

  appendProse(lines.length);
  return blocks;
}

type SourceLinks = { sources?: ChatSource[]; onOpenSource?: (url: string) => void };

const deadlineBadge = /^(?:D[-−+]\d+|D-day|오늘 마감 지남|마감일 확인 필요)$/i;
const overdueBadge = /^(?:D\+\d+|오늘 마감 지남)$/i;
const inlinePattern = /(\\[!"#$%&'()*+,./:;<=>?@[\]\\^`_{|}~\x2d]|\*\*[^*\n]+\*\*|__[^_\n]+__|`[^`\n]+`|\[(?:\\[^\n]|[^\]\\\n])+\]\((?:[^()\n]|\([^()\n]*\))*\)|(?<!\S)\*[^*\s][^*\n]*?\*(?!\*)|~~[^~\n]+~~)/g;

function inlineText(text: string, links: SourceLinks): ReactNode[] {
  return text.split(inlinePattern).map((part, index) => {
    if (part.length === 2 && part.startsWith("\\")) return part[1];
    if ((part.startsWith("**") && part.endsWith("**") || part.startsWith("__") && part.endsWith("__")) && part.length > 4) {
      const label = part.slice(2, -2);
      const badge = deadlineBadge.test(label);
      return <strong key={index} className={badge ? "chat-deadline-badge" : undefined}
        data-overdue={badge && overdueBadge.test(label) ? true : undefined}>{inlineText(label, links)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    if (part.startsWith("~~") && part.endsWith("~~") && part.length > 4) return <del key={index}>{part.slice(2, -2)}</del>;
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) return <em key={index}>{part.slice(1, -1)}</em>;
    const link = /^\[((?:\\.|[^\]\\\n])+)\]\(((?:[^()\n]|\([^()\n]*\))*)\)$/.exec(part);
    if (!link) return part;
    const [, label, url] = link;
    const displayLabel = label.replace(/\\([\\`*_[\]~])/g, "$1");
    // Model-written URLs are only clickable when a tool has returned the same source.
    const source = links.sources?.find((item) => item.url === url);
    const openSource = links.onOpenSource;
    if (!source || !openSource) return displayLabel;
    const title = source.title === "조회한 원문" ? displayLabel : source.title;
    return <button key={index} type="button" className="chat-inline-source" onClick={() => openSource(url)}>
      <span>{title}</span><span className="chat-inline-source-arrow" aria-hidden="true">↗</span>
    </button>;
  });
}

const headingLine = /^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?$/;
const listLine = /^ {0,3}([-*+]|\d{1,9}[.)])[ \t]+(.+)$/;
const quoteLine = /^ {0,3}>[ \t]?(.*)$/;
const dividerLine = /^ {0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$/;
const tableDelimiter = /^:?-+:?$/;

function tableCells(line: string): string[] {
  const cells = [""];
  const row = line.trim().replace(/^\|/, "");
  for (const match of row.matchAll(/\\.|[^\\|]+|\||\\/g)) {
    if (match[0] === "|") cells.push("");
    else cells[cells.length - 1] += match[0];
  }
  if (cells.length > 1 && cells.at(-1) === "") cells.pop();
  return cells.map((cell) => cell.trim());
}

function tableHeading(line: string, separator: string) {
  if (!line.includes("|") || !separator.includes("|")) return;
  const headers = tableCells(line);
  const markers = tableCells(separator);
  if (headers.length < 2 || headers.length !== markers.length || !markers.every((cell) => tableDelimiter.test(cell))) return;
  const alignments = markers.map((marker) => marker.endsWith(":") ? marker.startsWith(":") ? "center" : "right" : undefined);
  return { headers, alignments };
}

function Prose({ text, ...links }: { text: string } & SourceLinks) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const key = index;
    const line = lines[index++];
    if (!line.trim()) continue;

    const heading = headingLine.exec(line);
    const table = tableHeading(line, lines[index] ?? "");
    if (heading) {
      const Heading = heading[1].length <= 2 ? "h3" : "h4";
      blocks.push(<Heading key={key}>{inlineText(heading[2], links)}</Heading>);
    } else if (dividerLine.test(line)) {
      blocks.push(<hr key={key} />);
    } else if (quoteLine.test(line)) {
      const quoted = [quoteLine.exec(line)![1]];
      while (index < lines.length && quoteLine.test(lines[index])) quoted.push(quoteLine.exec(lines[index++])![1]);
      blocks.push(<blockquote key={key}><p>{inlineText(quoted.join("\n"), links)}</p></blockquote>);
    } else if (table && !listLine.test(line)) {
      const rows: string[][] = [];
      index++;
      while (lines[index]?.includes("|") && ![headingLine, listLine, quoteLine].some((pattern) => pattern.test(lines[index]))) {
        rows.push(tableCells(lines[index++]));
      }
      blocks.push(<div className="chat-markdown-table" key={key} tabIndex={0} role="region" aria-label="답변 표">
        <table>
          <thead><tr>{table.headers.map((cell, column) =>
            <th key={column} scope="col" data-align={table.alignments[column]}>{inlineText(cell, links)}</th>)}</tr></thead>
          <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{table.headers.map((_, column) =>
            <td key={column} data-align={table.alignments[column]}>{inlineText(row[column] ?? "", links)}</td>)}</tr>)}</tbody>
        </table>
      </div>);
    } else if (listLine.test(line)) {
      const first = listLine.exec(line)!;
      const ordered = /^\d/.test(first[1]);
      const items: ReactNode[] = [];
      let item: RegExpExecArray | null = first;
      while (item && /^\d/.test(item[1]) === ordered) {
        const details: string[] = [];
        while (index < lines.length && lines[index].trim() && !listLine.test(lines[index]) && /^ {2,}|^\t/.test(lines[index])) {
          details.push(lines[index++].trim());
        }
        items.push(<li key={items.length}>{inlineText(item[2], links)}
          {details.length > 0 && <span className="chat-list-detail">{inlineText(details.join("\n"), links)}</span>}</li>);
        item = listLine.exec(lines[index] ?? "");
        if (item && /^\d/.test(item[1]) === ordered) index++;
      }
      blocks.push(ordered ? <ol key={key} start={Number.parseInt(first[1], 10)}>{items}</ol> : <ul key={key}>{items}</ul>);
    } else {
      const paragraph = [line];
      while (index < lines.length && lines[index].trim() &&
          ![headingLine, listLine, quoteLine, dividerLine].some((pattern) => pattern.test(lines[index])) &&
          !tableHeading(lines[index], lines[index + 1] ?? "")) {
        paragraph.push(lines[index++]);
      }
      blocks.push(<p key={key}>{inlineText(paragraph.join("\n"), links)}</p>);
    }
  }
  return <>{blocks}</>;
}

function CodeBlock({ text, language }: { text: string; language: string }) {
  const [copyStatus, setCopyStatus] = useState("");

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopyStatus("복사했어요");
    } catch {
      setCopyStatus("복사하지 못했어요");
    }
  }

  return <div className="chat-code-block">
    <div className="chat-code-header">
      <span>{language || "코드"}</span>
      <button type="button" className="chat-text-button" onClick={() => void copy()} aria-label="코드 복사">
        <span aria-live="polite">{copyStatus || "복사"}</span>
      </button>
    </div>
    <pre tabIndex={0} aria-label={language ? `${language} 코드` : "코드"}><code>{text}</code></pre>
  </div>;
}

export function ChatAnswer({ text, ...links }: { text: string } & SourceLinks) {
  return <div className="chat-answer-text">{splitAnswer(text).map((block, index) => block.kind === "code"
    ? <CodeBlock key={index} text={block.text} language={block.language} />
    : <Prose key={index} text={block.text} {...links} />)}</div>;
}
