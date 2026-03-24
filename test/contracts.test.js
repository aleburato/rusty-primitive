import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";

const repoRoot = process.cwd();

function readRepoFile(...segments) {
  return fs.readFileSync(path.join(repoRoot, ...segments), "utf8");
}

function parseStringArray(source, label) {
  const match = source.match(new RegExp(`const ${label}:[^=]+= \\[(.*?)\\];`, "s"));
  assert.ok(match, `missing ${label}`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map((entry) => entry[1]);
}

function parseRustVariants(source, enumName) {
  const match = source.match(
    new RegExp(
      `impl ${enumName} \\{\\s+#[^\\n]+\\s+pub const fn variants\\(\\) -> &'static \\[&'static str\\] \\{\\s+&\\[(.*?)\\]\\s+\\}`,
      "s",
    ),
  );
  assert.ok(match, `missing ${enumName}::variants`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map((entry) => entry[1]);
}

function parseTsRenderDefaults(source) {
  const patterns = {
    count: /const count = .*\?\? (\d+);/,
    shape: /const shape = .*\?\? "([^"]+)";/,
    alpha: /const alpha = .*\?\? (\d+);/,
    repeat: /const repeat = .*\?\? (\d+);/,
    background: /const background = .*\?\? "([^"]+)";/,
    resizeInput: /const resizeInput = .*\?\? (\d+);/,
    outputSize: /const outputSize = .*\?\? (\d+);/,
  };

  return Object.fromEntries(
    Object.entries(patterns).map(([key, pattern]) => {
      const match = source.match(pattern);
      assert.ok(match, `missing TypeScript default for ${key}`);
      return [key, /^\d+$/.test(match[1]) ? Number(match[1]) : match[1]];
    }),
  );
}

function parseRustRenderDefaults(source) {
  const block = source.match(/impl Default for RenderOptions \{.*?Self \{(.*?)\n\s*}\n\s*}/s);
  assert.ok(block, "missing RenderOptions::default");

  const patterns = {
    count: /count:\s*(\d+),/,
    shape: /shape:\s*ShapeKind::([A-Za-z]+),/,
    alpha: /alpha:\s*AlphaOption::Fixed\((\d+)\),/,
    repeat: /repeat:\s*(\d+),/,
    background: /background:\s*BackgroundOption::([A-Za-z]+),/,
    resizeInput: /resize_input:\s*(\d+),/,
    outputSize: /output_size:\s*(\d+),/,
  };

  const values = Object.fromEntries(
    Object.entries(patterns).map(([key, pattern]) => {
      const match = block[1].match(pattern);
      assert.ok(match, `missing Rust default for ${key}`);
      return [key, match[1]];
    }),
  );

  return {
    count: Number(values.count),
    shape: values.shape.toLowerCase(),
    alpha: Number(values.alpha),
    repeat: Number(values.repeat),
    background: values.background.toLowerCase(),
    resizeInput: Number(values.resizeInput),
    outputSize: Number(values.outputSize),
  };
}

function parseAlphaMessage(source, fileLabel) {
  const match = source.match(/alpha must be[^"\n]*/);
  assert.ok(match, `missing alpha validation message in ${fileLabel}`);
  return match[0];
}

test("wrapper shape vocabulary mirrors Rust", () => {
  const tsSource = readRepoFile("src", "index.ts");
  const rustSource = readRepoFile("crates", "primeval-core", "src", "shapes.rs");

  assert.deepEqual(
    parseStringArray(tsSource, "VALID_SHAPES"),
    parseRustVariants(rustSource, "ShapeKind"),
  );
});

test("wrapper output vocabulary mirrors Rust", () => {
  const tsSource = readRepoFile("src", "index.ts");
  const rustSource = readRepoFile("crates", "primeval-core", "src", "export.rs");

  assert.deepEqual(
    parseStringArray(tsSource, "VALID_OUTPUTS"),
    parseRustVariants(rustSource, "OutputFormat"),
  );
});

test("wrapper render defaults mirror Rust", () => {
  const tsSource = readRepoFile("src", "index.ts");
  const rustSource = readRepoFile("crates", "primeval-render", "src", "lib.rs");

  assert.deepEqual(parseTsRenderDefaults(tsSource), parseRustRenderDefaults(rustSource));
});

test("alpha validation message is aligned across surfaces", () => {
  const messages = [
    parseAlphaMessage(readRepoFile("src", "index.ts"), "src/index.ts"),
    parseAlphaMessage(
      readRepoFile("crates", "primeval-render", "src", "lib.rs"),
      "crates/primeval-render/src/lib.rs",
    ),
    parseAlphaMessage(
      readRepoFile("crates", "primeval-render", "src", "lib.rs"),
      "crates/primeval-render/src/lib.rs",
    ),
  ];

  assert.deepEqual(messages, new Array(messages.length).fill("alpha must be 1..255 or auto"));
});

test("cli and binding use shared Rust option parsers", () => {
  const cliSource = readRepoFile("crates", "primeval-cli", "src", "main.rs");
  const bindingSource = readRepoFile("binding", "src", "binding.rs");

  assert.match(cliSource, /parse_alpha_str/);
  assert.match(cliSource, /parse_background_str/);
  assert.match(bindingSource, /parse_alpha_u32/);
  assert.match(bindingSource, /parse_background_str/);
  assert.match(bindingSource, /parse_seed_i64/);
});

test("package test script exercises the native package path", () => {
  const pkg = JSON.parse(readRepoFile("package.json"));

  assert.match(pkg.scripts.pretest, /build:node/);
  assert.match(pkg.scripts.test, /test\/native\.test\.js/);
});
