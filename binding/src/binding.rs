use napi::bindgen_prelude::*;
use napi::threadsafe_function::{ThreadsafeFunction, ThreadsafeFunctionCallMode};
use napi::{Env, Status};
use napi_derive::napi;
use primeval_core::shapes::ShapeKind;
use primeval_render::{
    approximate, parse_alpha_u32, parse_background_str, parse_seed_i64, ApproximateError,
    ApproximateRequest, ApproximateResult, InputSource, OutputFormat, ProgressInfo, RenderOptions,
};
use std::collections::HashMap;
use std::sync::atomic::AtomicU32;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};

static NEXT_TASK_ID: AtomicU32 = AtomicU32::new(1);
static TASKS: OnceLock<Mutex<HashMap<u32, Arc<AtomicBool>>>> = OnceLock::new();

fn tasks() -> &'static Mutex<HashMap<u32, Arc<AtomicBool>>> {
    TASKS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn with_task_registry<R>(
    registry: &Mutex<HashMap<u32, Arc<AtomicBool>>>,
    f: impl FnOnce(&HashMap<u32, Arc<AtomicBool>>) -> R,
) -> R {
    match registry.lock() {
        Ok(guard) => f(&guard),
        Err(poisoned) => f(&poisoned.into_inner()),
    }
}

fn with_task_registry_mut<R>(
    registry: &Mutex<HashMap<u32, Arc<AtomicBool>>>,
    f: impl FnOnce(&mut HashMap<u32, Arc<AtomicBool>>) -> R,
) -> R {
    match registry.lock() {
        Ok(mut guard) => f(&mut guard),
        Err(poisoned) => {
            let mut guard = poisoned.into_inner();
            f(&mut guard)
        }
    }
}

fn with_tasks<R>(f: impl FnOnce(&HashMap<u32, Arc<AtomicBool>>) -> R) -> R {
    with_task_registry(tasks(), f)
}

fn with_tasks_mut<R>(f: impl FnOnce(&mut HashMap<u32, Arc<AtomicBool>>) -> R) -> R {
    with_task_registry_mut(tasks(), f)
}

#[napi(object, object_to_js = false)]
pub struct NativeInputSource {
    pub kind: String,
    pub path: Option<String>,
    pub data: Option<Buffer>,
}

#[napi(object, object_to_js = false)]
pub struct NativeRenderOptions {
    pub count: u32,
    pub shape: String,
    pub alpha: Option<u32>,
    pub repeat: u32,
    pub seed: Option<i64>,
    pub background: String,
    #[napi(js_name = "resizeInput")]
    pub resize_input: u32,
    #[napi(js_name = "outputSize")]
    pub output_size: u32,
}

#[napi(object, object_to_js = false)]
pub struct NativeExecutionOptions {
    #[napi(js_name = "onProgress")]
    pub on_progress: Option<ThreadsafeFunction<NativeProgressInfo>>,
}

#[napi(object, object_to_js = false)]
pub struct NativeApproximateRequest {
    pub input: NativeInputSource,
    pub output: String,
    pub render: NativeRenderOptions,
    pub execution: Option<NativeExecutionOptions>,
}

#[napi(object)]
pub struct NativeProgressInfo {
    pub step: u32,
    pub total: u32,
    pub score: f64,
}

#[napi(object)]
pub struct NativeApproximateResult {
    pub format: String,
    pub data: Buffer,
    #[napi(js_name = "mimeType")]
    pub mime_type: String,
    pub width: u32,
    pub height: u32,
}

#[napi(js_name = "startApproximate")]
pub fn start_approximate(env: &Env, request: NativeApproximateRequest) -> Result<Object<'_>> {
    let NativeApproximateRequest {
        input,
        output,
        render,
        execution,
    } = request;
    let cancelled = Arc::new(AtomicBool::new(false));
    let cancelled_for_future = Arc::clone(&cancelled);
    let task_id = NEXT_TASK_ID.fetch_add(1, Ordering::Relaxed);
    with_tasks_mut(|tasks| {
        tasks.insert(task_id, Arc::clone(&cancelled));
    });
    let progress = execution.and_then(|execution| execution.on_progress);
    let request = normalize_request(input, output, render)?;

    let promise = env.spawn_future_with_callback(
        async move {
            let result = if let Some(tsfn) = progress.as_ref() {
                let on_progress = |info: ProgressInfo| {
                    let _ = tsfn.call(
                        Ok(NativeProgressInfo {
                            step: info.step,
                            total: info.total,
                            score: info.score,
                        }),
                        ThreadsafeFunctionCallMode::NonBlocking,
                    );
                };
                approximate(request, Some(&on_progress), cancelled_for_future.as_ref())
            } else {
                approximate(request, None, cancelled_for_future.as_ref())
            };
            with_tasks_mut(|tasks| {
                tasks.remove(&task_id);
            });

            result.map(NativeApproximateResult::from).map_err(map_error)
        },
        |_, result| Ok(result),
    )?;

    let mut handle = Object::new(env)?;
    handle.set("promise", promise)?;
    handle.set("taskId", task_id)?;
    Ok(handle)
}

