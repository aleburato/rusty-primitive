#!/usr/bin/env python3
"""
Benchmark script that runs the primeval algorithm with different shape types,
collects performance metrics, and generates an HTML report.

Optionally compares two binaries side-by-side.
"""

import argparse
import json
import math
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional
from datetime import datetime
from PIL import Image

DEFAULT_BIN_A = Path("./target/release/primeval-cli")
DEFAULT_BUILD_CMD = [
    "cargo",
    "build",
    "--release",
    "--manifest-path",
    "Cargo.toml",
    "--bin",
    "primeval-cli",
]
OUTPUT_DIR = Path("output")


@dataclass(frozen=True)
class ShapeSpec:
    go_mode: int
    display_name: str
    rust_name: str


@dataclass(frozen=True)
class BenchmarkResult:
    label: str
    shape_type: int
    shape_name: str
    steps: int
    seed: int
    elapsed_time: float
    file_size: int
    svg_size_kb: Optional[float]
    mae_rgb: float
    rmse_rgb: float
    output_file: str
    svg_output_file: str
    timestamp: str

    def to_dict(self):
        return asdict(self)


SHAPE_SPECS = (
    ShapeSpec(0, "Mixed", "any"),
    ShapeSpec(1, "Triangle", "triangle"),
    ShapeSpec(2, "Rectangle", "rectangle"),
    ShapeSpec(3, "Ellipse", "ellipse"),
    ShapeSpec(4, "Circle", "circle"),
    ShapeSpec(5, "RotatedRectangle", "rotated-rectangle"),
    ShapeSpec(6, "Quadratic", "quadratic"),
    ShapeSpec(7, "RotatedEllipse", "rotated-ellipse"),
    ShapeSpec(8, "Polygon", "polygon"),
)
SHAPE_BY_NAME = {spec.display_name: spec for spec in SHAPE_SPECS}
SHAPES = {spec.go_mode: spec.display_name for spec in SHAPE_SPECS}
RUST_SHAPES = {spec.display_name: spec.rust_name for spec in SHAPE_SPECS}
SHAPE_GROUPS = {
    "all": [spec.display_name for spec in SHAPE_SPECS],
    "mixed": ["Mixed"],
    "direct": [
        "Triangle",
        "Rectangle",
        "Ellipse",
        "Circle",
        "RotatedRectangle",
    ],
    "path": [
        "Quadratic",
        "RotatedEllipse",
        "Polygon",
    ],
}

try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_LANCZOS = Image.LANCZOS

# Plain strings (not f-strings) so { } are literal and need no escaping.

