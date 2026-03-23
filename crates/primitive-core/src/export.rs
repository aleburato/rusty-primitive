use crate::{Buffer, Color};
use gif::{Encoder, Frame, Repeat};
use image::codecs::jpeg::JpegEncoder;
use image::{imageops, DynamicImage, GenericImageView, ImageEncoder, ImageReader, RgbaImage};
use std::fs::File;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

pub fn load_image(path: &str) -> Result<DynamicImage, Box<dyn std::error::Error>> {
    if path == "-" {
        let mut bytes = Vec::new();
        std::io::stdin().read_to_end(&mut bytes)?;
        return Ok(image::load_from_memory(&bytes)?);
    }
    Ok(ImageReader::open(path)?.decode()?)
}

pub fn save_file(path: &str, contents: &str) -> Result<(), Box<dyn std::error::Error>> {
    if path == "-" {
        std::io::stdout().write_all(contents.as_bytes())?;
        return Ok(());
    }
    std::fs::write(path, contents)?;
    Ok(())
}

pub fn save_png(path: &str, buffer: &Buffer) -> Result<(), Box<dyn std::error::Error>> {
    let image = buffer.to_image();
    if path == "-" {
        let encoder = image::codecs::png::PngEncoder::new(std::io::stdout());
        encoder.write_image(
            image.as_raw(),
            image.width(),
            image.height(),
            image::ColorType::Rgba8.into(),
        )?;
        return Ok(());
    }
    image.save_with_format(path, image::ImageFormat::Png)?;
    Ok(())
}

pub fn save_jpg(
    path: &str,
    buffer: &Buffer,
    quality: u8,
) -> Result<(), Box<dyn std::error::Error>> {
    let rgb = rgba_to_rgb(buffer.pixels());
    let mut out: Box<dyn Write> = if path == "-" {
        Box::new(std::io::stdout())
    } else {
        Box::new(File::create(path)?)
    };
    let mut encoder = JpegEncoder::new_with_quality(&mut out, quality);
    encoder.encode(
        &rgb,
        buffer.width(),
        buffer.height(),
        image::ColorType::Rgb8.into(),
    )?;
    Ok(())
}

pub fn save_gif(
    path: &str,
    frames: &[Buffer],
    delay: u16,
    last_delay: u16,
) -> Result<(), Box<dyn std::error::Error>> {
    let Some(first) = frames.first() else {
        return Ok(());
    };
    let mut out = File::create(path)?;
    let mut encoder = Encoder::new(&mut out, first.width() as u16, first.height() as u16, &[])?;
    encoder.set_repeat(Repeat::Infinite)?;
    for (index, frame_buffer) in frames.iter().enumerate() {
        let mut rgba = frame_buffer.pixels().to_vec();
        let mut frame = Frame::from_rgba_speed(
            frame_buffer.width() as u16,
            frame_buffer.height() as u16,
            &mut rgba,
            10,
        );
        frame.delay = if index + 1 == frames.len() {
            last_delay
        } else {
            delay
        };
        encoder.write_frame(&frame)?;
    }
    Ok(())
}

#[must_use]
pub fn thumbnail(image: &DynamicImage, max_size: u32) -> RgbaImage {
    let (width, height) = image.dimensions();
    if width <= max_size && height <= max_size {
        return image.to_rgba8();
    }

    let (new_width, new_height) = if width >= height {
        (max_size, (max_size * height / width).max(1))
    } else {
        ((max_size * width / height).max(1), max_size)
    };

    imageops::resize(
        image,
        new_width,
        new_height,
        imageops::FilterType::CatmullRom,
    )
}

#[must_use]
pub fn resize_buffer(buffer: &Buffer, width: u32, height: u32) -> Buffer {
    let resized = imageops::resize(
        &buffer.to_image(),
        width,
        height,
        imageops::FilterType::CatmullRom,
    );
    Buffer::from_image(&resized)
}

#[must_use]
pub fn output_paths(base_output: &str, emits: &[String]) -> Vec<(String, PathBuf)> {
    let path = Path::new(base_output);
    let stem = path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("output");
    let parent = path.parent().unwrap_or_else(|| Path::new("."));

    if emits.len() == 1 {
        return vec![(emits[0].clone(), path.to_path_buf())];
    }

    emits
        .iter()
        .map(|emit| (emit.clone(), parent.join(format!("{stem}.{emit}"))))
        .collect()
}

#[must_use]
pub fn average_background(image: &DynamicImage) -> Color {
    Buffer::from_image(&image.to_rgba8()).average_color()
}

fn rgba_to_rgb(rgba: &[u8]) -> Vec<u8> {
    let mut rgb = Vec::with_capacity(rgba.len() / 4 * 3);
    for pixel in rgba.chunks_exact(4) {
        rgb.extend_from_slice(&pixel[..3]);
    }
    rgb
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::{DynamicImage, Rgba, RgbaImage};

    #[test]
    fn save_jpg_writes_rgb_file() {
        let path = std::env::temp_dir().join(format!(
            "primitive-export-test-{}-{}.jpg",
            std::process::id(),
            std::thread::current().name().unwrap_or("unnamed")
        ));
        let buffer = Buffer::new_from_color(2, 2, Color::new(10, 20, 30, 255));

        let result = save_jpg(path.to_str().unwrap_or(""), &buffer, 90);

        assert!(result.is_ok(), "jpg export should succeed: {result:?}");
        let metadata = std::fs::metadata(&path).expect("jpg output should exist");
        assert!(metadata.len() > 0, "jpg output should not be empty");
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn thumbnail_clamps_extreme_aspect_ratio_to_non_zero_dimensions() {
        let image =
            DynamicImage::ImageRgba8(RgbaImage::from_pixel(10_000, 1, Rgba([0, 0, 0, 255])));

        let resized = thumbnail(&image, 100);

        assert_eq!(resized.width(), 100);
        assert_eq!(resized.height(), 1);
    }
}
