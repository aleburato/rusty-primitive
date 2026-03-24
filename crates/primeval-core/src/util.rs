/// Converts degrees to radians.
#[must_use]
#[inline]
pub fn radians(degrees: f64) -> f64 {
    degrees * std::f64::consts::PI / 180.0
}

/// Converts radians to degrees.
#[must_use]
#[inline]
pub fn degrees(radians: f64) -> f64 {
    radians * 180.0 / std::f64::consts::PI
}

/// Rotates point `(x, y)` by `theta` radians around the origin.
#[must_use]
#[inline]
pub fn rotate(x: f64, y: f64, theta: f64) -> (f64, f64) {
    let (sin_t, cos_t) = theta.sin_cos();
    rotate_sc(x, y, sin_t, cos_t)
}

/// Rotates point `(x, y)` using pre-computed sine and cosine values.
///
/// Use this when the same angle is applied to many points to avoid
/// redundant trigonometric calls.
#[must_use]
#[inline]
pub fn rotate_sc(x: f64, y: f64, sin_t: f64, cos_t: f64) -> (f64, f64) {
    (x * cos_t - y * sin_t, x * sin_t + y * cos_t)
}

#[must_use]
pub fn system_clock_seed() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("system clock should be after unix epoch")
        .as_nanos() as u64
}

#[must_use]
pub fn number_string(mut x: f64) -> String {
    for suffix in ["", "k", "M", "G"] {
        if x < 1000.0 {
            return format!("{x:.1}{suffix}");
        }
        x /= 1000.0;
    }
    format!("{x:.1}T")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn radians_and_degrees_roundtrip() {
        let deg = 45.0;
        let rad = radians(deg);
        let back = degrees(rad);
        assert!((back - deg).abs() < 1e-12);
    }

    #[test]
    fn radians_known_values() {
        assert!((radians(180.0) - std::f64::consts::PI).abs() < 1e-12);
        assert!((radians(90.0) - std::f64::consts::FRAC_PI_2).abs() < 1e-12);
    }

    #[test]
    fn rotate_identity() {
        let (rx, ry) = rotate(1.0, 0.0, 0.0);
        assert!((rx - 1.0).abs() < 1e-12);
        assert!(ry.abs() < 1e-12);
    }

    #[test]
    fn rotate_quarter_turn() {
        let (rx, ry) = rotate(1.0, 0.0, std::f64::consts::FRAC_PI_2);
        assert!(rx.abs() < 1e-12);
        assert!((ry - 1.0).abs() < 1e-12);
    }

    #[test]
    fn rotate_sc_matches_rotate() {
        let cases = [
            (1.0, 0.0, 0.0),
            (1.0, 0.0, std::f64::consts::FRAC_PI_2),
            (1.0, 1.0, std::f64::consts::FRAC_PI_4),
            (3.0, -4.0, 1.23),
        ];
        for (x, y, theta) in cases {
            let (sin_t, cos_t) = theta.sin_cos();
            let (rx1, ry1) = rotate(x, y, theta);
            let (rx2, ry2) = rotate_sc(x, y, sin_t, cos_t);
            assert!(
                (rx1 - rx2).abs() < 1e-12 && (ry1 - ry2).abs() < 1e-12,
                "mismatch for ({x}, {y}, {theta}): rotate=({rx1},{ry1}) rotate_sc=({rx2},{ry2})"
            );
        }
    }

    #[test]
    fn number_string_formats_suffixes() {
        assert_eq!(number_string(999.0), "999.0");
        assert_eq!(number_string(1000.0), "1.0k");
        assert_eq!(number_string(1_200_000.0), "1.2M");
    }
}