#[napi(js_name = "cancelApproximate")]
pub fn cancel_approximate(task_id: u32) {
    if let Some(cancelled) = with_tasks(|tasks| tasks.get(&task_id).cloned()) {
        cancelled.store(true, Ordering::SeqCst);
    }
}

fn normalize_request(
    input: NativeInputSource,
    output: String,
    render: NativeRenderOptions,
) -> Result<ApproximateRequest> {
    let input = match input.kind.as_str() {
        "path" => {
            let path = input
                .path
                .ok_or_else(|| napi_error("ValidationError", "path input requires `path`"))?;
            InputSource::Path(path.into())
        }
        "bytes" => {
            let data = input
                .data
                .ok_or_else(|| napi_error("ValidationError", "bytes input requires `data`"))?;
            InputSource::Bytes(data.into())
        }
        other => {
            return Err(napi_error(
                "ValidationError",
                format!("unknown input kind: {other}"),
            ))
        }
    };

    let format = output
        .parse::<OutputFormat>()
        .map_err(|message| napi_error("ValidationError", message))?;

    let shape = render
        .shape
        .parse::<ShapeKind>()
        .map_err(|message| napi_error("ValidationError", message))?;

    let alpha =
        parse_alpha_u32(render.alpha).map_err(|message| napi_error("ValidationError", message))?;

    let background = parse_background_str(&render.background)
        .map_err(|message| napi_error("ValidationError", message))?;

    let seed = render
        .seed
        .map(|seed| parse_seed_i64(seed).map_err(|message| napi_error("ValidationError", message)))
        .transpose()?;

    Ok(ApproximateRequest {
        input,
        output: format,
        render: RenderOptions {
            count: render.count,
            shape,
            alpha,
            repeat: render.repeat as usize,
            seed,
            background,
            resize_input: render.resize_input,
            output_size: render.output_size,
            workers: None,
            gif_frame_step: 1,
        },
    })
}

fn map_error(error: ApproximateError) -> Error {
    match error {
        ApproximateError::Validation(message) => napi_error("ValidationError", message),
        ApproximateError::NotFound(path) => napi_error(
            "NotFoundError",
            format!("{} does not exist or is not readable", path.display()),
        ),
        ApproximateError::Aborted => napi_error("AbortError", "operation aborted"),
        ApproximateError::Internal(message) => napi_error("Error", message),
    }
}

fn napi_error(name: &str, message: impl Into<String>) -> Error {
    Error::new(
        Status::GenericFailure,
        format!("[{name}] {}", message.into()),
    )
}

impl From<ApproximateResult> for NativeApproximateResult {
    fn from(value: ApproximateResult) -> Self {
        let fmt = value.format();
        let format = fmt.extension().to_string();
        let mime_type = fmt.mime_type().to_string();
        let width = value.width();
        let height = value.height();
        let data = match value {
            ApproximateResult::Svg { data, .. } => Buffer::from(data.into_bytes()),
            ApproximateResult::Raster { data, .. } => Buffer::from(data),
        };
        Self {
            format,
            data,
            mime_type,
            width,
            height,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::panic::{catch_unwind, AssertUnwindSafe};

    fn render_options(shape: &str) -> NativeRenderOptions {
        NativeRenderOptions {
            count: 1,
            shape: shape.to_string(),
            alpha: Some(128),
            repeat: 0,
            seed: Some(7),
            background: "auto".to_string(),
            resize_input: 32,
            output_size: 32,
        }
    }

    #[test]
    fn normalize_request_uses_shared_shape_and_output_parsers() {
        let request = normalize_request(
            NativeInputSource {
                kind: "bytes".to_string(),
                path: None,
                data: Some(Buffer::from(vec![0_u8; 4])),
            },
            "jpeg".to_string(),
            render_options("rotated-rectangle"),
        )
        .expect("request should normalize");

        assert_eq!(request.output, OutputFormat::Jpg);
        assert_eq!(request.render.shape, ShapeKind::RotatedRectangle);
    }

    #[test]
    fn normalize_request_rejects_unknown_shape() {
        let error = normalize_request(
            NativeInputSource {
                kind: "bytes".to_string(),
                path: None,
                data: Some(Buffer::from(vec![0_u8; 4])),
            },
            "svg".to_string(),
            render_options("hexagon"),
        )
        .expect_err("shape should fail");

        assert_eq!(error.reason, "[ValidationError] unknown shape: hexagon");
    }

    #[test]
    fn task_registry_helpers_recover_from_poisoned_locks() {
        let registry = Mutex::new(HashMap::new());

        let _ = catch_unwind(AssertUnwindSafe(|| {
            with_task_registry_mut(&registry, |tasks| {
                tasks.insert(1, Arc::new(AtomicBool::new(false)));
                panic!("poison the mutex");
            });
        }));

        let cancelled = Arc::new(AtomicBool::new(false));
        with_task_registry_mut(&registry, |tasks| {
            tasks.insert(2, Arc::clone(&cancelled));
        });

        let task_ids =
            with_task_registry(&registry, |tasks| tasks.keys().copied().collect::<Vec<_>>());
        assert!(task_ids.contains(&1));
        assert!(task_ids.contains(&2));
    }
}
