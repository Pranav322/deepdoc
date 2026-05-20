#!/usr/bin/env node
// MDX compile-check used by deepdoc's generation pipeline.
//
// Reads MDX content from stdin, attempts to compile it via @mdx-js/mdx, and
// reports the outcome to deepdoc. On success exits 0 with no output.
// On failure exits 1 with a single JSON object on stderr describing the error:
//   {"line": <int|null>, "column": <int|null>, "message": <string>, "ruleId": <string|null>}

import { compile } from "@mdx-js/mdx";
import remarkGfm from "remark-gfm";

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

function emitError(payload) {
  process.stderr.write(JSON.stringify(payload));
  process.exit(1);
}

(async () => {
  let source;
  try {
    source = await readStdin();
  } catch (err) {
    emitError({
      line: null,
      column: null,
      message: `failed to read stdin: ${err && err.message ? err.message : String(err)}`,
      ruleId: "stdin-read-error",
    });
    return;
  }

  try {
    await compile(source, {
      remarkPlugins: [remarkGfm],
      development: false,
    });
    process.exit(0);
  } catch (err) {
    const place = err && err.place;
    const start = place && (place.start || place);
    emitError({
      line: start && typeof start.line === "number" ? start.line : null,
      column: start && typeof start.column === "number" ? start.column : null,
      message: (err && err.reason) || (err && err.message) || String(err),
      ruleId: (err && err.ruleId) || null,
    });
  }
})();
