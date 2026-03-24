import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

// --- Public types ---

export type InputSource =
  | { kind: "path"; path: string }
  | { kind: "bytes"; data: Buffer | Uint8Array };

export type OutputFormat = "svg" | "png" | "jpg" | "gif";

export type Shape =
  | "any"
  | "triangle"
  | "rectangle"
  | "ellipse"
  | "circle"
  | "rotated-rectangle"
  | "quadratic"
  | "rotated-ellipse"
  | "polygon";

export type RenderOptions = {
  count?: number;
  shape?: Shape;
  alpha?: number | "auto";
  repeat?: number;
  seed?: number;
  background?: "auto" | string;
  resizeInput?: number;
  outputSize?: number;
};

export type ProgressInfo = {
  step: number;
  total: number;
  score: number;
};

export type ExecutionOptions = {
  onProgress?: (info: ProgressInfo) => void;
  signal?: AbortSignal;
};

export type ApproximateRequest = {
  input: InputSource;
  output: OutputFormat;
  render?: RenderOptions;
  execution?: ExecutionOptions;
};

export type SvgResult = {
  format: "svg";
  data: string;
  mimeType: "image/svg+xml";
  width: number;
  height: number;
};

export type RasterResult = {
  format: "png" | "jpg" | "gif";
  data: Buffer;
  mimeType: "image/png" | "image/jpeg" | "image/gif";
  width: number;
  height: number;
};

export type ApproximateResult = SvgResult | RasterResult;

// --- Error classes ---

class PrimevalError extends Error {
  constructor(name: string, message: string) {
    super(message);
    this.name = name;
  }
}

export class ValidationError extends PrimevalError {
  declare name: "ValidationError";
  constructor(message: string) {
    super("ValidationError", message);
  }
}

export class NotFoundError extends PrimevalError {
  declare name: "NotFoundError";
  constructor(message: string) {
    super("NotFoundError", message);
  }
}

export class AbortError extends PrimevalError {
  declare name: "AbortError";
  constructor(message: string) {
    super("AbortError", message);
  }
}

// --- Internal types ---

const VALID_SHAPES: readonly Shape[] = [
  "any",
  "triangle",
  "rectangle",
  "ellipse",
  "circle",
  "rotated-rectangle",
  "quadratic",
  "rotated-ellipse",
  "polygon",
];

const VALID_OUTPUTS: readonly OutputFormat[] = ["svg", "png", "jpg", "gif"];

interface NativeResult {
  format: string;
  data: Buffer;
  mimeType: string;
  width: number;
  height: number;
}

interface NativeHandle {
  promise: Promise<NativeResult>;
  taskId: number;
}

interface NativeAddon {
  startApproximate(request: unknown): NativeHandle;
  cancelApproximate(taskId: number): void;
}

interface NormalizedRender {
  count: number;
  shape: Shape;
  alpha: number | "auto";
  repeat: number;
  seed: number | undefined;
  background: string;
  resizeInput: number;
  outputSize: number;
}

interface NormalizedInput {
  kind: "path" | "bytes";
  path?: string;
  data?: Buffer;
}

interface NormalizedRequest {
  input: NormalizedInput;
  output: OutputFormat;
  render: NormalizedRender;
  execution: {
    onProgress?: (info: ProgressInfo) => void;
    signal?: AbortSignal;
  };
}

// --- Normalization ---

function normalizeInput(input: unknown): NormalizedInput {
  if (!input || typeof input !== "object") {
    throw new ValidationError("input is required");
  }
  const inp = input as Record<string, unknown>;

  if (inp.kind === "path") {
    if (typeof inp.path !== "string" || inp.path.length === 0) {
      throw new ValidationError("path input requires a path");
    }
    return { kind: "path", path: inp.path };
  }

  if (inp.kind === "bytes") {
    if (Buffer.isBuffer(inp.data)) {
      return { kind: "bytes", data: inp.data };
    }
    if (inp.data instanceof Uint8Array) {
      return { kind: "bytes", data: Buffer.from(inp.data) };
    }
    throw new ValidationError("bytes input requires data");
  }

  throw new ValidationError(`unknown input kind: ${String(inp.kind)}`);
}

function normalizeRender(render?: Record<string, unknown>): NormalizedRender {
  const r = render ?? {};
  const count = (r.count as number | undefined) ?? 100;
  const shape = (r.shape as Shape | undefined) ?? "any";
  const alpha = (r.alpha as number | "auto" | undefined) ?? 128;
  const repeat = (r.repeat as number | undefined) ?? 0;
  const background = (r.background as string | undefined) ?? "auto";
  const resizeInput = (r.resizeInput as number | undefined) ?? 256;
  const outputSize = (r.outputSize as number | undefined) ?? 1024;
  const seed = r.seed as number | undefined;

  if (!Number.isInteger(count) || count < 1) {
    throw new ValidationError("count must be at least 1");
  }
  if (!(VALID_SHAPES as readonly string[]).includes(shape)) {
    throw new ValidationError(`unknown shape: ${shape}`);
  }
  if (alpha !== "auto" && (!Number.isInteger(alpha) || alpha < 1 || alpha > 255)) {
    throw new ValidationError("alpha must be 1..255 or auto");
  }
  if (!Number.isInteger(repeat) || repeat < 0) {
    throw new ValidationError("repeat must be at least 0");
  }
  if (!Number.isInteger(resizeInput) || resizeInput < 1) {
    throw new ValidationError("resizeInput must be at least 1");
  }
  if (!Number.isInteger(outputSize) || outputSize < 1) {
    throw new ValidationError("outputSize must be at least 1");
  }

  return { count, shape, alpha, repeat, seed, background, resizeInput, outputSize };
}

