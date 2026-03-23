use clap::{Parser, Subcommand, ValueEnum};
use primitive_core::export::{
    average_background, load_image, output_paths, save_file, save_gif, save_jpg, save_png,
    thumbnail,
};
use primitive_core::shapes::ShapeKind;
use primitive_core::{Buffer, Color, Model, ModelOptions};
use std::path::Path;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::Instant;

#[derive(Parser)]
#[command(name = "primitive")]
#[command(version)]
#[command(about = "Approximate images with geometric primitives")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    Run(RunArgs),
}

#[derive(Parser)]
struct RunArgs {
    input: String,

    #[arg(short, long)]
    output: String,

    #[arg(long, value_delimiter = ',')]
    emit: Vec<EmitFormat>,

    #[arg(long, default_value_t = 100)]
    count: u32,

    #[arg(long, value_enum, default_value_t = ShapeArg::Triangle)]
    shape: ShapeArg,

    #[arg(long, default_value = "128")]
    alpha: String,

    #[arg(long, default_value = "auto")]
    background: String,

    #[arg(long, default_value_t = 256)]
    resize_input: u32,

    #[arg(long, default_value_t = 1024)]
    output_size: u32,

    #[arg(long)]
    threads: Option<usize>,

    #[arg(long)]
    seed: Option<u64>,

    #[arg(long, default_value_t = 0)]
    repeat: u32,

    #[arg(long, default_value_t = 1)]
    save_every: usize,

    #[arg(long, value_enum, default_value_t = ProgressMode::Auto)]
    progress: ProgressMode,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, ValueEnum)]
enum EmitFormat {
    Png,
    Jpg,
    Svg,
    Gif,
}

impl EmitFormat {
    fn as_ext(self) -> &'static str {
        match self {
            Self::Png => "png",
            Self::Jpg => "jpg",
            Self::Svg => "svg",
            Self::Gif => "gif",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, ValueEnum)]
enum ShapeArg {
    Any,
    Triangle,
    Rectangle,
    Ellipse,
    Circle,
    RotatedRectangle,
    Quadratic,
    RotatedEllipse,
    Polygon,
}