_COMPARISON_CSS = """
    :root {
        --bg:             #0d0d0b;
        --surface:        #161613;
        --surface-2:      #1d1d1a;
        --border:         #2c2b27;
        --border-subtle:  #1f1f1c;
        --text:           #ede8de;
        --text-2:         #8a8680;
        --text-3:         #4a4844;
        --green:          #5db878;
        --red:            #c96b6b;
        --amber:          #c4904a;
        --blue:           #5b9bd5;
        --muted:          #5a5a62;
        --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
        --font-mono: ui-monospace, 'SF Mono', Menlo, 'Cascadia Code', monospace;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
        font-family: var(--font-sans);
        background: var(--bg);
        color: var(--text);
        min-height: 100vh;
        -webkit-font-smoothing: antialiased;
    }

    /* ── Header ─────────────────────────────────────────── */
    .header {
        padding: 56px 60px 44px;
        border-bottom: 1px solid var(--border);
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        gap: 40px;
    }
    .header-eyebrow {
        font-family: var(--font-mono);
        font-size: .72em;
        color: var(--text-3);
        letter-spacing: .14em;
        text-transform: uppercase;
        margin-bottom: 14px;
    }
    .header-title {
        font-family: var(--font-sans);
        font-size: 3em;
        font-weight: 800;
        line-height: .92;
        letter-spacing: -.03em;
        color: var(--text);
    }
    .header-title .sep {
        color: var(--text-3);
        font-weight: 400;
        font-size: .5em;
        vertical-align: middle;
        padding: 0 .2em;
    }
    .header-right { display: flex; align-items: center; gap: 20px; flex-shrink: 0; }
    .source-thumb {
        width: 64px;
        height: 64px;
        object-fit: cover;
        border-radius: 4px;
        opacity: .55;
        flex-shrink: 0;
    }
    .header-meta {
        font-family: var(--font-mono);
        font-size: .75em;
        color: var(--text-3);
        text-align: right;
        line-height: 2;
        white-space: nowrap;
    }

    /* ── Stats strip ─────────────────────────────────────── */
    .stats {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        border-bottom: 1px solid var(--border);
    }
    .stat {
        padding: 28px 40px;
        border-right: 1px solid var(--border);
    }
    .stat:last-child { border-right: none; }
    .stat-label {
        font-family: var(--font-mono);
        font-size: .68em;
        color: var(--text-3);
        letter-spacing: .12em;
        text-transform: uppercase;
        margin-bottom: 8px;
    }
    .stat-value {
        font-family: var(--font-sans);
        font-size: 1.9em;
        font-weight: 700;
        letter-spacing: -.025em;
        line-height: 1;
        color: var(--text);
    }
    .verdict-faster { color: var(--green); }
    .verdict-slower { color: var(--red);   }
    .verdict-equal  { color: var(--muted); }

    /* ── Content ─────────────────────────────────────────── */
    .content { padding: 48px 60px; }
    .section-head {
        display: flex;
        align-items: center;
        gap: 16px;
        margin-bottom: 28px;
    }
    .section-title {
        font-family: var(--font-mono);
        font-size: .68em;
        font-weight: 500;
        letter-spacing: .14em;
        text-transform: uppercase;
        color: var(--text-3);
        white-space: nowrap;
    }
    .section-rule {
        flex: 1;
        height: 1px;
        background: var(--border);
    }

    /* ── Table ───────────────────────────────────────────── */
    table { width: 100%; border-collapse: collapse; margin-bottom: 56px; }
    thead { border-bottom: 1px solid var(--border); }
    th {
        font-family: var(--font-mono);
        font-size: .68em;
        font-weight: 500;
        letter-spacing: .1em;
        text-transform: uppercase;
        color: var(--text-3);
        padding: 0 16px 14px 0;
        text-align: left;
        border-bottom: none;
        white-space: nowrap;
    }
    th.r { text-align: right; padding-right: 0; padding-left: 32px; }
    th.c { text-align: center; padding-left: 32px; }
    th.group-hd {
        text-align: left;
        padding-bottom: 6px;
        border-bottom: none;
        color: var(--text-2);
        letter-spacing: .06em;
        padding-left: 32px;
    }
    th.sub-hd {
        font-size: .6em;
        color: var(--text-3);
        padding-top: 2px;
    }
    td {
        padding: 16px 16px 16px 0;
        border-bottom: 1px solid var(--border-subtle);
        vertical-align: middle;
    }
    td.r { text-align: right; padding-right: 0; padding-left: 32px; }
    td.c { text-align: center; padding-left: 32px; }
    tr:last-child td { border-bottom: none; }
    .col-shape { font-weight: 600; font-size: .95em; color: var(--text); white-space: nowrap; }
    .col-time  { font-family: var(--font-mono); font-size: .85em; color: var(--text-2); white-space: nowrap; }

    /* ── Badges ──────────────────────────────────────────── */
    .badge {
        display: inline-block;
        font-family: var(--font-mono);
        font-size: .72em;
        font-weight: 500;
        padding: 4px 9px;
        border-radius: 3px;
        letter-spacing: .04em;
        white-space: nowrap;
    }
    /* Speed badges: green=faster  muted=~equal  red=slower */
    .badge-green { background: rgba(93,184,120,.1);  color: var(--green); }
    .badge-red   { background: rgba(201,107,107,.1); color: var(--red);   }
    /* Quality badges: blue=lower-error  red=higher-error */
    .badge-blue  { background: rgba(91,155,213,.1);  color: var(--blue); }
    .badge-red-q { background: rgba(201,107,107,.1); color: var(--red); }
    /* Shared muted badge for ~equal in both columns */
    .badge-muted { background: rgba(90,90,98,.12);   color: var(--muted); }

    /* ── Gallery ─────────────────────────────────────────── */
    .gallery-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
        gap: 2px;
        background: var(--border-subtle);
        border: 1px solid var(--border);
    }
    .card { background: var(--surface); overflow: hidden; }
    .card-header {
        padding: 14px 16px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        border-bottom: 1px solid var(--border-subtle);
    }
    .card-name {
        font-family: var(--font-sans);
        font-size: .88em;
        font-weight: 700;
        color: var(--text);
        letter-spacing: -.01em;
    }
    .card-body { padding: 6px; }
    .img-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
    figure img {
        width: 100%;
        aspect-ratio: 1;
        object-fit: contain;
        display: block;
        background: var(--surface-2);
        transition: opacity .15s;
    }
    figcaption {
        font-family: var(--font-mono);
        font-size: .65em;
        color: var(--text-3);
        padding: 5px 2px 2px;
        text-align: center;
        letter-spacing: .04em;
        transition: color .15s;
    }
    .clickable-pair { cursor: zoom-in; }
    .clickable-pair:hover img { opacity: .72; }
    .clickable-pair:hover figcaption { color: var(--text-2); }

    /* ── Footer ──────────────────────────────────────────── */
    .footer {
        padding: 20px 60px;
        border-top: 1px solid var(--border);
        font-family: var(--font-mono);
        font-size: .68em;
        color: var(--text-3);
        display: flex;
        justify-content: space-between;
        letter-spacing: .04em;
    }

    /* ── Overlay ─────────────────────────────────────────── */
    .overlay { position: fixed; inset: 0; z-index: 1000; display: flex; align-items: center; justify-content: center; }
    .overlay[hidden] { display: none; }
    .overlay-bg { position: absolute; inset: 0; background: rgba(0,0,0,.93); cursor: pointer; backdrop-filter: blur(3px); }
    .overlay-box { position: relative; z-index: 1; display: flex; flex-direction: column; align-items: center; gap: 20px; padding: 36px; max-width: 90vw; }
    .overlay-header { display: flex; align-items: center; justify-content: space-between; width: 100%; }
    .overlay-shape { font-family: var(--font-sans); font-size: 1.3em; font-weight: 700; color: var(--text); letter-spacing: -.02em; }
    .overlay-close { background: none; border: 1px solid var(--border); color: var(--text-2); width: 30px; height: 30px; border-radius: 5px; cursor: pointer; font-size: 1em; display: flex; align-items: center; justify-content: center; transition: border-color .15s, color .15s; flex-shrink: 0; }
    .overlay-close:hover { border-color: var(--text-2); color: var(--text); }
    .overlay-img-wrap { display: flex; align-items: center; justify-content: center; }
    .overlay-img-wrap img { max-width: 80vw; max-height: 65vh; object-fit: contain; display: block; }
    .overlay-controls { display: grid; grid-template-columns: 1fr 1fr; gap: 2px; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 3px; }
    .toggle-btn { font-family: var(--font-mono); font-size: .78em; font-weight: 500; padding: 7px 22px; border: none; border-radius: 4px; cursor: pointer; background: transparent; color: var(--text-2); transition: background .12s, color .12s; letter-spacing: .05em; text-align: center; }
    .toggle-btn.active { background: var(--surface-2); color: var(--text); }
    .toggle-btn:hover:not(.active) { color: var(--text); }
    .toggle-btn-orig { grid-column: 1 / -1; }
    .overlay-hint { font-family: var(--font-mono); font-size: .65em; color: var(--text-3); letter-spacing: .08em; }
"""

