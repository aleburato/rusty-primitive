use clap::builder::{PossibleValuesParser, TypedValueParser};
use clap::{Parser, Subcommand, ValueEnum};
use primeval_core::export::output_paths;
use primeval_core::{shapes::ShapeKind, OutputFormat};
use primeval_render::{
    parse_alpha_str, parse_background_str, prepare, ApproximateError, ApproximateResult,
    ProgressInfo, RenderOptions, RenderRequest,
};
use std::io::Write;
use std::path::Path;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::Instant;

#[derive(Parser)]
#[command(name = "primeval")]
#[command(version)]
#[command(about = "Approximate images with geometric shapes")]
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

    #[arg(long, value_delimiter = ',', value_parser = output_format_parser())]
    emit: Vec<OutputFormat>,

    #[arg(long, default_value_t = 100)]
    count: u32,

    #[arg(long, default_value = "any", value_parser = shape_kind_parser())]
    shape: ShapeKind,

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
    let emit = if args.emit.is_empty() {
        vec![detect_emit_from_output(&args.output)?]
    } else {
        args.emit
    };

    if args.output == "-" && emit.len() > 1 {
        return Err("stdout output supports only one emitted format".into());
    }
    if args.output == "-" && emit.contains(&OutputFormat::Gif) {
        return Err("gif output to stdout is not supported".into());
    }

    let seed = args
        .seed
        .unwrap_or_else(primeval_core::util::system_clock_seed);
    let alpha = parse_alpha_str(&args.alpha)
        .map_err(|message| std::io::Error::new(std::io::ErrorKind::InvalidInput, message))?;
    let background = parse_background_str(&args.background)
        .map_err(|message| std::io::Error::new(std::io::ErrorKind::InvalidInput, message))?;
    let render = RenderOptions {
        count: args.count,
        shape: args.shape,
        alpha,
        repeat: args.repeat as usize,
        seed: Some(seed),
        background,
        resize_input: args.resize_input,
        output_size: args.output_size,
        workers: args.threads,
        gif_frame_step: args.save_every,
    };

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
            "seed={seed} workers={}",
            render
                .workers
                .unwrap_or_else(primeval_render::default_worker_count)
        );
    }

    let on_progress = |info: ProgressInfo| {
        eprintln!(
            "{:>4}: elapsed={:.3}s score={:.6}",
            info.step,
            start.elapsed().as_secs_f64(),
            info.score,
        );
    };
    let callback: Option<&dyn Fn(ProgressInfo)> = if show_progress {
        Some(&on_progress)
    } else {
        None
    };
    let request = RenderRequest {
        input: primeval_render::InputSource::Path(args.input.into()),
        render,
    };
    let mut run = prepare(request, callback, cancelled.as_ref());

    let run = match &mut run {
        Ok(run) => run,
        Err(ApproximateError::Aborted) => return Ok(()),
        Err(error) => return Err(Box::new(error.clone())),
    };

    for (index, (_, path)) in output_paths(&args.output, &emit).into_iter().enumerate() {
        let result = run.result(emit[index]).map_err(Box::new)?;
        write_result(&path.to_string_lossy(), &result)?;
    }

    Ok(())
}

fn detect_emit_from_output(output: &str) -> Result<OutputFormat, Box<dyn std::error::Error>> {
    if output == "-" {
        return Ok(OutputFormat::Svg);
    }

    match Path::new(output)
        .extension()
        .and_then(|ext| ext.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase()
        .parse::<OutputFormat>()
    {
        Ok(format) => Ok(format),
        Err(_) => Err("could not infer output format from file extension".into()),
    }
}

fn shape_kind_parser() -> impl TypedValueParser<Value = ShapeKind> {
    PossibleValuesParser::new(ShapeKind::variants())
        .map(|value| value.parse::<ShapeKind>().expect("validated shape kind"))
}

fn output_format_parser() -> impl TypedValueParser<Value = OutputFormat> {
    PossibleValuesParser::new(OutputFormat::variants()).map(|value| {
        value
            .parse::<OutputFormat>()
            .expect("validated output format")
    })
}

fn write_result(path: &str, result: &ApproximateResult) -> Result<(), Box<dyn std::error::Error>> {
    let bytes: &[u8] = match result {
        ApproximateResult::Svg { data, .. } => data.as_bytes(),
        ApproximateResult::Raster { data, .. } => data,
    };
    if path == "-" {
        std::io::stdout().write_all(bytes)?;
    } else {
        std::fs::write(path, bytes)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cli_defaults_shape_to_any() {
        let cli = Cli::try_parse_from(["primeval", "run", "input.png", "--output", "out.svg"])
            .expect("cli should parse");

        match cli.command {
            Commands::Run(args) => assert_eq!(args.shape, ShapeKind::Any),
        }
    }

    #[test]
    fn cli_emit_parser_uses_shared_output_formats() {
        let cli = Cli::try_parse_from([
            "primeval",
            "run",
            "input.png",
            "--output",
            "out.png",
            "--emit",
            "jpg,gif",
        ])
        .expect("cli should parse");

        match cli.command {
            Commands::Run(args) => {
                assert_eq!(args.emit, vec![OutputFormat::Jpg, OutputFormat::Gif])
            }
        }
    }
}
