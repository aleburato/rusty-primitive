# AGENTS.md

## Project Overview

`primitive` is a Rust implementation of geometric image approximation. The repository root is the Cargo workspace, which contains:

- `primitive-core`: optimization engine, rasterization, scoring, and export
- `primitive-cli`: end-user command-line interface

User-facing README assets live in `docs/readme/`.

## Workspace Layout

```text
crates/
├── primitive-core/src/
│   ├── model.rs
│   ├── worker.rs
│   ├── score.rs
│   ├── shapes.rs
│   ├── optimize.rs
│   ├── buffer.rs
│   ├── raster.rs
│   ├── error_grid.rs
│   ├── state.rs
│   ├── export.rs
│   └── test_util.rs
└── primitive-cli/src/main.rs
```

## Build And Test

Run commands from the repository root:

```bash
cargo build --release
cargo test
cargo fmt
cargo clippy --all-targets
```

CLI example:

```bash
./target/release/primitive-cli run input.png --output output.png --emit png,svg --count 1000 --shape any
```

## Benchmarking

Use `scripts/benchmark.py` to compare two binaries:

```bash
python3 scripts/benchmark.py \
  --bin-a ./target/release/primitive-cli \
  --bin-b /path/to/other/binary \
  --label-a current \
  --label-b baseline \
  --no-build
```

Reports are written to `output/`.

## Core Algorithm Notes

Each `Model::step`:

1. Computes a spatial error grid from `target` and `current`
2. Searches candidate shapes in parallel worker contexts
3. Hill-climbs the best candidates
4. Commits the winning shape to history and the current buffer
5. Replays history at output resolution for final raster or SVG export

Important implementation choices:

- integer hot-path scoring with optional aarch64 NEON in `score.rs`
- closed `enum Shape` dispatch instead of trait-object polymorphism
- scanline rasterization across all shapes
- multi-threaded worker-local scratch buffers

## Quality Gates

Before merging:

- `cargo fmt --check`
- `cargo clippy --all-targets -- -D warnings`
- `cargo test`