_OVERLAY_HTML = """
<div id="cmp-overlay" class="overlay" hidden>
    <div id="cmp-overlay-bg" class="overlay-bg"></div>
    <div class="overlay-box">
        <div class="overlay-header">
            <span id="cmp-shape" class="overlay-shape"></span>
            <button id="cmp-close" class="overlay-close" aria-label="Close">&times;</button>
        </div>
        <div class="overlay-img-wrap">
            <img id="cmp-img" src="" alt="comparison" />
        </div>
        <div class="overlay-controls">
            <button id="cmp-btn-a" class="toggle-btn active">A</button>
            <button id="cmp-btn-b" class="toggle-btn">B</button>
            <button id="cmp-btn-orig" class="toggle-btn toggle-btn-orig">original</button>
        </div>
        <p class="overlay-hint">&#8592; A &nbsp;&#183;&nbsp; Space to toggle &nbsp;&#183;&nbsp; B &#8594; &nbsp;&#183;&nbsp; &#8595; original &nbsp;&#183;&nbsp; &#8593; back &nbsp;&#183;&nbsp; Esc to close</p>
    </div>
</div>
"""

_OVERLAY_JS = """
(function () {
  var overlay  = document.getElementById('cmp-overlay');
  var oImg     = document.getElementById('cmp-img');
  var oShape   = document.getElementById('cmp-shape');
  var btnA     = document.getElementById('cmp-btn-a');
  var btnB     = document.getElementById('cmp-btn-b');
  var btnOrig  = document.getElementById('cmp-btn-orig');
  var closeBtn = document.getElementById('cmp-close');
  var srcA, srcB, srcOrig, active, lastVariation;

  function select(which) {
    active = which;
    if (which !== 'orig') lastVariation = which;
    oImg.src = which === 'a' ? srcA : which === 'b' ? srcB : srcOrig;
    btnA.classList.toggle('active', which === 'a');
    btnB.classList.toggle('active', which === 'b');
    btnOrig.classList.toggle('active', which === 'orig');
  }

  function openOverlay(el) {
    srcA    = el.getAttribute('data-src-a');
    srcB    = el.getAttribute('data-src-b');
    srcOrig = el.getAttribute('data-src-orig');
    oShape.textContent = el.getAttribute('data-shape');
    btnA.textContent = el.getAttribute('data-label-a');
    btnB.textContent = el.getAttribute('data-label-b');
    lastVariation = el.getAttribute('data-start') || 'a';
    select(lastVariation);
    overlay.hidden = false;
    document.body.style.overflow = 'hidden';
  }

  function closeOverlay() {
    overlay.hidden = true;
    document.body.style.overflow = '';
  }

  btnA.addEventListener('click', function () { select('a'); });
  btnB.addEventListener('click', function () { select('b'); });
  btnOrig.addEventListener('click', function () { select('orig'); });
  closeBtn.addEventListener('click', closeOverlay);
  document.getElementById('cmp-overlay-bg').addEventListener('click', closeOverlay);

  document.addEventListener('keydown', function (e) {
    if (overlay.hidden) return;
    if (e.key === 'Escape') { closeOverlay(); return; }
    if (e.key === 'ArrowLeft'  || e.key === 'a' || e.key === 'A' || e.key === '1') select('a');
    if (e.key === 'ArrowRight' || e.key === 'b' || e.key === 'B' || e.key === '2') select('b');
    if (e.key === 'ArrowDown'  || e.key === 'o' || e.key === 'O') { e.preventDefault(); select('orig'); }
    if (e.key === 'ArrowUp') { e.preventDefault(); select(lastVariation); }
    if (e.key === ' ') { e.preventDefault(); select(active === 'orig' ? lastVariation : active === 'a' ? 'b' : 'a'); }
  });

  document.querySelectorAll('.clickable-pair').forEach(function (fig) {
    fig.addEventListener('click', function () { openOverlay(fig); });
  });
}());
"""


def parse_args():
    p = argparse.ArgumentParser(description="Benchmark primeval shape types")
    p.add_argument(
        "--bin-a",
        default=str(DEFAULT_BIN_A),
        help="Path to first binary (A)",
    )
    p.add_argument("--bin-b", default=None, help="Path to second binary (B, enables comparison mode)")
    p.add_argument("--label-a", default=None, help="Label for binary A (default: basename of --bin-a)")
    p.add_argument("--label-b", default=None, help="Label for binary B (default: basename of --bin-b)")
    p.add_argument(
        "--input",
        default="docs/readme/originals/americangothic.jpg",
        help="Input image path",
    )
    p.add_argument("--steps", type=int, default=250, help="Number of primitives per run")
    p.add_argument("--seed", type=int, default=42, help="Random seed")
    p.add_argument(
        "--shapes",
        default="all",
        help="Comma-separated shape names or groups: all, mixed, direct, path",
    )
    p.add_argument("--no-build", action="store_true", help="Skip building binary A")
    p.add_argument(
        "--from-json",
        metavar="PATH",
        default=None,
        help="Regenerate HTML from an existing benchmark JSON file without re-running benchmarks",
    )
    p.add_argument(
        "--swap",
        action="store_true",
        help="Swap the A/B label order when used with --from-json (e.g. render 'rust vs go' from a 'go vs rust' JSON)",
    )
    return p.parse_args()


