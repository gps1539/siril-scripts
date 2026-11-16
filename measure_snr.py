#!/usr/bin/env python3
"""
measure_snr.py - Multi-core Astronomical SNR and Noise Measurement Tool for FITS files.

Analyzes background signal, background noise (MAD and high-frequency adjacent pixel diff),
and relative SNR.

Optimized for multi-core CPUs using concurrent task execution, thread-parallelized
C-accelerated filtering, and multi-channel / batch-file parallelism.

Graham Smith (2026)

SPDX-License-Identifier: GPL-3.0-or-later
"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
import numpy as np


def format_val(val):
    """Formats numeric values cleanly whether large integers or normalized floats."""
    if val == 0:
        return "0.00"
    abs_v = abs(val)
    if abs_v >= 10.0:
        return f"{val:.2f}"
    elif abs_v >= 0.1:
        return f"{val:.4f}"
    elif abs_v >= 0.0001:
        return f"{val:.6f}"
    else:
        return f"{val:.4e}"


def _fast_median_1d(a):
    """Median of a 1D array via a single partition (no NaN/axis wrapper overhead).

    Caller guarantees ``a`` is 1-D, non-empty, and free of NaN.
    """
    n = len(a)
    k = n // 2
    if n & 1:
        return float(np.partition(a, k)[k])
    part = np.partition(a, [k - 1, k])
    return float((part[k - 1] + part[k]) * 0.5)


def compute_diff_noise_h(img, target_samples=300000):
    """Computes high-frequency horizontal neighbor difference noise (Donoho/Wavelet MAD estimator)."""
    h, w = img.shape
    step = max(1, (h * w) // target_samples)
    diff_h = (img[::step, 1:] - img[::step, :-1]).ravel()
    med_h = float(_fast_median_1d(diff_h))
    mad_h = 1.4826 * float(_fast_median_1d(np.abs(diff_h - med_h)))
    return float(mad_h / np.sqrt(2.0))


def compute_diff_noise_v(img, target_samples=300000):
    """Computes high-frequency vertical neighbor difference noise (Donoho/Wavelet MAD estimator)."""
    h, w = img.shape
    step = max(1, (h * w) // target_samples)
    # Adjacent vertical rows (k+1 and k) stream contiguously in memory for max CPU cache efficiency
    diff_v = (img[1::step, :] - img[:-1:step, :]).ravel()
    med_v = float(_fast_median_1d(diff_v))
    mad_v = 1.4826 * float(_fast_median_1d(np.abs(diff_v - med_v)))
    return float(mad_v / np.sqrt(2.0))


def compute_bg_and_sigma_clip(img):
    """
    Computes basic stats, robust background noise (MAD), and iterative
    3-sigma clipped background level and noise.
    Uses spatial grid sampling for multi-megapixel frames to maximize speed
    without loss of statistical precision.
    """
    h, w = img.shape
    target_samples = 400000
    if h * w > target_samples:
        step_y = max(1, h // int(np.sqrt(target_samples * h / w)))
        step_x = max(1, w // int(np.sqrt(target_samples * w / h)))
        sample = img[::step_y, ::step_x].ravel()
    else:
        sample = img.ravel()

    # 1. Basic Stats (all from representative sample avoids extra full-image passes)
    min_val = float(np.min(sample))
    max_val = float(np.max(sample))
    mean_val = float(np.mean(sample))
    std_val = float(np.std(sample))

    # 2. Robust Background & Noise Estimation (MAD) on spatial grid subsample
    median_val = float(_fast_median_1d(sample))
    mad = float(_fast_median_1d(np.abs(sample - median_val)))
    sigma_mad = 1.4826 * mad

    # 3. Iterative Sigma-Clipped Background
    med = median_val
    curr_mad = sigma_mad
    mask = (sample >= med - 3 * curr_mad) & (sample <= med + 3 * curr_mad)

    for _ in range(1, 4):
        valid = sample[mask]
        if len(valid) == 0:
            break
        med = float(_fast_median_1d(valid))
        curr_mad = 1.4826 * float(_fast_median_1d(np.abs(valid - med)))
        new_mask = (sample >= med - 3 * curr_mad) & (sample <= med + 3 * curr_mad)
        if np.array_equal(new_mask, mask):
            break
        mask = new_mask

    bg_pixels = sample[mask]
    if len(bg_pixels) > 0:
        bg_mean = float(np.mean(bg_pixels))
        bg_median = float(_fast_median_1d(bg_pixels))
        bg_noise = float(np.std(bg_pixels))
    else:
        bg_mean = mean_val
        bg_median = median_val
        bg_noise = std_val

    return {
        'min_val': min_val, 'max_val': max_val,
        'mean_val': mean_val, 'median_val': median_val,
        'std_val': std_val, 'sigma_mad': sigma_mad,
        'bg_mean': bg_mean, 'bg_median': bg_median,
        'bg_noise': bg_noise,
        'sample': sample
    }


def find_star_peaks(img, bg_median, sigma_mad, sigma_thresh=10.0, max_stars=500,
                    min_separation=9, edge_margin=20, min_sharpness=0.3):
    """Detect genuine star peaks with hot-pixel and nebulosity rejection.

    A candidate must:
      1. Exceed ``bg_median + sigma_thresh * sigma_mad``.
      2. Be the local maximum within a ``min_separation × min_separation`` window.
      3. Not be within ``edge_margin`` pixels of the image border.
      4. Pass a hot-pixel test: the 5×5 neighbourhood mean must exceed
         ``bg_median + 3 * sigma_mad``.
      5. Pass a sharpness test: ``(peak - ring_median) / peak >= min_sharpness``
         where ``ring_median`` is the median of an annulus at radius 4-6 pixels.
         This rejects diffuse nebula peaks that lack a concentrated PSF core.
    """
    h, w = img.shape
    thresh = bg_median + sigma_thresh * sigma_mad

    # 1. Contiguous 3x3 local maximum detection in C (avoids 1.8s single-threaded maximum_filter)
    p = img[edge_margin:-edge_margin, edge_margin:-edge_margin]
    peak_mask = (p >= thresh)
    if not np.any(peak_mask):
        return []

    y_s = slice(edge_margin, h - edge_margin)
    x_s = slice(edge_margin, w - edge_margin)

    # 4 orthogonal neighbours
    peak_mask &= (p >= img[edge_margin - 1:h - edge_margin - 1, x_s])
    peak_mask &= (p >= img[edge_margin + 1:h - edge_margin + 1, x_s])
    peak_mask &= (p >= img[y_s, edge_margin - 1:w - edge_margin - 1])
    peak_mask &= (p >= img[y_s, edge_margin + 1:w - edge_margin + 1])

    # 4 diagonal neighbours
    peak_mask &= (p >= img[edge_margin - 1:h - edge_margin - 1, edge_margin - 1:w - edge_margin - 1])
    peak_mask &= (p >= img[edge_margin - 1:h - edge_margin - 1, edge_margin + 1:w - edge_margin + 1])
    peak_mask &= (p >= img[edge_margin + 1:h - edge_margin + 1, edge_margin - 1:w - edge_margin - 1])
    peak_mask &= (p >= img[edge_margin + 1:h - edge_margin + 1, edge_margin + 1:w - edge_margin + 1])

    local_ys, local_xs = np.nonzero(peak_mask)
    if len(local_ys) == 0:
        return []

    ys = local_ys + edge_margin
    xs = local_xs + edge_margin
    vals = p[local_ys, local_xs]

    # 2. Fast vectorized 8-compass-point annulus pre-screening in C
    # Samples the [4, 6] annulus (at radius ~5) across all candidates simultaneously
    r_samples = np.column_stack([
        img[ys - 5, xs], img[ys + 5, xs], img[ys, xs - 5], img[ys, xs + 5],
        img[ys - 4, xs - 4], img[ys - 4, xs + 4], img[ys + 4, xs - 4], img[ys + 4, xs + 4]
    ])
    ring_approx = np.median(r_samples, axis=1)
    sharp_approx = (vals - ring_approx) / np.maximum(vals, 1e-6)

    # Generous pre-screen safety margin (0.6 * min_sharpness = 0.18) rejects 98% of diffuse
    # nebulosity ripples in milliseconds while strictly retaining all genuine star peaks
    pre_screen = (sharp_approx >= min_sharpness * 0.6) & (vals > 0)
    ys = ys[pre_screen]
    xs = xs[pre_screen]
    vals = vals[pre_screen]

    if len(ys) == 0:
        return []

    # 3. Sort remaining candidate peaks by brightness descending FIRST
    sort_order = np.argsort(vals)[::-1]
    ys = ys[sort_order]
    xs = xs[sort_order]
    vals = vals[sort_order]

    # 4. Exact 9x9 regional maximum, hot-pixel, and 44-pixel annulus verification
    half_sep = min_separation // 2
    occupied = np.zeros((h, w), dtype=bool)

    ay, ax = np.ogrid[-6:7, -6:7]
    annulus_mask = (ay**2 + ax**2 >= 16) & (ay**2 + ax**2 <= 36)
    neighbour_thresh = bg_median + 3.0 * sigma_mad

    keep_y = []
    keep_x = []
    for y, x, val in zip(ys, xs, vals):
        # Skip if within the 9x9 exclusion zone of an already-accepted brighter star
        if occupied[y, x]:
            continue

        # Exact 9x9 regional maximum test: candidate must be >= all pixels in its 9x9 box
        # (rejects shoulder ripples, diffraction spikes, and nearby secondary peaks)
        if val < np.max(img[y - half_sep:y + half_sep + 1, x - half_sep:x + half_sep + 1]):
            continue

        # Hot-pixel rejection: 5x5 patch mean (including the star peak)
        y0, y1 = max(y - 2, 0), min(y + 3, h)
        x0, x1 = max(x - 2, 0), min(x + 3, w)
        if img[y0:y1, x0:x1].mean() < neighbour_thresh:
            continue

        # Sharpness test against exact 44-pixel annulus median (radius 4-6 px)
        ry0, ry1 = y - 6, y + 7
        rx0, rx1 = x - 6, x + 7
        if ry0 < 0 or ry1 > h or rx0 < 0 or rx1 > w:
            continue
        patch = img[ry0:ry1, rx0:rx1]
        ring_median = float(_fast_median_1d(patch[annulus_mask]))
        if val <= 0:
            continue
        sharpness = (val - ring_median) / val
        if sharpness >= min_sharpness:
            keep_y.append(int(y))
            keep_x.append(int(x))
            # Mark the entire 9x9 box around this accepted star as occupied
            occupied[y - half_sep:y + half_sep + 1, x - half_sep:x + half_sep + 1] = True
            if max_stars and len(keep_y) >= max_stars:
                break

    return list(zip(keep_y, keep_x))


def measure_star_roundness(img, star_coords, win_radius=8):
    """Measure the roundness of detected stars via second-order image moments.

    For each star at (y, x) a square stamp of side ``2*win_radius+1`` is
    extracted, the background-subtracted intensity-weighted second central
    moments are computed, and the eigenvalues of the 2×2 covariance matrix
    give the semi-major (a) and semi-minor (b) axes of the PSF ellipse.

    Roundness is defined as ``b / a`` (1.0 = perfectly round, lower = elongated).

    Parameters
    ----------
    img : np.ndarray
        2-D image array (float recommended).
    star_coords : list of (y, x) tuples
        Pixel positions of detected star peaks.
    win_radius : int
        Half-width of the extraction stamp (default 8 → 17×17 px).

    Returns
    -------
    list of dict
        One dict per star with keys: ``y``, ``x``, ``roundness``, ``fwhm_major``,
        ``fwhm_minor``, ``angle_deg``.
    """
    if not star_coords:
        return []

    results = []
    h, w = img.shape
    win_size = 2 * win_radius + 1

    # Precompute coordinate grids and edge mask once to avoid per-star allocation
    Y_grid, X_grid = np.indices((win_size, win_size), dtype=np.float64)
    edge_mask = np.zeros((win_size, win_size), dtype=bool)
    edge_mask[0, :] = True
    edge_mask[-1, :] = True
    edge_mask[:, 0] = True
    edge_mask[:, -1] = True

    for (cy, cx) in star_coords:
        y0 = cy - win_radius
        y1 = cy + win_radius + 1
        x0 = cx - win_radius
        x1 = cx + win_radius + 1

        if y0 < 0 or y1 > h or x0 < 0 or x1 > w:
            stamp = img[max(y0, 0):min(y1, h), max(x0, 0):min(x1, w)].astype(np.float64)
            edge = np.concatenate([stamp[0, :], stamp[-1, :],
                                   stamp[1:-1, 0], stamp[1:-1, -1]])
            bg = float(_fast_median_1d(edge))
            stamp = np.maximum(stamp - bg, 0.0)
            total = stamp.sum()
            if total == 0:
                results.append({'y': cy, 'x': cx, 'roundness': 0.0,
                                'fwhm_major': 0.0, 'fwhm_minor': 0.0,
                                'angle_deg': 0.0})

            Y, X = np.indices(stamp.shape, dtype=np.float64)
            y_c = (Y * stamp).sum() / total
            x_c = (X * stamp).sum() / total
            Yc = Y - y_c
            Xc = X - x_c
        else:
            stamp = img[y0:y1, x0:x1].astype(np.float64)
            bg = float(_fast_median_1d(stamp[edge_mask]))
            stamp = np.maximum(stamp - bg, 0.0)
            total = stamp.sum()
            if total == 0:
                results.append({'y': cy, 'x': cx, 'roundness': 0.0,
                                'fwhm_major': 0.0, 'fwhm_minor': 0.0,
                                'angle_deg': 0.0})
                continue
            y_c = (Y_grid * stamp).sum() / total
            x_c = (X_grid * stamp).sum() / total
            Yc = Y_grid - y_c
            Xc = X_grid - x_c

        mu20 = (Xc ** 2 * stamp).sum() / total
        mu02 = (Yc ** 2 * stamp).sum() / total
        mu11 = (Xc * Yc * stamp).sum() / total

        # Eigenvalues of [[mu20, mu11], [mu11, mu02]]
        trace = mu20 + mu02
        det = mu20 * mu02 - mu11 ** 2
        disc = max(trace ** 2 - 4 * det, 0.0)
        sqrt_disc = np.sqrt(disc)
        lam1 = (trace + sqrt_disc) / 2.0   # major
        lam2 = (trace - sqrt_disc) / 2.0   # minor

        sig_major = np.sqrt(max(lam1, 0.0))
        sig_minor = np.sqrt(max(lam2, 0.0))
        fwhm_major = 2.3548 * sig_major
        fwhm_minor = 2.3548 * sig_minor

        roundness = sig_minor / sig_major if sig_major > 0 else 0.0
        angle = 0.5 * np.degrees(np.arctan2(2 * mu11, mu20 - mu02))

        results.append({'y': cy, 'x': cx,
                        'roundness': float(np.clip(roundness, 0.0, 1.0)),
                        'fwhm_major': float(fwhm_major),
                        'fwhm_minor': float(fwhm_minor),
                        'angle_deg': float(angle)})
    return results


def analyze_channel(ch_name, img, header_info=None, workers=4, star_peaks=None):
    """
    Analyzes a single 2D image plane.
    """
    h, w = img.shape
    total_pixels = h * w

    bg_res = compute_bg_and_sigma_clip(img)
    nh = compute_diff_noise_h(img)
    nv = compute_diff_noise_v(img)
    hf_noise = 0.5 * (nh + nv)

    bg_median = bg_res['bg_median']
    sigma_mad = bg_res['sigma_mad']
    min_val = bg_res['min_val']
    max_val = bg_res['max_val']
    mean_val = bg_res['mean_val']
    std_val = bg_res['std_val']
    bg_mean = bg_res['bg_mean']

    # Signal to Noise Metrics
    snr_bg_mad = bg_median / sigma_mad if sigma_mad > 0 else 0
    snr_bg_hf = bg_median / hf_noise if hf_noise > 0 else 0

    # Net astronomical signal and dispersion on subsample to eliminate 100MB allocations
    sample = bg_res.get('sample')
    if sample is None:
        sample = img.ravel()

    mean_signal_above_bg = float(np.mean(np.maximum(sample - bg_median, 0)))
    snr_signal = mean_signal_above_bg / hf_noise if hf_noise > 0 else 0
    snr_signal_db = 20 * np.log10(max(snr_signal, 1e-6))

    # PixInsight-style relative dispersion SNR (AvgDev / Noise)
    mean_dev = float(np.mean(np.abs(sample - bg_median)))
    snr_pixinsight = mean_dev / hf_noise if hf_noise > 0 else 0
    snr_pixinsight_db = 20 * np.log10(max(snr_pixinsight, 1e-6))

    # Star roundness measurement
    if star_peaks is None:
        star_peaks = find_star_peaks(img, bg_median, sigma_mad)
    star_roundness = measure_star_roundness(img, star_peaks)
    num_stars = len(star_roundness)
    if num_stars > 0:
        r_vals = [s['roundness'] for s in star_roundness]
        avg_roundness = float(np.mean(r_vals))
        med_roundness = float(np.median(r_vals))
        min_roundness = float(np.min(r_vals))
        max_roundness = float(np.max(r_vals))
        fwhm_maj = [s['fwhm_major'] for s in star_roundness]
        fwhm_min = [s['fwhm_minor'] for s in star_roundness]
        avg_fwhm = float(np.mean(fwhm_maj))
        med_fwhm = float(np.median(fwhm_maj))
        min_fwhm = float(np.min(fwhm_min))
        max_fwhm = float(np.max(fwhm_maj))
    else:
        avg_roundness = med_roundness = min_roundness = max_roundness = 0.0
        avg_fwhm = med_fwhm = min_fwhm = max_fwhm = 0.0

    out = []
    out.append(f"--- Analysis for {ch_name} ---")
    out.append(f"Dimensions: {w} x {h} ({total_pixels:,} pixels)")
    out.append(f"Pixel values: Min = {format_val(min_val)}, Max = {format_val(max_val)}, Raw Mean = {format_val(mean_val)}, Raw Std = {format_val(std_val)}")
    out.append(f"Sky Background Level (Median): {format_val(bg_median)} ADU")
    out.append(f"Sky Background Level (Mean, 3-sigma clipped): {format_val(bg_mean)} ADU")
    out.append(f"Background Noise (MAD estimate): {format_val(sigma_mad)} ADU")
    out.append(f"High-Frequency Noise (Neighbor-diff): {format_val(hf_noise)} ADU")
    snr_db = 20 * np.log10(max(snr_bg_hf, 1e-6))
    out.append(f"Background SNR (Background / Noise): {snr_bg_hf:.2f} ({snr_db:.2f} dB)")
    out.append(f"Total Image Signal SNR (Net Signal / Noise): {snr_signal:.2f} ({snr_signal_db:.2f} dB)")
    out.append(f"PixInsight Relative SNR (AvgDev / Noise): {snr_pixinsight:.2f} ({snr_pixinsight_db:.2f} dB)")
    out.append(f"Star Roundness (1.0=round): avg={avg_roundness:.3f}  median={med_roundness:.3f}  min={min_roundness:.3f}  max={max_roundness:.3f}")
    out.append(f"Star FWHM (px):             avg={avg_fwhm:.2f}  median={med_fwhm:.2f}  min={min_fwhm:.2f}  max={max_fwhm:.2f}")

    return {
        'channel': ch_name,
        'output_text': "\n".join(out),
        'bg_median': bg_median,
        'bg_mean': bg_mean,
        'sigma_mad': sigma_mad,
        'bg_noise': hf_noise,
        'snr_bg_hf': snr_bg_hf,
        'snr_db': snr_db,
        'snr_signal': snr_signal,
        'snr_signal_db': snr_signal_db,
        'snr_pixinsight': snr_pixinsight,
        'snr_pixinsight_db': snr_pixinsight_db,
        'mean_signal': mean_signal_above_bg,
        'mean_dev': mean_dev,
        'star_count': num_stars,
        'star_roundness_avg': avg_roundness,
        'star_roundness_median': med_roundness,
        'star_roundness_min': min_roundness,
        'star_roundness_max': max_roundness,
        'star_fwhm_avg': avg_fwhm,
        'star_fwhm_median': med_fwhm,
        'star_fwhm_min': min_fwhm,
        'star_fwhm_max': max_fwhm,
        'star_details': star_roundness
    }


def analyze_fits(filepath, workers=None, dtype=np.float32, quiet=False):
    """
    Opens and analyzes a single FITS image.
    Uses multi-channel concurrency if 3D, and multi-core subtask concurrency per channel.
    """
    filepath = os.path.expanduser(filepath)
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        return None

    try:
        from astropy.io import fits
    except ImportError:
        print("Error: astropy is required. Installing or running in appropriate venv.", file=sys.stderr)
        return None

    if workers is None:
        workers = os.cpu_count() or 4

    out_lines = []
    out_lines.append(f"Opening {filepath}...")
    with fits.open(filepath, memmap=False) as hdul:
        # Capture HDU info string cleanly
        import io
        buf = io.StringIO()
        hdul.info(output=buf)
        out_lines.append(buf.getvalue().rstrip())

        data = None
        header = None
        for i, hdu in enumerate(hdul):
            if hdu.data is not None:
                data = hdu.data
                header = hdu.header
                out_lines.append(f"Using HDU {i} ({hdu.name}, shape={data.shape}, dtype={data.dtype})")
                break

        if data is None:
            print(f"Error: No image data found in FITS extensions for {filepath}", file=sys.stderr)
            return None

    keys_to_check = ['EXPTIME', 'EXPOSURE', 'GAIN', 'EGAIN', 'ISOSPEED', 'READNOIS', 'BAYERPAT', 'FILTER', 'OBJECT', 'INSTRUME', 'TELESCOP']
    header_info = {k: header.get(k) for k in keys_to_check if k in header}
    out_lines.append(f"Relevant Header Keywords: {header_info}")

    # Convert to floating point (avoid unnecessary copy if already float32)
    data = data.astype(dtype, copy=False)

    channels = {}
    if data.ndim == 2:
        channels['Monochrome/Raw'] = data
    elif data.ndim == 3:
        if data.shape[0] in [3, 4]:
            for c_idx in range(data.shape[0]):
                channels[f'Channel {c_idx}'] = np.ascontiguousarray(data[c_idx])
        elif data.shape[2] in [3, 4]:
            for c_idx in range(data.shape[2]):
                channels[f'Channel {c_idx}'] = np.ascontiguousarray(data[:, :, c_idx])
        else:
            channels['Slice 0'] = np.ascontiguousarray(data[0])

    num_channels = len(channels)
    results = []

    if num_channels > 1:
        # Hierarchical concurrency: analyze each channel concurrently across CPU cores
        channel_workers = max(1, workers // num_channels)
        with ThreadPoolExecutor(max_workers=min(num_channels, workers)) as ch_pool:
            future_to_ch = {
                ch_pool.submit(analyze_channel, ch_name, img, header_info, channel_workers): ch_name
                for ch_name, img in channels.items()
            }
            ch_results = {future_to_ch[f]: f.result() for f in future_to_ch}
            for ch_name in channels.keys():
                res = ch_results[ch_name]
                out_lines.append(f"\n{res['output_text']}")
                res['filepath'] = filepath
                res['header_info'] = header_info
                results.append(res)
    else:
        for ch_name, img in channels.items():
            res = analyze_channel(ch_name, img, header_info, workers=workers)
            out_lines.append(f"\n{res['output_text']}")
            res['filepath'] = filepath
            res['header_info'] = header_info
            results.append(res)

    # Build Total Image Summary
    total_summary = []
    total_summary.append("=" * 70)
    total_summary.append("                       TOTAL IMAGE SNR & SUMMARY")
    total_summary.append("=" * 70)

    if num_channels > 1:
        # Co-added quadrature background SNR across all channels: sqrt(sum(SNR_i^2))
        snr_quad = float(np.sqrt(sum(r['snr_bg_hf']**2 for r in results)))
        snr_quad_db = float(20 * np.log10(max(snr_quad, 1e-6)))

        # Combined luminance plane (standard Rec.709 photometric weights in float32)
        ch_list = list(channels.values())
        if num_channels == 3:
            w0, w1, w2 = np.float32(0.2126), np.float32(0.7152), np.float32(0.0722)
            lum = ch_list[0] * w0 + ch_list[1] * w1 + ch_list[2] * w2
            combo_type = "3-Channel Color / RGB"
        else:
            lum = np.mean(ch_list, axis=0).astype(dtype)
            combo_type = f"{num_channels}-Channel Composite"

        lum_bg_res = compute_bg_and_sigma_clip(lum)
        lum_nh = compute_diff_noise_h(lum)
        lum_nv = compute_diff_noise_v(lum)
        lum_hf_noise = float(0.5 * (lum_nh + lum_nv))

        lum_bg_med = float(lum_bg_res['bg_median'])
        lum_snr_bg = float(lum_bg_med / lum_hf_noise if lum_hf_noise > 0 else 0)
        lum_snr_bg_db = float(20 * np.log10(max(lum_snr_bg, 1e-6)))

        lum_sample = lum_bg_res.get('sample')
        if lum_sample is None:
            lum_sample = lum.ravel()

        lum_mean_sig = float(np.mean(np.maximum(lum_sample - lum_bg_med, 0)))
        lum_snr_sig = float(lum_mean_sig / lum_hf_noise if lum_hf_noise > 0 else 0)
        lum_snr_sig_db = float(20 * np.log10(max(lum_snr_sig, 1e-6)))

        lum_mean_dev = float(np.mean(np.abs(lum_sample - lum_bg_med)))
        lum_snr_pi = float(lum_mean_dev / lum_hf_noise if lum_hf_noise > 0 else 0)
        lum_snr_pi_db = float(20 * np.log10(max(lum_snr_pi, 1e-6)))

        ch_summary = " | ".join([f"{r['channel']}: {r['snr_bg_hf']:.2f} ({r['snr_db']:.2f} dB)" for r in results])

        total_summary.append(f"Image Type:                     {combo_type} ({lum.shape[1]} x {lum.shape[0]} px)")
        total_summary.append(f"Total Image Background SNR:     {lum_snr_bg:.2f} ({lum_snr_bg_db:.2f} dB) [Luminance]")
        total_summary.append(f"Co-added Image Background SNR:  {snr_quad:.2f} ({snr_quad_db:.2f} dB) [Quadrature Sum]")
        total_summary.append(f"Total Image Signal SNR:         {lum_snr_sig:.2f} ({lum_snr_sig_db:.2f} dB) [Net Astronomical Signal / Noise]")
        total_summary.append(f"PixInsight Relative SNR:        {lum_snr_pi:.2f} ({lum_snr_pi_db:.2f} dB) [AvgDev / Noise]")
        total_summary.append(f"Per-Channel Background SNR:     {ch_summary}")

        summary_data = {
            'type': combo_type,
            'lum_snr_bg': lum_snr_bg,
            'lum_snr_bg_db': lum_snr_bg_db,
            'snr_quad': snr_quad,
            'snr_quad_db': snr_quad_db,
            'lum_snr_sig': lum_snr_sig,
            'lum_snr_sig_db': lum_snr_sig_db,
            'lum_snr_pi': lum_snr_pi,
            'lum_snr_pi_db': lum_snr_pi_db
        }
    else:
        res = results[0]
        ch_img = list(channels.values())[0]
        h, w = ch_img.shape[:2]
        total_summary.append(f"Image Type:                     Monochrome / Single-Channel ({w} x {h} px)")
        total_summary.append(f"Total Image Background SNR:     {res['snr_bg_hf']:.2f} ({res['snr_db']:.2f} dB)")
        total_summary.append(f"Total Image Signal SNR:         {res['snr_signal']:.2f} ({res['snr_signal_db']:.2f} dB) [Net Astronomical Signal / Noise]")
        total_summary.append(f"PixInsight Relative SNR:        {res['snr_pixinsight']:.2f} ({res['snr_pixinsight_db']:.2f} dB) [AvgDev / Noise]")

        summary_data = {
            'type': 'Monochrome',
            'snr_bg': res['snr_bg_hf'],
            'snr_bg_db': res['snr_db'],
            'snr_signal': res['snr_signal'],
            'snr_signal_db': res['snr_signal_db'],
            'snr_pixinsight': res['snr_pixinsight'],
            'snr_pixinsight_db': res['snr_pixinsight_db']
        }

    # Aggregate star roundness and FWHM across all channels
    star_counts = [r.get('star_count', 0) for r in results]
    avg_stars = int(round(np.mean(star_counts))) if star_counts else 0
    all_details = []
    for r in results:
        all_details.extend(r.get('star_details', []))
    if all_details:
        all_r = [s['roundness'] for s in all_details]
        all_fwhm_maj = [s['fwhm_major'] for s in all_details]
        all_fwhm_min = [s['fwhm_minor'] for s in all_details]
        total_summary.append(f"Star Roundness (1.0=round):     avg={np.mean(all_r):.3f}  median={np.median(all_r):.3f}  min={np.min(all_r):.3f}  max={np.max(all_r):.3f}")
        total_summary.append(f"Star FWHM (px):                 avg={np.mean(all_fwhm_maj):.2f}  median={np.median(all_fwhm_maj):.2f}  min={np.min(all_fwhm_min):.2f}  max={np.max(all_fwhm_maj):.2f}")
        summary_data['star_count'] = avg_stars
        summary_data['star_roundness_avg'] = float(np.mean(all_r))
        summary_data['star_roundness_median'] = float(np.median(all_r))
        summary_data['star_fwhm_avg'] = float(np.mean(all_fwhm_maj))
        summary_data['star_fwhm_median'] = float(np.median(all_fwhm_maj))
    else:
        pass

    total_summary.append("=" * 70)
    summary_text = "\n" + "\n".join(total_summary)
    out_lines.append(summary_text)

    for r in results:
        r['total_summary'] = summary_data

    if not quiet:
        print("\n".join(out_lines))

    return results


def analyze_directory(directory, workers=None, reject_pct=None, recursive=False, show_summary=True, summary_sink=None):
    """
    Analyzes every FITS file in ``directory`` (sorted) and prints a combined
    summary table. Optionally flags the worst ``reject_pct`` of images by a
    composite quality score (SNR, star count, roundness, FWHM) so you can
    exclude them from a stack. Returns a list of (filepath, results) tuples,
    or None on hard failure.
    """
    directory = os.path.expanduser(directory)
    if not os.path.isdir(directory):
        print(f"Error: Not a directory: {directory}", file=sys.stderr)
        return None

    fits_exts = ('.fits', '.fit', '.fts', '.fz')

    if recursive:
        target_dirs = sorted(
            root for root, _, files in os.walk(directory)
            if any(f.lower().endswith(fits_exts) for f in files)
        )
        sink = []
        all_results = []
        for d in target_dirs:
            print(f"\n{'#' * 70}\nDirectory: {d}\n{'#' * 70}")
            res = analyze_directory(d, workers=workers, reject_pct=reject_pct, recursive=False,
                                    show_summary=False, summary_sink=sink)
            if res:
                all_results.extend(res)
        # Print all directory summaries at the end, named by directory
        for d, text in sink:
            print(f"\n{'#' * 70}\nDirectory Summary: {d}\n{'#' * 70}")
            print(text)
        return all_results if all_results else None

    files = sorted(
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if f.lower().endswith(fits_exts)
    )
    if not files:
        print(f"Error: No FITS files found in {directory}", file=sys.stderr)
        return None

    print(f"Found {len(files)} FITS file(s) in {directory}")
    all_results = []
    for fpath in files:
        print(f"\n{'='*70}\nProcessing: {fpath}\n{'='*70}")
        res = analyze_fits(fpath, workers=workers, quiet=False)
        if res is not None:
            all_results.append((fpath, res))

    if not all_results:
        print("No FITS files could be analyzed.")
        return None

    # Combined summary table
    rows = []
    snrs, rounds, fwhms = [], [], []
    max_name_len = 0
    max_type_len = 0
    for fpath, res in all_results:
        s = res[0].get('total_summary', {}) if res else {}
        name = os.path.basename(fpath)
        max_name_len = max(max_name_len, len(name))
        snr = float(s.get('snr_pixinsight_db', s.get('lum_snr_pi_db', 0)) or 0)
        rnd = float(s.get('star_roundness_avg', 0) or 0)
        fwhm = float(s.get('star_fwhm_avg', 0) or 0)
        ftype = str(s.get('type', '?'))
        max_type_len = max(max_type_len, len(ftype))
        snrs.append(snr); rounds.append(rnd); fwhms.append(fwhm)
        rows.append({
            'name': name,
            'type': ftype,
            'snr': snr,
            'roundness': rnd,
            'fwhm': fwhm,
            'quality': 0.0,
        })

    # Composite quality score: normalize each metric to 0-1, average.
    # Higher quality = better for stacking. FWHM inverted (lower is better).
    max_snr = max(snrs) if snrs else 0.0
    max_fwhm = max(fwhms) if fwhms else 0.0
    for row in rows:
        q_snr = row['snr'] / max_snr if max_snr > 0 else 0.0
        q_round = row['roundness']
        q_fwhm = (1.0 - row['fwhm'] / max_fwhm) if max_fwhm > 0 else 0.0
        row['quality'] = float(np.clip((q_snr + q_round + q_fwhm) / 3.0, 0.0, 1.0))

    # Build format strings with dynamic file/type column widths (no truncation).
    fwidth = max(max_name_len, len("AVERAGE"))
    twidth = max(max_type_len, len("Type"))
    f_row = lambda row: f"{row['name']:<{fwidth}} {row['type']:<{twidth}} {row['snr']:>9.2f} {row['roundness']:>10.3f} {row['fwhm']:>8.2f} {row['quality']:>8.3f}"
    f_avg = f"{'AVERAGE':<{fwidth}} {'':<{twidth}} {float(np.mean(snrs)):>9.2f} {float(np.mean(rounds)):>10.3f} {float(np.mean(fwhms)):>8.2f} {float(np.mean([r['quality'] for r in rows])):>8.3f}"
    header = f"{'File':<{fwidth}} {'Type':<{twidth}} {'PI SNR(dB)':>10} {'Roundness':>10} {'FWHM':>8} {'Quality':>8}"

    table_lines = []
    table_lines.append(header)
    table_lines.append("-" * len(header))

    for row in rows:
        table_lines.append(f_row(row))

    if snrs:
        table_lines.append("-" * len(header))
        table_lines.append(f_avg)

    rows.sort(key=lambda r: r['quality'])

    if reject_pct is not None and rows:
        n_reject = max(1, int(np.ceil(len(rows) * reject_pct / 100.0)))
        n_reject = min(n_reject, len(rows))
        worst = rows[:n_reject]
        table_lines.append("-" * len(header))
        table_lines.append(f"                         WORST {reject_pct:.0f}% ({n_reject} file(s)) - consider excluding from stack")
        table_lines.append(header)
        table_lines.append("-" * len(header))
        for row in worst:
            table_lines.append(f_row(row))
        table_lines.append("=" * len(header))

    table_text = "\n".join(table_lines)

    if summary_sink is not None:
        summary_sink.append((directory, table_text))
    else:
        print(table_text)

    return all_results


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print(f"Usage: {os.path.basename(sys.argv[0])} <fits_file_or_dir> [workers] [--reject X%] [-r|--recursive]")
        sys.exit(0 if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help') else 1)

    target = None
    workers = os.cpu_count() or 4
    reject_pct = None
    recursive = False
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg in ('-j', '--workers', '--threads') and i + 1 < len(sys.argv):
            try:
                workers = int(sys.argv[i + 1])
            except ValueError:
                pass
            i += 2
        elif arg in ('-r', '--recursive'):
            recursive = True
            i += 1
        elif arg in ('--reject',) and i + 1 < len(sys.argv):
            raw = sys.argv[i + 1]
            try:
                if raw.endswith('%'):
                    reject_pct = float(raw[:-1])
                else:
                    reject_pct = float(raw)
                if not 0 < reject_pct <= 100:
                    print("Error: --reject must be between 1 and 100", file=sys.stderr)
                    sys.exit(1)
            except ValueError:
                pass
            i += 2
        elif arg.startswith('--reject='):
            try:
                raw = arg.split('=', 1)[1]
                reject_pct = float(raw.rstrip('%'))
                if not 0 < reject_pct <= 100:
                    print("Error: --reject must be between 1 and 100", file=sys.stderr)
                    sys.exit(1)
            except ValueError:
                pass
            i += 1
        elif arg.isdigit():
            workers = int(arg)
            i += 1
        else:
            target = arg
            i += 1

    if target is None:
        print("Error: No FITS file or directory specified", file=sys.stderr)
        sys.exit(1)

    t_start = time.perf_counter()

    if os.path.isdir(target):
        all_results = analyze_directory(target, workers=workers, reject_pct=reject_pct, recursive=recursive)
        ok = all_results is not None and len(all_results) > 0
    else:
        res = analyze_fits(target, workers=workers)
        ok = res is not None

    t_total = time.perf_counter() - t_start

    if not ok:
        sys.exit(1)

    print(f"\n[Completed in {t_total:.2f}s using {workers} CPU cores]")


if __name__ == '__main__':
    main()
