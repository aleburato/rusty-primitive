import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const TARGET_SUFFIXES = {
  "aarch64-apple-darwin": "darwin-arm64",
  "x86_64-apple-darwin": "darwin-x64",
  "aarch64-unknown-linux-gnu": "linux-arm64-gnu",
  "x86_64-unknown-linux-gnu": "linux-x64-gnu",
  "x86_64-pc-windows-msvc": "win32-x64-msvc",
};

const TARGET_RUNNERS = {
  "aarch64-apple-darwin": "macos-14",
  "x86_64-apple-darwin": "macos-13",
  "aarch64-unknown-linux-gnu": "ubuntu-24.04-arm",
  "x86_64-unknown-linux-gnu": "ubuntu-latest",
  "x86_64-pc-windows-msvc": "windows-latest",
};

const DEFAULT_PACKAGE_JSON = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "package.json",
);

export function optionalDependencyNamesForTargets(packageName, targets) {
  return targets.map((target) => `${packageName}-${packageSuffixForTarget(target)}`);
}

export function releaseMatrixForTargets(targets) {
  return {
    include: targets.map((target) => ({
      runner: runnerForTarget(target),
      target,
    })),
  };
}

export function readPackageMetadata(packageJsonPath = DEFAULT_PACKAGE_JSON) {
  return JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
}

export function validatePackageMetadata(pkg) {
  const packageName = requiredString(pkg.name, "package.json name");
  const version = requiredString(pkg.version, "package.json version");
  const targets = requiredTargets(pkg.napi?.targets);
  const expectedOptionalDependencies = optionalDependencyNamesForTargets(packageName, targets);
  const actualOptionalDependencies = Object.keys(pkg.optionalDependencies ?? {}).sort();

  if (
    JSON.stringify(actualOptionalDependencies) !==
    JSON.stringify([...expectedOptionalDependencies].sort())
  ) {
    throw new Error(
      `optionalDependencies drift from napi.targets; expected ${expectedOptionalDependencies.join(
        ", ",
      )}, got ${actualOptionalDependencies.join(", ") || "(none)"}`,
    );
  }

  for (const dependencyName of expectedOptionalDependencies) {
    if (pkg.optionalDependencies[dependencyName] !== version) {
      throw new Error(
        `optional dependency ${dependencyName} must match package version ${version}`,
      );
    }
  }

  return {
    packageName,
    targets,
    version,
    expectedOptionalDependencies,
  };
}

export function verifyArtifacts(artifactsDir, pkg) {
  const { expectedOptionalDependencies, targets } = validatePackageMetadata(pkg);
  const absoluteArtifactsDir = path.resolve(artifactsDir);
  if (!fs.existsSync(absoluteArtifactsDir)) {
    throw new Error(`artifact directory does not exist: ${absoluteArtifactsDir}`);
  }

  const missingPackages = [];
  const missingPayloads = [];

  for (const [index, dependencyName] of expectedOptionalDependencies.entries()) {
    const target = targets[index];
    const candidates = findArtifactCandidates(absoluteArtifactsDir, dependencyName);
    if (candidates.length === 0) {
      missingPackages.push(dependencyName);
      continue;
    }

    const hasNodePayload = candidates.some((candidate) =>
      candidateContainsNodePayload(candidate, expectedNodePayloadName(target)),
    );
    if (!hasNodePayload) {
      missingPayloads.push(dependencyName);
    }
  }

  if (missingPackages.length > 0 || missingPayloads.length > 0) {
    const parts = [];
    if (missingPackages.length > 0) {
      parts.push(`missing package artifacts: ${missingPackages.join(", ")}`);
    }
    if (missingPayloads.length > 0) {
      parts.push(`missing .node payloads: ${missingPayloads.join(", ")}`);
    }
    throw new Error(parts.join("; "));
  }
}