def parse_shape_selection(value):
    """Expand a comma-separated shape selection into benchmark shape tuples."""
    selected = []
    seen = set()
    aliases = {}
    for spec in SHAPE_SPECS:
        aliases[spec.display_name.lower()] = spec.display_name
        aliases[spec.display_name.replace(" ", "").lower()] = spec.display_name
        aliases[spec.display_name.replace(" ", "-").lower()] = spec.display_name
        aliases[spec.rust_name.lower()] = spec.display_name

    for item in value.split(","):
        token = item.strip().lower()
        if not token:
            continue
        if token in SHAPE_GROUPS:
            names = SHAPE_GROUPS[token]
        elif token in aliases:
            names = [aliases[token]]
        else:
            valid = ", ".join(sorted([*SHAPE_GROUPS.keys(), *aliases.keys()]))
            raise SystemExit(f"unknown shape selection '{item}'. Valid values: {valid}")

        for name in names:
            if name in seen:
                continue
            seen.add(name)
            spec = SHAPE_BY_NAME[name]
            selected.append((spec.go_mode, spec.display_name))

    if not selected:
        raise SystemExit("no shapes selected")

    return selected


def format_duration(seconds):
    """Format a duration using compact human-readable units."""
    if seconds < 1:
        return f"{int(round(seconds * 1000))}ms"
    if seconds < 60:
        return f"{seconds:.1f}s" if seconds < 10 else f"{round(seconds):.0f}s"

    total_seconds = int(round(seconds))
    minutes, secs = divmod(total_seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"

    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def format_metric(value):
    """Format an image error metric on the 0..255 channel scale."""
    return f"{value:.2f}"


def format_artifact_size(value):
    """Format a rounded artifact size in KB/MB."""
    if value is None:
        return "—"
    if value >= 1024:
        return f"{value / 1024:.1f} MB"
    return f"{value:.1f} KB"


def command_output(cmd):
    """Return combined stdout/stderr for a best-effort help command."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError:
        return ""
    return f"{result.stdout}\n{result.stderr}"


@lru_cache(maxsize=None)
def detect_cli_style(binary):
    """Detect whether a binary uses the upstream Go flags or the Rust subcommand CLI."""
    run_help = command_output([binary, "run", "--help"])
    if "--count" in run_help and "--shape" in run_help and "--output" in run_help:
        return "rust"

    root_help = command_output([binary, "--help"])
    if "Commands:" in root_help and "run" in root_help:
        return "rust"

    return "go"


@lru_cache(maxsize=None)
def supports_seed_flag(binary):
    """Return True if the binary lists -seed in its usage text."""
    # Passing -help forces Go's flag package to print usage and exit 2.
    # We inspect that output rather than passing -seed directly (which would
    # show up as an error message and give a false positive).
    try:
        result = subprocess.run([binary, "-help"], capture_output=True, text=True, check=False)
    except OSError:
        return False
    return "-seed" in result.stderr or "-seed" in result.stdout


def build_command(binary, cli_style, shape_type, shape_name, input_image, output_file, steps, seed):
    """Build the correct invocation for either the Go or Rust CLI."""
    if cli_style == "rust":
        emit = output_file.suffix.lstrip(".").lower() or "png"
        return [
            binary,
            "run",
            str(input_image),
            "--output",
            str(output_file),
            "--emit",
            emit,
            "--count",
            str(steps),
            "--shape",
            RUST_SHAPES[shape_name],
            "--seed",
            str(seed),
            "--progress",
            "off",
        ]

    cmd = [
        binary,
        "-i", str(input_image),
        "-o", str(output_file),
        "-n", str(steps),
        "-m", str(shape_type),
    ]
    if supports_seed_flag(binary):
        cmd += ["-seed", str(seed)]
    return cmd


def measure_svg_size(binary, cli_style, shape_type, shape_name, input_image, steps, seed, output_file):
    """Generate an SVG sidecar outside the timed benchmark path and return its rounded size in KB."""
    cmd = build_command(binary, cli_style, shape_type, shape_name, input_image, output_file, steps, seed)
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            f"  [warn] {shape_name} svg export failed for {Path(binary).name}: {result.stderr.strip()}",
            flush=True,
        )
        return None
    return round(output_file.stat().st_size / 1024, 1)


def compute_image_metrics(input_image, output_file, reference_cache):
    """Compute RGB MAE and RMSE against the input resized to the output dimensions."""
    with Image.open(output_file) as rendered_image:
        rendered = rendered_image.convert("RGB")
        cache_key = (str(input_image), rendered.size)
        if cache_key not in reference_cache:
            with Image.open(input_image) as source_image:
                source = source_image.convert("RGB")
                reference_cache[cache_key] = source.resize(rendered.size, RESAMPLE_LANCZOS)
        reference = reference_cache[cache_key]

        rendered_bytes = rendered.tobytes()
        reference_bytes = reference.tobytes()

    count = len(rendered_bytes)
    abs_total = 0
    sq_total = 0
    for expected, actual in zip(reference_bytes, rendered_bytes):
        delta = actual - expected
        abs_total += abs(delta)
        sq_total += delta * delta

    mae = abs_total / count
    rmse = math.sqrt(sq_total / count)
    return {
        "mae_rgb": mae,
        "rmse_rgb": rmse,
    }


def run_benchmark(binary, cli_style, shape_type, shape_name, input_image, steps, seed, label, reference_cache):
    """Run a single benchmark with the specified shape type and binary."""
    bin_dir = OUTPUT_DIR / label / shape_name
    bin_dir.mkdir(parents=True, exist_ok=True)

    output_file = bin_dir / f"{shape_name}_{steps}.png"
    svg_output_file = bin_dir / f"{shape_name}_{steps}.svg"

    cmd = build_command(binary, cli_style, shape_type, shape_name, input_image, output_file, steps, seed)

    print(f"  [{label}] {shape_name} — starting", flush=True)

    start_time = time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

    tick = 5  # print a heartbeat every N seconds
    next_tick = tick
    while proc.poll() is None:
        time.sleep(0.5)
        elapsed = time.perf_counter() - start_time
        if elapsed >= next_tick:
            print(f"  [{label}] {shape_name} — {elapsed:.0f}s elapsed…", flush=True)
            next_tick += tick

    stderr_out = proc.stderr.read()
    elapsed_time = time.perf_counter() - start_time

    if proc.returncode != 0:
        print(f"  [{label}] {shape_name} — FAILED ({elapsed_time:.1f}s)")
        print(stderr_out.strip())
        return None

    file_size = output_file.stat().st_size
    svg_size_kb = measure_svg_size(
        binary,
        cli_style,
        shape_type,
        shape_name,
        input_image,
        steps,
        seed,
        svg_output_file,
    )
    metrics = compute_image_metrics(input_image, output_file, reference_cache)
    print(
        f"  [{label}] {shape_name} — done in {elapsed_time:.2f}s "
        f"(rmse {metrics['rmse_rgb']:.2f}, mae {metrics['mae_rgb']:.2f})",
        flush=True,
    )

    return BenchmarkResult(
        label=label,
        shape_type=shape_type,
        shape_name=shape_name,
        steps=steps,
        seed=seed,
        elapsed_time=elapsed_time,
        file_size=file_size,
        svg_size_kb=svg_size_kb,
        mae_rgb=metrics["mae_rgb"],
        rmse_rgb=metrics["rmse_rgb"],
        output_file=str(output_file),
        svg_output_file=str(svg_output_file),
        timestamp=datetime.now().isoformat(),
    ).to_dict()


def run_all(binary, label, input_image, steps, seed, selected_shapes):
    cli_style = detect_cli_style(binary)
    results = []
    reference_cache = {}
    for shape_type, shape_name in selected_shapes:
        r = run_benchmark(binary, cli_style, shape_type, shape_name, input_image, steps, seed, label, reference_cache)
        if r:
            results.append(r)
    return results


def _badge_class(ratio):
    """CSS badge class for a speedup ratio (A/B; <1 means A is faster)."""
    if ratio < 0.95:
        return "badge-green"
    if ratio > 1.05:
        return "badge-red"
    return "badge-muted"


def _quality_badge_class(ratio):
    """CSS badge class for a quality ratio (A/B RMSE; <1 means A has lower error)."""
    if ratio < 0.95:
        return "badge-blue"
    if ratio > 1.05:
        return "badge-red-q"
    return "badge-muted"


def _verdict_class(ratio):
    """CSS class for the overall verdict stat value."""
    if ratio < 0.95:
        return "verdict-faster"
    if ratio > 1.05:
        return "verdict-slower"
    return "verdict-equal"


def _speed_delta_text(ratio):
    if ratio < 0.99:
        return f"{(1 - ratio) * 100:.1f}% faster"
    if ratio > 1.01:
        return f"{(ratio - 1) * 100:.1f}% slower"
    return "similar"


def _speed_multiple_text(ratio):
    if ratio <= 0:
        return "similar"
    if ratio < 0.99:
        return f"{1 / ratio:.2f}x"
    if ratio > 1.01:
        return f"{ratio:.2f}x"
    return "similar"


def _overall_speed_text(ratio):
    multiple = _speed_multiple_text(ratio)
    delta = _speed_delta_text(ratio)
    if multiple == "similar":
        return multiple
    return f"{delta} ({multiple})"


def _quality_delta_text(ratio):
    if ratio < 0.99:
        return f"{(1 - ratio) * 100:.1f}% lower error"
    if ratio > 1.01:
        return f"{(ratio - 1) * 100:.1f}% higher error"
    return "similar"


def _figure(src, alt, caption, src_a, src_b, src_orig, label_a, label_b, shape, start):
    """Build a clickable <figure> for the comparison gallery."""
    return (
        f'<figure class="clickable-pair"'
        f' data-src-a="{src_a}" data-src-b="{src_b}" data-src-orig="{src_orig}"'
        f' data-label-a="{label_a}" data-label-b="{label_b}"'
        f' data-shape="{shape}" data-start="{start}"'
        f' title="Click to compare">'
        f'<img src="{src}" alt="{alt}" loading="lazy" />'
        f'<figcaption>{caption}</figcaption>'
        f'</figure>'
    )


def generate_comparison_html(results_a, results_b, label_a, label_b, args):
    by_shape_a = {r["shape_name"]: r for r in results_a}
    by_shape_b = {r["shape_name"]: r for r in results_b}
    all_shapes = [n for n in SHAPES.values() if n in by_shape_a and n in by_shape_b]

    rows = []
    for shape_name in all_shapes:
        ra = by_shape_a[shape_name]
        rb = by_shape_b[shape_name]
        ta = ra["elapsed_time"]
        tb = rb["elapsed_time"]
        speed_ratio = ta / tb
        speed_badge = _badge_class(speed_ratio)
        qa = ra["rmse_rgb"]
        qb = rb["rmse_rgb"]
        quality_ratio = qa / qb if qb else 1.0
        quality_badge = _quality_badge_class(quality_ratio)

        rows.append(f"""
        <tr>
            <td class="col-shape">{shape_name}</td>
            <td class="col-time r">{format_duration(ta)}</td>
            <td class="col-time r">{format_duration(tb)}</td>
            <td class="col-time r">{format_metric(qa)}</td>
            <td class="col-time r">{format_metric(qb)}</td>
            <td class="col-time r">{format_artifact_size(ra.get("svg_size_kb"))}</td>
            <td class="col-time r">{format_artifact_size(rb.get("svg_size_kb"))}</td>
            <td class="c"><span class="badge {speed_badge}">{_overall_speed_text(speed_ratio)}</span></td>
            <td class="c"><span class="badge {quality_badge}">{_quality_delta_text(quality_ratio)}</span></td>
        </tr>""")

    orig_rel = Path(args.input).name  # copied to OUTPUT_DIR alongside the HTML
    input_size_kb = round(Path(args.input).stat().st_size / 1024, 1) if Path(args.input).exists() else None

    total_a = sum(r["elapsed_time"] for r in results_a)
    total_b = sum(r["elapsed_time"] for r in results_b)
    total_ratio = total_a / total_b if total_b else 1.0
    vc = _verdict_class(total_ratio)
    total_label = _overall_speed_text(total_ratio)
    avg_rmse_a = sum(r["rmse_rgb"] for r in results_a) / len(results_a)
    avg_rmse_b = sum(r["rmse_rgb"] for r in results_b) / len(results_b)
    quality_ratio = avg_rmse_a / avg_rmse_b if avg_rmse_b else 1.0
    quality_class = _verdict_class(quality_ratio)
    quality_label = _quality_delta_text(quality_ratio)

    gallery_cards = []
    for shape_name in all_shapes:
        ra = by_shape_a[shape_name]
        rb = by_shape_b[shape_name]
        ar_rel = Path(ra["output_file"]).relative_to(OUTPUT_DIR).as_posix()
        br_rel = Path(rb["output_file"]).relative_to(OUTPUT_DIR).as_posix()
        ratio = ra["elapsed_time"] / rb["elapsed_time"]
        bc = _badge_class(ratio)
        verdict = _overall_speed_text(ratio)

        fig_a = _figure(
            src=ar_rel, alt=f"{label_a} {shape_name}",
            caption=f"{label_a} — {format_duration(ra['elapsed_time'])} · svg {format_artifact_size(ra.get('svg_size_kb'))}",
            src_a=ar_rel, src_b=br_rel, src_orig=orig_rel,
            label_a=label_a, label_b=label_b,
            shape=shape_name, start="a",
        )
        fig_b = _figure(
            src=br_rel, alt=f"{label_b} {shape_name}",
            caption=f"{label_b} — {format_duration(rb['elapsed_time'])} · svg {format_artifact_size(rb.get('svg_size_kb'))}",
            src_a=ar_rel, src_b=br_rel, src_orig=orig_rel,
            label_a=label_a, label_b=label_b,
            shape=shape_name, start="b",
        )
        gallery_cards.append(f"""
        <article class="card">
            <div class="card-header">
                <span class="card-name">{shape_name}</span>
                <span class="badge {bc}">{verdict}</span>
            </div>
            <div class="card-body">
                <div class="img-pair">{fig_a}{fig_b}</div>
            </div>
        </article>""")

    input_name = orig_rel
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Benchmark — {label_a} vs {label_b}</title>
    <style>{_COMPARISON_CSS}</style>
</head>
<body>
{_OVERLAY_HTML}
<div class="header">
    <div class="header-left">
        <p class="header-eyebrow">Primeval Benchmark</p>
        <h1 class="header-title">{label_a}<span class="sep">×</span>{label_b}</h1>
    </div>
    <div class="header-right">
        <img class="source-thumb" src="{input_name}" alt="source" />
        <div class="header-meta">
            <span>{input_name}</span><br>
            <span>{format_artifact_size(input_size_kb)}</span><br>
            <span>{args.steps} steps &nbsp;·&nbsp; seed {args.seed}</span>
        </div>
    </div>
</div>
<div class="stats">
    <div class="stat">
        <p class="stat-label">{label_a}</p>
        <p class="stat-value">{format_duration(total_a)}</p>
    </div>
    <div class="stat">
        <p class="stat-label">{label_b}</p>
        <p class="stat-value">{format_duration(total_b)}</p>
    </div>
    <div class="stat">
        <p class="stat-label">Overall</p>
        <p class="stat-value {vc}">{total_label}</p>
    </div>
    <div class="stat">
        <p class="stat-label">Avg RMSE</p>
        <p class="stat-value {quality_class}">{quality_label}</p>
    </div>
    <div class="stat">
        <p class="stat-label">Shape Types</p>
        <p class="stat-value">{len(all_shapes)}</p>
    </div>
</div>
<div class="content">
    <div class="section-head">
        <span class="section-title">Timing</span>
        <div class="section-rule"></div>
    </div>
    <table>
        <thead>
            <tr>
                <th rowspan="2" class="group-hd" style="padding-left:0">Shape</th>
                <th colspan="2" class="group-hd" style="text-align:center">Time</th>
                <th colspan="2" class="group-hd" style="text-align:center">Quality (RMSE)</th>
                <th colspan="2" class="group-hd" style="text-align:center">SVG Size</th>
                <th rowspan="2" class="group-hd" style="text-align:center">Speed</th>
                <th rowspan="2" class="group-hd" style="text-align:center">Quality</th>
            </tr>
            <tr>
                <th class="r sub-hd">{label_a}</th>
                <th class="r sub-hd">{label_b}</th>
                <th class="r sub-hd">{label_a}</th>
                <th class="r sub-hd">{label_b}</th>
                <th class="r sub-hd">{label_a}</th>
                <th class="r sub-hd">{label_b}</th>
            </tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
    </table>
    <div class="section-head">
        <span class="section-title">Visual Output</span>
        <div class="section-rule"></div>
    </div>
    <div class="gallery-grid">
        {''.join(gallery_cards)}
    </div>
</div>
<div class="footer">
    <span>Generated {now}</span>
    <span>A: {args.bin_a} &nbsp;·&nbsp; B: {args.bin_b}</span>
</div>
<script>{_OVERLAY_JS}</script>
</body>
</html>"""


def generate_single_html(results, args):
    """HTML report for a single-binary run, styled to match the comparison theme."""
    sorted_results = sorted(results, key=lambda x: x["elapsed_time"])
    total_time = sum(r["elapsed_time"] for r in results)
    avg_rmse = sum(r["rmse_rgb"] for r in results) / len(results)
    avg_time = total_time / len(results)
    fastest = min(results, key=lambda x: x["elapsed_time"])
    slowest = max(results, key=lambda x: x["elapsed_time"])

    label = args.label_a or Path(args.bin_a).name
    input_name = Path(args.input).name
    input_size_kb = round(Path(args.input).stat().st_size / 1024, 1) if Path(args.input).exists() else None
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = []
    for result in sorted_results:
        shape_name = result["shape_name"]
        elapsed = result["elapsed_time"]
        ratio = elapsed / avg_time
        time_str = format_duration(elapsed)
        rmse_str = format_metric(result["rmse_rgb"])
        svg_size_str = format_artifact_size(result.get("svg_size_kb"))
        rows.append(
            f'\n        <tr>'
            f'\n            <td class="col-shape">{shape_name}</td>'
            f'\n            <td class="col-time r">{time_str}</td>'
            f'\n            <td class="col-time r">{rmse_str}</td>'
            f'\n            <td class="col-time r">{svg_size_str}</td>'
            f'\n            <td class="col-time r">{ratio:.2f}×</td>'
            f'\n        </tr>'
        )

    gallery_cards = []
    for result in results:
        shape_name = result["shape_name"]
        elapsed = result["elapsed_time"]
        relative_output = Path(result["output_file"]).relative_to(OUTPUT_DIR)
        src_path = relative_output.as_posix()
        time_str = format_duration(elapsed)
        rmse_str = format_metric(result["rmse_rgb"])
        svg_size_str = format_artifact_size(result.get("svg_size_kb"))
        gallery_cards.append(
            f'\n        <article class="card">'
            f'\n            <div class="card-header">'
            f'\n                <span class="card-name">{shape_name}</span>'
            f'\n                <span style="font-family:var(--font-mono);font-size:.72em;color:var(--text-3)">'
            f'{time_str} · rmse {rmse_str} · svg {svg_size_str}</span>'
            f'\n            </div>'
            f'\n            <div class="card-body">'
            f'\n                <figure>'
            f'\n                    <img src="{src_path}" alt="{shape_name}" loading="lazy" />'
            f'\n                </figure>'
            f'\n            </div>'
            f'\n        </article>'
        )

    rows_html = "".join(rows)
    cards_html = "".join(gallery_cards)
    css = _COMPARISON_CSS

    parts = [
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n',
        '    <meta charset="UTF-8">\n',
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n',
        f'    <title>Primeval Benchmark — {label}</title>\n',
        f'    <style>{css}</style>\n',
        '</head>\n<body>\n',
        '<div class="header">\n',
        '    <div class="header-left">\n',
        '        <p class="header-eyebrow">Primeval Benchmark</p>\n',
        f'        <h1 class="header-title">{label}</h1>\n',
        '    </div>\n',
        '    <div class="header-right">\n',
        f'        <img class="source-thumb" src="{input_name}" alt="source" />\n',
        '        <div class="header-meta">\n',
        f'            <span>{input_name}</span><br>\n',
        f'            <span>{format_artifact_size(input_size_kb)}</span><br>\n',
        f'            <span>{args.steps} steps · seed {args.seed}</span>\n',
        '        </div>\n    </div>\n</div>\n',
        '<div class="stats">\n',
        f'    <div class="stat"><p class="stat-label">Total Time</p><p class="stat-value">{format_duration(total_time)}</p></div>\n',
        f'    <div class="stat"><p class="stat-label">Avg Time</p><p class="stat-value">{format_duration(avg_time)}</p></div>\n',
        f'    <div class="stat"><p class="stat-label">Avg RMSE</p><p class="stat-value">{format_metric(avg_rmse)}</p></div>\n',
        f'    <div class="stat"><p class="stat-label">Shape Types</p><p class="stat-value">{len(results)}</p></div>\n',
        f'    <div class="stat"><p class="stat-label">Fastest</p><p class="stat-value">{fastest["shape_name"]}</p></div>\n',
        f'    <div class="stat"><p class="stat-label">Slowest</p><p class="stat-value">{slowest["shape_name"]}</p></div>\n',
        '</div>\n',
        '<div class="content">\n',
        '    <div class="section-head">\n        <span class="section-title">Results</span>\n        <div class="section-rule"></div>\n    </div>\n',
        '    <table>\n        <thead>\n            <tr>\n',
        '                <th class="group-hd" style="padding-left:0">Shape</th>\n',
        '                <th class="group-hd r">Time</th>\n',
        '                <th class="group-hd r">RMSE</th>\n',
        '                <th class="group-hd r">SVG</th>\n',
        '                <th class="group-hd r">vs avg</th>\n',
        f'            </tr>\n        </thead>\n        <tbody>{rows_html}</tbody>\n    </table>\n',
        '    <div class="section-head">\n        <span class="section-title">Visual Output</span>\n        <div class="section-rule"></div>\n    </div>\n',
        f'    <div class="gallery-grid">{cards_html}</div>\n',
        '</div>\n',
        f'<div class="footer">\n    <span>Generated {now}</span>\n    <span>{args.bin_a} · {args.steps} steps</span>\n</div>\n',
        '</body>\n</html>',
    ]
    return "".join(parts)


def serialize_report(results, args, label_a, label_b=None):
    return {
        "generated_at": datetime.now().isoformat(),
        "input_image": str(args.input),
        "steps": args.steps,
        "seed": args.seed,
        "label_a": label_a,
        "label_b": label_b,
        "bin_a": args.bin_a,
        "bin_b": args.bin_b,
        "results": results,
    }


def load_report(path):
    with open(path) as f:
        payload = json.load(f)

    if isinstance(payload, list):
        records = payload
        if not records:
            raise SystemExit("JSON file is empty")
        first = records[0]
        return {
            "generated_at": first.get("timestamp"),
            "input_image": None,
            "steps": first.get("steps"),
            "seed": first.get("seed"),
            "label_a": None,
            "label_b": None,
            "bin_a": None,
            "bin_b": None,
            "results": records,
        }

    if not payload.get("results"):
        raise SystemExit("JSON file is empty")
    return payload


def main_from_json(args):
    """Regenerate HTML from an existing benchmark JSON file."""
    json_path = Path(args.from_json)
    if not json_path.exists():
        raise SystemExit(f"JSON file not found: {json_path}")

    payload = load_report(json_path)
    records = payload["results"]

    # Detect whether this is a comparison (multiple labels) or single run.
    labels = list(dict.fromkeys(r["label"] for r in records))  # preserve order, dedupe

    # Infer display metadata from the first record.
    steps = payload.get("steps", args.steps)
    seed = payload.get("seed", args.seed)
    input_image = payload.get("input_image") or args.input

    if len(labels) == 2:
        label_a, label_b = labels
        if args.swap:
            label_a, label_b = label_b, label_a
        results_a = [r for r in records if r["label"] == label_a]
        results_b = [r for r in records if r["label"] == label_b]
        # Build a synthetic args namespace with the fields generate_comparison_html needs.
        synth = argparse.Namespace(
            input=input_image,
            steps=steps,
            seed=seed,
            bin_a=payload.get("bin_a") or label_a,
            bin_b=payload.get("bin_b") or label_b,
        )
        html = generate_comparison_html(results_a, results_b, label_a, label_b, synth)
        out_path = OUTPUT_DIR / "benchmark_comparison.html"
    elif len(labels) == 1:
        results = [r for r in records if r["label"] == labels[0]]
        synth = argparse.Namespace(
            input=input_image,
            steps=steps,
            seed=seed,
            bin_a=payload.get("bin_a") or labels[0],
            label_a=labels[0],
        )
        html = generate_single_html(results, synth)
        out_path = OUTPUT_DIR / "benchmark_report.html"
    else:
        raise SystemExit(
            f"Expected 1 or 2 distinct labels in JSON; found {len(labels)}: {labels}"
        )

    with open(out_path, "w") as f:
        f.write(html)
    print(f"✓ HTML regenerated from {json_path}")
    print(f"✓ Report: {out_path}")


def main():
    args = parse_args()

    if args.from_json:
        main_from_json(args)
        return

    input_image = Path(args.input)
    selected_shapes = parse_shape_selection(args.shapes)
    label_a = args.label_a or Path(args.bin_a).name
    label_b = args.label_b or (Path(args.bin_b).name if args.bin_b else None)

    print("\n" + "=" * 60)
    if args.bin_b:
        print(f"  Primeval Benchmark — {label_a} vs {label_b}")
    else:
        print(f"  Primeval Benchmark — {args.steps} steps per shape")
    print("=" * 60 + "\n")
    print("Shapes:", ", ".join(name for _, name in selected_shapes), "\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not args.no_build and Path(args.bin_a) == DEFAULT_BIN_A:
        print(f"Building {label_a}...")
        result = subprocess.run(DEFAULT_BUILD_CMD, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            print("Build failed!")
            print(result.stderr)
            return
        print("Build complete.\n")

    cli_style_a = detect_cli_style(args.bin_a)
    cli_style_b = detect_cli_style(args.bin_b) if args.bin_b else None

    results_a = []
    results_b = []
    reference_cache = {}

    for shape_type, shape_name in selected_shapes:
        ra = run_benchmark(args.bin_a, cli_style_a, shape_type, shape_name, input_image, args.steps, args.seed, label_a, reference_cache)
        if ra:
            results_a.append(ra)

        if args.bin_b:
            rb = run_benchmark(args.bin_b, cli_style_b, shape_type, shape_name, input_image, args.steps, args.seed, label_b, reference_cache)
            if rb:
                results_b.append(rb)

    if args.bin_b:
        html = generate_comparison_html(results_a, results_b, label_a, label_b, args)
        report_path = OUTPUT_DIR / "benchmark_comparison.html"

        all_results = results_a + results_b
        json_path = OUTPUT_DIR / "benchmark_comparison.json"
    else:
        html = generate_single_html(results_a, args)
        report_path = OUTPUT_DIR / "benchmark_report.html"

        all_results = results_a
        json_path = OUTPUT_DIR / "benchmark_results.json"

    shutil.copy2(input_image, OUTPUT_DIR / input_image.name)

    with open(report_path, "w") as f:
        f.write(html)
    print(f"\n✓ Report: {report_path}")

    report_payload = serialize_report(all_results, args, label_a, label_b)
    with open(json_path, "w") as f:
        json.dump(report_payload, f, indent=2)
    print(f"✓ JSON:   {json_path}\n")

    if args.bin_b and results_a and results_b:
        total_a = sum(r["elapsed_time"] for r in results_a)
        total_b = sum(r["elapsed_time"] for r in results_b)
        ratio = total_a / total_b
        avg_rmse_a = sum(r["rmse_rgb"] for r in results_a) / len(results_a)
        avg_rmse_b = sum(r["rmse_rgb"] for r in results_b) / len(results_b)
        print(
            f"Summary: {label_a} is {_overall_speed_text(ratio)} overall "
            f"({format_duration(total_a)} vs {format_duration(total_b)})"
        )
        print(
            f"Quality: {label_a} has {_quality_delta_text(avg_rmse_a / avg_rmse_b if avg_rmse_b else 1.0)} "
            f"on average (rmse {format_metric(avg_rmse_a)} vs {format_metric(avg_rmse_b)})"
        )
    else:
        results = results_a
        print(f"Summary: {len(results)} shapes | total {format_duration(sum(r['elapsed_time'] for r in results))}")
        if results:
            print(f"  Fastest: {min(results, key=lambda x: x['elapsed_time'])['shape_name']}")
            print(f"  Slowest: {max(results, key=lambda x: x['elapsed_time'])['shape_name']}")
    print()


if __name__ == "__main__":
    main()
