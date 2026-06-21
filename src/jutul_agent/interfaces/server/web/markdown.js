// A small, safe markdown renderer: enough for assistant replies, no dependencies.
// It escapes all HTML first, so model output can never inject markup, then applies
// a conservative subset (code fences, inline code, bold/italic, headings, lists,
// links). Not a full CommonMark implementation; it just has to read well.

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function inline(s) {
  return s
    .replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

function renderMarkdown(text) {
  const escaped = escapeHtml(text);
  const parts = escaped.split(/```/);
  let html = "";
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 1) {
      // fenced code block: drop an optional language tag on the first line
      const body = parts[i].replace(/^[^\n]*\n/, "");
      html += `<pre><code>${body}</code></pre>`;
      continue;
    }
    html += renderBlocks(parts[i]);
  }
  return html;
}

function isTableSep(line) {
  return line.includes("-") && /^\s*\|?[\s:|-]+\|?\s*$/.test(line);
}
function splitRow(line) {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

function renderBlocks(segment) {
  const lines = segment.split("\n");
  let html = "";
  let list = null; // "ul" | "ol" | null
  let para = [];

  const flushPara = () => {
    if (para.length) {
      // Join wrapped lines with hard breaks (like the terminal UI), so a single
      // newline shows as a line break rather than collapsing into a space.
      html += `<p>${para.map((l) => inline(l)).join("<br>")}</p>`;
      para = [];
    }
  };
  const closeList = () => {
    if (list) {
      html += `</${list}>`;
      list = null;
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trimEnd();
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    const bullet = line.match(/^[-*]\s+(.*)$/);
    const ordered = line.match(/^\d+\.\s+(.*)$/);
    const quote = line.match(/^&gt;\s?(.*)$/); // '>' is HTML-escaped before block parsing
    // A GitHub-style table: a row, then a |---|---| separator line.
    const isTable = line.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1]);

    if (!line.trim()) {
      flushPara();
      closeList();
    } else if (isTable) {
      flushPara();
      closeList();
      const head = splitRow(line);
      let body = "";
      i += 2; // skip the header and the separator
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        const cells = splitRow(lines[i]);
        body += "<tr>" + cells.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>";
        i++;
      }
      i--; // the for-loop will advance past the last consumed row
      const thead = "<tr>" + head.map((c) => `<th>${inline(c)}</th>`).join("") + "</tr>";
      html += `<table><thead>${thead}</thead><tbody>${body}</tbody></table>`;
    } else if (heading) {
      flushPara();
      closeList();
      const level = heading[1].length;
      html += `<h${level}>${inline(heading[2])}</h${level}>`;
    } else if (quote) {
      flushPara();
      closeList();
      html += `<blockquote>${inline(quote[1])}</blockquote>`;
    } else if (bullet) {
      flushPara();
      if (list !== "ul") {
        closeList();
        list = "ul";
        html += "<ul>";
      }
      html += `<li>${inline(bullet[1])}</li>`;
    } else if (ordered) {
      flushPara();
      if (list !== "ol") {
        closeList();
        list = "ol";
        html += "<ol>";
      }
      html += `<li>${inline(ordered[1])}</li>`;
    } else {
      closeList();
      para.push(line);
    }
  }
  flushPara();
  closeList();
  return html;
}

window.renderMarkdown = renderMarkdown;