function requiredString(value, label) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${label} is required`);
  }
  return value;
}

function requiredTargets(targets) {
  if (!Array.isArray(targets) || targets.length === 0) {
    throw new Error("package.json napi.targets must be a non-empty array");
  }
  return targets.map((target) => requiredString(target, "napi.targets entry"));
}

function packageSuffixForTarget(target) {
  const suffix = TARGET_SUFFIXES[target];
  if (!suffix) {
    throw new Error(`unsupported napi target: ${target}`);
  }
  return suffix;
}

function runnerForTarget(target) {
  const runner = TARGET_RUNNERS[target];
  if (!runner) {
    throw new Error(`no GitHub runner mapping for napi target: ${target}`);
  }
  return runner;
}

function findArtifactCandidates(rootDir, dependencyName) {
  const normalized = dependencyName.replace(/^@/, "").replace("/", "-");
  const packageDirs = [];
  const matchingFiles = [];
  const queue = [rootDir];

  while (queue.length > 0) {
    const current = queue.pop();
    const packageJsonPath = path.join(current, "package.json");
    if (fs.existsSync(packageJsonPath)) {
      try {
        const pkg = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
        if (pkg.name === dependencyName) {
          packageDirs.push(current);
          continue;
        }
      } catch {}
    }

    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const resolved = path.join(current, entry.name);
      if (entry.isDirectory()) {
        queue.push(resolved);
      } else if (entry.isFile()) {
        const basename = path.basename(resolved);
        if (
          basename.includes(normalized) ||
          resolved.includes(`${path.sep}${normalized}${path.sep}`)
        ) {
          matchingFiles.push(resolved);
        }
      }
    }
  }

  return [...new Set([...packageDirs, ...matchingFiles])];
}

function walkFiles(rootDir) {
  const files = [];
  const stack = [rootDir];
  while (stack.length > 0) {
    const current = stack.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const resolved = path.join(current, entry.name);
      if (entry.isDirectory()) {
        stack.push(resolved);
      } else if (entry.isFile()) {
        files.push(resolved);
      }
    }
  }
  return files;
}

function candidateContainsNodePayload(candidate, expectedPayloadName) {
  if (fs.existsSync(candidate) && fs.statSync(candidate).isDirectory()) {
    return walkFiles(candidate).some((file) => path.basename(file) === expectedPayloadName);
  }
  if (candidate.endsWith(".node")) {
    return path.basename(candidate).includes(expectedPayloadName);
  }
  if (candidate.endsWith(".tgz")) {
    return tarballContainsNodePayload(candidate, expectedPayloadName);
  }
  return false;
}

function tarballContainsNodePayload(candidate, expectedPayloadName) {
  const listing = execFileSync("tar", ["-tf", candidate], {
    encoding: "utf8",
  });
  return listing
    .split("\n")
    .some((line) => line.endsWith(expectedPayloadName) || line.endsWith(`/${expectedPayloadName}`));
}

function expectedNodePayloadName(target) {
  return `primeval-node.${packageSuffixForTarget(target)}.node`;
}

function usage() {
  console.error(
    [
      "Usage:",
      "  node scripts/napi-targets.mjs check-package [package.json path]",
      "  node scripts/napi-targets.mjs release-matrix [package.json path]",
      "  node scripts/napi-targets.mjs expected-packages [package.json path]",
      "  node scripts/napi-targets.mjs verify-artifacts <artifacts dir> [package.json path]",
    ].join("\n"),
  );
}

function main(argv) {
  const [command, firstArg, secondArg] = argv;
  if (!command) {
    usage();
    process.exitCode = 1;
    return;
  }

  try {
    switch (command) {
      case "check-package": {
        const result = validatePackageMetadata(readPackageMetadata(firstArg));
        console.log(JSON.stringify(result));
        break;
      }
      case "release-matrix": {
        const pkg = readPackageMetadata(firstArg);
        const { targets } = validatePackageMetadata(pkg);
        console.log(JSON.stringify(releaseMatrixForTargets(targets)));
        break;
      }
      case "expected-packages": {
        const result = validatePackageMetadata(readPackageMetadata(firstArg));
        console.log(JSON.stringify(result.expectedOptionalDependencies));
        break;
      }
      case "verify-artifacts": {
        if (!firstArg) {
          throw new Error("verify-artifacts requires an artifacts directory");
        }
        const pkg = readPackageMetadata(secondArg);
        verifyArtifacts(firstArg, pkg);
        console.log(`verified artifacts for ${pkg.name}`);
        break;
      }
      default:
        throw new Error(`unknown command: ${command}`);
    }
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2));
}
