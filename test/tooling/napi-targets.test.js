import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import {
  optionalDependencyNamesForTargets,
  releaseMatrixForTargets,
  validatePackageMetadata,
  verifyArtifacts,
} from "../../scripts/napi-targets.mjs";

test("optional dependencies are derived from napi targets", () => {
  assert.deepEqual(
    optionalDependencyNamesForTargets(
      "@aleburato/primeval",
      [
        "aarch64-apple-darwin",
        "x86_64-apple-darwin",
        "aarch64-unknown-linux-gnu",
        "x86_64-unknown-linux-gnu",
        "x86_64-pc-windows-msvc",
      ],
    ),
    [
      "@aleburato/primeval-darwin-arm64",
      "@aleburato/primeval-darwin-x64",
      "@aleburato/primeval-linux-arm64-gnu",
      "@aleburato/primeval-linux-x64-gnu",
      "@aleburato/primeval-win32-x64-msvc",
    ],
  );
});

test("release matrix runners are derived from napi targets", () => {
  assert.deepEqual(releaseMatrixForTargets(["x86_64-unknown-linux-gnu"]), {
    include: [
      {
        runner: "ubuntu-latest",
        target: "x86_64-unknown-linux-gnu",
      },
    ],
  });
});

test("package metadata validation rejects drift between targets and optional dependencies", () => {
  assert.throws(
    () =>
      validatePackageMetadata({
        name: "@aleburato/primeval",
        version: "0.1.0",
        optionalDependencies: {
          "@aleburato/primeval-linux-x64-gnu": "0.1.0",
        },
        napi: {
          targets: [
            "aarch64-apple-darwin",
            "x86_64-apple-darwin",
            "aarch64-unknown-linux-gnu",
            "x86_64-unknown-linux-gnu",
            "x86_64-pc-windows-msvc",
          ],
        },
      }),
    /optionalDependencies/i,
  );
});

test("artifact verification accepts matching native payloads", () => {
  const artifactsDir = fs.mkdtempSync(path.join(os.tmpdir(), "primeval-artifacts-"));
  try {
    fs.writeFileSync(
      path.join(
        artifactsDir,
        "aleburato-primeval-linux-x64-gnu.primeval-node.linux-x64-gnu.node",
      ),
      Buffer.alloc(0),
    );

    verifyArtifacts(artifactsDir, {
      name: "@aleburato/primeval",
      version: "0.1.0",
      optionalDependencies: {
        "@aleburato/primeval-linux-x64-gnu": "0.1.0",
      },
      napi: {
        targets: ["x86_64-unknown-linux-gnu"],
      },
    });
  } finally {
    fs.rmSync(artifactsDir, { recursive: true, force: true });
  }
});

test("artifact verification rejects missing native payloads", () => {
  const artifactsDir = fs.mkdtempSync(path.join(os.tmpdir(), "primeval-artifacts-"));
  try {
    fs.writeFileSync(
      path.join(artifactsDir, "aleburato-primeval-linux-x64-gnu.txt"),
      "placeholder",
    );

    assert.throws(
      () =>
        verifyArtifacts(artifactsDir, {
          name: "@aleburato/primeval",
          version: "0.1.0",
          optionalDependencies: {
            "@aleburato/primeval-linux-x64-gnu": "0.1.0",
          },
          napi: {
            targets: ["x86_64-unknown-linux-gnu"],
          },
        }),
      /missing \.node payloads/i,
    );
  } finally {
    fs.rmSync(artifactsDir, { recursive: true, force: true });
  }
});

test("artifact verification accepts napi package directories", () => {
  const artifactsDir = fs.mkdtempSync(path.join(os.tmpdir(), "primeval-artifacts-"));
  const packageDir = path.join(artifactsDir, "npm", "linux-x64-gnu");

  try {
    fs.mkdirSync(packageDir, { recursive: true });
    fs.writeFileSync(
      path.join(packageDir, "package.json"),
      JSON.stringify({
        name: "@aleburato/primeval-linux-x64-gnu",
        version: "0.1.0",
      }),
    );
    fs.writeFileSync(
      path.join(packageDir, "primeval-node.linux-x64-gnu.node"),
      Buffer.alloc(0),
    );

    verifyArtifacts(artifactsDir, {
      name: "@aleburato/primeval",
      version: "0.1.0",
      optionalDependencies: {
        "@aleburato/primeval-linux-x64-gnu": "0.1.0",
      },
      napi: {
        targets: ["x86_64-unknown-linux-gnu"],
      },
    });
  } finally {
    fs.rmSync(artifactsDir, { recursive: true, force: true });
  }
});

test("artifact verification rejects wrong target payloads", () => {
  const artifactsDir = fs.mkdtempSync(path.join(os.tmpdir(), "primeval-artifacts-"));
  const packageDir = path.join(artifactsDir, "npm", "linux-x64-gnu");

  try {
    fs.mkdirSync(packageDir, { recursive: true });
    fs.writeFileSync(
      path.join(packageDir, "package.json"),
      JSON.stringify({
        name: "@aleburato/primeval-linux-x64-gnu",
        version: "0.1.0",
      }),
    );
    fs.writeFileSync(
      path.join(packageDir, "primeval-node.win32-x64-msvc.node"),
      Buffer.alloc(0),
    );

    assert.throws(
      () =>
        verifyArtifacts(artifactsDir, {
          name: "@aleburato/primeval",
          version: "0.1.0",
          optionalDependencies: {
            "@aleburato/primeval-linux-x64-gnu": "0.1.0",
          },
          napi: {
            targets: ["x86_64-unknown-linux-gnu"],
          },
        }),
      /missing \.node payloads/i,
    );
  } finally {
    fs.rmSync(artifactsDir, { recursive: true, force: true });
  }
});