impl From<ShapeArg> for ShapeKind {
    fn from(value: ShapeArg) -> Self {
        match value {
            ShapeArg::Any => ShapeKind::Any,
            ShapeArg::Triangle => ShapeKind::Triangle,
            ShapeArg::Rectangle => ShapeKind::Rectangle,
            ShapeArg::Ellipse => ShapeKind::Ellipse,
            ShapeArg::Circle => ShapeKind::Circle,
            ShapeArg::RotatedRectangle => ShapeKind::RotatedRectangle,
            ShapeArg::Quadratic => ShapeKind::Quadratic,
            ShapeArg::RotatedEllipse => ShapeKind::RotatedEllipse,
            ShapeArg::Polygon => ShapeKind::Polygon,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, ValueEnum)]
enum ProgressMode {
    Auto,
    Plain,
    Off,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let cli = Cli::parse();
    match cli.command {
        Commands::Run(args) => run(args),
    }
}

fn run(args: RunArgs) -> Result<(), Box<dyn std::error::Error>> {
    let profile_quadratic = std::env::var_os("PRIMITIVE_PROFILE_QUADRATIC").is_some();
    let emit = if args.emit.is_empty() {
        vec![detect_emit_from_output(&args.output)?]
    } else {
        args.emit
    };

    if args.output == "-" && emit.len() > 1 {
        return Err("stdout output supports only one emitted format".into());
    }
    if args.output == "-" && emit.contains(&EmitFormat::Gif) {
        return Err("gif output to stdout is not supported".into());
    }

    let input = load_image(&args.input)?;
    let working = if args.resize_input > 0 {
        thumbnail(&input, args.resize_input)
    } else {
        input.to_rgba8()
    };

    let background = if args.background.eq_ignore_ascii_case("auto") {
        average_background(&input)
    } else {
        Color::from_hex(&args.background).ok_or("invalid background color")?
    };

    let seed = args
        .seed
        .unwrap_or_else(primitive_core::util::system_clock_seed);

    let threads = args.threads.unwrap_or_else(default_worker_count);
    let alpha = parse_alpha(&args.alpha)?;
    let mut model = Model::new(
        Buffer::from_image(&working),
        background,
        args.output_size,
        ModelOptions {
            seed: Some(seed),
            workers: threads,
            profile_quadratic,
            ..ModelOptions::default()
        },
    );

    let cancelled = Arc::new(AtomicBool::new(false));
    {
        let cancelled = Arc::clone(&cancelled);
        ctrlc::set_handler(move || {
            cancelled.store(true, Ordering::SeqCst);
        })?;
    }

    let show_progress = args.progress != ProgressMode::Off;
    let start = Instant::now();
    if show_progress {
        eprintln!(
            "seed={seed} workers={threads} start_score={:.6}",
            model.score_f64()
        );
    }

    for step in 0..args.count {
        if cancelled.load(Ordering::SeqCst) {
            break;
        }

        let step_start = Instant::now();
        let evaluations = model.step(args.shape.into(), alpha, args.repeat as usize)?;
        if show_progress {
            let step_seconds = step_start.elapsed().as_secs_f64().max(f64::EPSILON);
            let nps = primitive_core::util::number_string(evaluations as f64 / step_seconds);
            eprintln!(
                "{:>4}: elapsed={:.3}s score={:.6} evals={} evals/s={}",
                step + 1,
                start.elapsed().as_secs_f64(),
                model.score_f64(),
                evaluations,
                nps,
            );
        }
    }

    if profile_quadratic {
        if let Some(stats) = model.quadratic_profile_stats() {
            let avg_attempts = stats.mutate_attempts as f64 / stats.raster_calls.max(1) as f64;
            let invalid_rate =
                stats.mutate_invalid_retries as f64 / stats.mutate_attempts.max(1) as f64;
            let avg_subdivide = stats.subdivide_calls as f64 / stats.raster_calls.max(1) as f64;
            let avg_flat_segments = stats.flat_segments as f64 / stats.raster_calls.max(1) as f64;
            let avg_scanlines = stats.emitted_scanlines as f64 / stats.raster_calls.max(1) as f64;
            eprintln!(
                "quadratic_profile mutate_attempts={} mutate_invalid_retries={} invalid_rate={:.3} raster_calls={} subdivide_calls={} flat_segments={} emitted_scanlines={} avg_mutate_attempts_per_raster={:.2} avg_subdivide_per_raster={:.2} avg_flat_segments_per_raster={:.2} avg_scanlines_per_raster={:.2}",
                stats.mutate_attempts,
                stats.mutate_invalid_retries,
                invalid_rate,
                stats.raster_calls,
                stats.subdivide_calls,
                stats.flat_segments,
                stats.emitted_scanlines,
                avg_attempts,
                avg_subdivide,
                avg_flat_segments,
                avg_scanlines,
            );
        } else {
            eprintln!("quadratic_profile no-data");
        }
    }

    let rendered = model.render_output();
    let svg = emit.contains(&EmitFormat::Svg).then(|| model.svg());
    let gif_frames = emit.contains(&EmitFormat::Gif).then(|| {
        let mut frames = model.frames(0.001);
        if args.save_every > 1 {
            frames = frames
                .into_iter()
                .enumerate()
                .filter_map(|(index, frame)| (index % args.save_every == 0).then_some(frame))
                .collect();
        }
        frames
    });

    let emit_names = emit
        .iter()
        .map(|item| item.as_ext().to_string())
        .collect::<Vec<_>>();
    for (format, path) in output_paths(&args.output, &emit_names) {
        let path_str = path.to_string_lossy();
        match format.as_str() {
            "png" => save_png(&path_str, &rendered)?,
            "jpg" => save_jpg(&path_str, &rendered, 95)?,
            "svg" => save_file(
                &path_str,
                svg.as_deref().ok_or("svg output was not prepared")?,
            )?,
            "gif" => save_gif(
                &path_str,
                gif_frames.as_deref().ok_or("gif output was not prepared")?,
                50,
                250,
            )?,
            _ => return Err(format!("unsupported format: {format}").into()),
        }
    }

    Ok(())
}

fn detect_emit_from_output(output: &str) -> Result<EmitFormat, Box<dyn std::error::Error>> {
    if output == "-" {
        return Ok(EmitFormat::Svg);
    }

    match Path::new(output)
        .extension()
        .and_then(|ext| ext.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase()
        .as_str()
    {
        "png" => Ok(EmitFormat::Png),
        "jpg" | "jpeg" => Ok(EmitFormat::Jpg),
        "svg" => Ok(EmitFormat::Svg),
        "gif" => Ok(EmitFormat::Gif),
        _ => Err("could not infer output format from file extension".into()),
    }
}

fn parse_alpha(value: &str) -> Result<i32, Box<dyn std::error::Error>> {
    if value.eq_ignore_ascii_case("auto") {
        return Ok(0);
    }

    let parsed: i32 = value.parse()?;
    if !(1..=255).contains(&parsed) {
        return Err("alpha must be 1..255 or auto".into());
    }
    Ok(parsed)
}

fn default_worker_count() -> usize {
    std::thread::available_parallelism()
        .map(std::num::NonZeroUsize::get)
        .unwrap_or(1)
}
