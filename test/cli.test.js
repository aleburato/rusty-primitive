import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

const repoRoot = process.cwd();
const fixturePath = path.join(repoRoot, "docs", "readme", "originals", "monalisa.jpg");
const cliPath = path.join(repoRoot, "dist", "cli.js");

function runCli(args) {
  return spawnSync(process.execPath, [cliPath, ...args], {
    cwd: repoRoot,
    encoding: "utf8",
  });
}

function makeTmpDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "primeval-node-cli-test-"));
}

test("cli writes svg output file", () => {
  const tmpDir = makeTmpDir();
  const output = path.join(tmpDir, "out.svg");

  const result = runCli([
    fixturePath,
    "--output",
    output,
    "--count",
    "4",
    "--resize-input",
    "8",
    "--output-size",
    "16",
    "--seed",
    "7",
    "--progress",
    "off",
  ]);

  assert.equal(result.status, 0, result.stderr);
  const svg = fs.readFileSync(output, "utf8");
  assert.match(svg, /^<svg\b/);
});

test("cli supports stdout output", () => {
  const result = runCli([
    fixturePath,
    "--output",
    "-",
    "--count",
    "4",
    "--resize-input",
    "8",
    "--output-size",
    "16",
    "--seed",
    "7",
    "--progress",
    "off",
  ]);

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /^<svg\b/);
});

test("cli suppresses progress with --progress off", () => {
  const tmpDir = makeTmpDir();
  const output = path.join(tmpDir, "out.svg");

  const result = runCli([
    fixturePath,
    "--output",
    output,
    "--count",
    "4",
    "--resize-input",
    "8",
    "--output-size",
    "16",
    "--seed",
    "7",
    "--progress",
    "off",
  ]);

  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stderr.trim(), "");
});

test("cli treats --alpha 0 as auto", () => {
  const tmpDir = makeTmpDir();
  const output = path.join(tmpDir, "out.svg");

  const result = runCli([
    fixturePath,
    "--output",
    output,
    "--count",
    "4",
    "--alpha",
    "0",
    "--resize-input",
    "8",
    "--output-size",
    "16",
    "--seed",
    "7",
    "--progress",
    "off",
  ]);

  assert.equal(result.status, 0, result.stderr);
  const svg = fs.readFileSync(output, "utf8");
  assert.match(svg, /^<svg\b/);
});

test("cli prints help", () => {
  const result = runCli(["--help"]);
  assert.equal(result.status, 0);
  assert.match(result.stdout, /Usage:/);
});

test("cli exits non-zero with missing args", () => {
  const result = runCli([]);
  assert.equal(result.status, 1);
});

test("cli exits non-zero with missing input file", () => {
  const tmpDir = makeTmpDir();
  const output = path.join(tmpDir, "out.svg");
  const result = runCli([
    path.join(tmpDir, "does-not-exist.jpg"),
    "--output",
    output,
    "--progress",
    "off",
  ]);

  assert.equal(result.status, 1);
});