function normalizeRequest(request: unknown): NormalizedRequest {
  if (!request || typeof request !== "object") {
    throw new ValidationError("request is required");
  }
  const req = request as Record<string, unknown>;

  const input = normalizeInput(req.input);
  const output = req.output as string;
  if (!(VALID_OUTPUTS as readonly string[]).includes(output)) {
    throw new ValidationError(`unknown output format: ${String(output)}`);
  }

  const execution = (req.execution ?? {}) as Record<string, unknown>;

  return {
    input,
    output: output as OutputFormat,
    render: normalizeRender(req.render as Record<string, unknown> | undefined),
    execution: {
      onProgress: execution.onProgress as ((info: ProgressInfo) => void) | undefined,
      signal: execution.signal as AbortSignal | undefined,
    },
  };
}

// --- Native addon loading ---

function getPlatformPackageName(): string {
  switch (process.platform) {
    case "darwin":
      return `@aleburato/primeval-darwin-${process.arch}`;
    case "win32":
      return `@aleburato/primeval-win32-${process.arch}-msvc`;
    case "linux":
      if (process.arch !== "x64" && process.arch !== "arm64") {
        throw new ValidationError(`unsupported linux architecture: ${process.arch}`);
      }
      return `@aleburato/primeval-linux-${process.arch}-gnu`;
    default:
      throw new ValidationError(`unsupported platform: ${process.platform}`);
  }
}

let _native: NativeAddon | null = null;

function loadNative(): NativeAddon {
  if (_native) return _native;
  const packageName = getPlatformPackageName();
  try {
    _native = require(packageName) as NativeAddon;
  } catch (error) {
    try {
      _native = require("../primeval-node.node") as NativeAddon;
    } catch (fallbackError) {
      throw new Error(
        `could not load native addon ${packageName}: ${error instanceof Error ? error.message : String(error)}; local fallback also failed: ${fallbackError instanceof Error ? fallbackError.message : String(fallbackError)}`,
      );
    }
  }
  return _native;
}

// --- Error mapping ---

function mapNativeError(error: unknown): Error {
  const message = error instanceof Error ? error.message : String(error);
  const nameMatch = message.match(/^\[([^\]]+)\]\s*(.*)$/);
  if (!nameMatch) {
    return new Error(message);
  }

  const [, name, detail] = nameMatch;
  switch (name) {
    case "ValidationError":
      return new ValidationError(detail!);
    case "NotFoundError":
      return new NotFoundError(detail!);
    case "AbortError":
      return new AbortError(detail!);
    default:
      return new Error(detail);
  }
}

// --- Core API ---

function startApproximate(
  request: ApproximateRequest,
): { promise: Promise<ApproximateResult>; cancel: () => void } {
  const normalized = normalizeRequest(request);
  const native = loadNative();
  const onProgress =
    normalized.execution.onProgress &&
    ((_: unknown, info: ProgressInfo | null): void => {
      if (info) {
        normalized.execution.onProgress?.(info);
      }
    });
  const handle = native.startApproximate({
    input: normalized.input,
    output: normalized.output,
    render: {
      count: normalized.render.count,
      shape: normalized.render.shape,
      alpha: normalized.render.alpha === "auto" ? null : normalized.render.alpha,
      repeat: normalized.render.repeat,
      seed: normalized.render.seed ?? null,
      background: normalized.render.background,
      resizeInput: normalized.render.resizeInput,
      outputSize: normalized.render.outputSize,
    },
    execution: onProgress ? { onProgress } : undefined,
  });

  const cancel = (): void => native.cancelApproximate(handle.taskId);
  const signal = normalized.execution.signal;
  let onAbort: (() => void) | undefined;
  if (signal) {
    onAbort = () => cancel();
    if (signal.aborted) {
      onAbort();
    } else {
      signal.addEventListener("abort", onAbort, { once: true });
    }
  }

  const promise = handle.promise
    .then((result): ApproximateResult => {
      if (result.format === "svg") {
        return {
          format: "svg",
          data: Buffer.isBuffer(result.data)
            ? result.data.toString("utf8")
            : String(result.data),
          mimeType: result.mimeType as "image/svg+xml",
          width: result.width,
          height: result.height,
        };
      }

      return {
        format: result.format as "png" | "jpg" | "gif",
        data: Buffer.isBuffer(result.data) ? result.data : Buffer.from(result.data),
        mimeType: result.mimeType as "image/png" | "image/jpeg" | "image/gif",
        width: result.width,
        height: result.height,
      };
    })
    .catch((error: unknown) => {
      throw mapNativeError(error);
    })
    .finally(() => {
      if (signal && onAbort) signal.removeEventListener("abort", onAbort);
    });

  return { promise, cancel };
}

export function approximate(request: ApproximateRequest): Promise<ApproximateResult> {
  return startApproximate(request).promise;
}

export function toDataUri(result: ApproximateResult): string {
  if (!result || typeof result !== "object") {
    throw new ValidationError("result is required");
  }

  const base64 =
    result.format === "svg"
      ? Buffer.from(
          typeof result.data === "string" ? result.data : String(result.data),
          "utf8",
        ).toString("base64")
      : Buffer.from(result.data).toString("base64");

  return `data:${result.mimeType};base64,${base64}`;
}
