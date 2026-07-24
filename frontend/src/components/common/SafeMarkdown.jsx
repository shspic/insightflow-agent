import { useMemo } from "react";

export function extractMarkdownHeadings(content = "") {
  let index = 0;
  return String(content).split(/\r?\n/).flatMap((line) => {
    const match = /^(#{1,4})\s+(.+)$/.exec(line);
    if (!match) return [];
    return [{ id: `report-section-${index++}`, level: match[1].length, label: match[2] }];
  });
}

function inlineText(text) {
  const parts = String(text).split(/(\[\d+\])/g);
  return parts.map((part, index) => (
    /^\[\d+\]$/.test(part)
      ? <a key={`${part}-${index}`} href={`#citation-${part.slice(1, -1)}`}>{part}</a>
      : part
  ));
}

function parseRows(lines) {
  return lines.map((line) => line.replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim()));
}

export default function SafeMarkdown({ content = "" }) {
  const blocks = useMemo(() => {
    const lines = String(content).replace(/\r\n/g, "\n").split("\n");
    const result = [];
    let headingIndex = 0;
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) {
        index += 1;
        continue;
      }
      if (line.startsWith("```")) {
        const code = [];
        index += 1;
        while (index < lines.length && !lines[index].startsWith("```")) code.push(lines[index++]);
        result.push({ type: "code", value: code.join("\n") });
        index += 1;
        continue;
      }
      const heading = /^(#{1,4})\s+(.+)$/.exec(line);
      if (heading) {
        result.push({
          type: "heading",
          level: heading[1].length,
          value: heading[2],
          id: `report-section-${headingIndex++}`,
        });
        index += 1;
        continue;
      }
      if (/^\s*[-*]\s+/.test(line)) {
        const items = [];
        while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
          items.push(lines[index].replace(/^\s*[-*]\s+/, ""));
          index += 1;
        }
        result.push({ type: "list", items });
        continue;
      }
      if (line.includes("|") && lines[index + 1]?.match(/^\s*\|?[\s:-]+\|/)) {
        const table = [line];
        index += 2;
        while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
          table.push(lines[index++]);
        }
        result.push({ type: "table", rows: parseRows(table) });
        continue;
      }
      const paragraph = [line];
      index += 1;
      while (index < lines.length && lines[index].trim() && !/^(#{1,4})\s+/.test(lines[index])) {
        if (lines[index].startsWith("```") || /^\s*[-*]\s+/.test(lines[index])) break;
        paragraph.push(lines[index++]);
      }
      result.push({ type: "paragraph", value: paragraph.join(" ") });
    }
    return result;
  }, [content]);

  return (
    <article className="safe-markdown">
      {blocks.map((block, index) => {
        if (block.type === "heading") {
          const Tag = `h${Math.min(4, block.level + 1)}`;
          return <Tag id={block.id} key={index}>{inlineText(block.value)}</Tag>;
        }
        if (block.type === "list") {
          return <ul key={index}>{block.items.map((item) => <li key={item}>{inlineText(item)}</li>)}</ul>;
        }
        if (block.type === "code") {
          return <details key={index}><summary>查看代码或结构化内容</summary><pre><code>{block.value}</code></pre></details>;
        }
        if (block.type === "table") {
          const [head, ...body] = block.rows;
          return (
            <div className="table-scroll safe-markdown__table" key={index}>
              <table><thead><tr>{head.map((cell) => <th key={cell}>{cell}</th>)}</tr></thead>
                <tbody>{body.map((row, rowIndex) => (
                  <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={`${cell}-${cellIndex}`}>{cell}</td>)}</tr>
                ))}</tbody></table>
            </div>
          );
        }
        return <p key={index}>{inlineText(block.value)}</p>;
      })}
    </article>
  );
}
