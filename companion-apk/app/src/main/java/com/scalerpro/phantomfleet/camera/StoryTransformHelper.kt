package com.scalerpro.phantomfleet.camera

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.ColorMatrix
import android.graphics.ColorMatrixColorFilter
import android.graphics.Paint
import android.util.Log
import java.io.ByteArrayOutputStream
import java.security.MessageDigest
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.roundToInt
import kotlin.math.sqrt

/**
 * Per-account visual transform pipeline for Instagram story images.
 *
 * Purpose: prevent content-cluster fingerprinting when many child accounts
 * repost the same mother-account story. 500 accounts posting an identical
 * image file (same pixel hash, same file size, same colour histogram) is a
 * detectable cohort-level signal for Meta's ML classifiers.
 *
 * These transforms create unique-but-similar versions of each frame that:
 *  - Pass human inspection (changes are imperceptible)
 *  - Diverge statistically (pixel hash, file size, colour histogram all differ)
 *  - Are DETERMINISTIC per (accountId, postIndex) — same inputs → same output,
 *    enabling reproducible debugging without losing fleet-level diversity
 *
 * Transform pipeline (applied in order):
 *  1. Brightness shift        — ±3–8% via LogNormal magnitude, random sign
 *  2. Subtle crop             — 0–2% trimmed from each edge (different framing)
 *  3. Hue rotation            — ±2–5° HSV hue shift (barely perceptible)
 *  4. Subpixel noise          — Normal(0, σ=2) per pixel channel (changes hash)
 *  5. JPEG re-encode quality  — 85–96% quality (seeded; varies file size signature)
 *
 * Fleet-scale detection analysis (CLAUDE.md 20K account thought experiment):
 *  - Brightness: LogNormal magnitude avoids rectangular distribution.
 *    Sign alternates via seed bit — 50/50 but deterministic per account.
 *  - Crop: deterministic per (accountId, postIndex) → every account crops
 *    a different amount from each edge → no two frames share framing.
 *  - Hue: ±2–5° is within human JND for most colours. ML pixel-hash
 *    comparison fails even at 1° shift.
 *  - Noise: σ=2 per channel (0–255 scale) is below human detection threshold
 *    but sufficient to flip dozens of pixel values, breaking any frame hash.
 *  - JPEG quality: file size varies 5–15% across accounts — destroys file-hash
 *    matching and avoids the "every image is exactly 284 KB" cluster tell.
 *
 * IMPORTANT: These transforms are intentionally imperceptible to humans.
 * They are purely anti-fingerprint noise, not creative edits.
 */
object StoryTransformHelper {

    private val TAG = "StoryTransform"

    // ──────────────────────────────────────────────────────────────────────────
    // Public entry point
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Apply per-account visual transforms to [inputBitmap].
     *
     * @param inputBitmap  Source image (will NOT be recycled; a new Bitmap is returned).
     * @param accountId    Account identifier — seeds all transform parameters.
     * @param postIndex    Monotone post counter — ensures different transforms each post.
     * @return             A new Bitmap with imperceptible but statistically unique changes.
     */
    fun transform(
        inputBitmap: Bitmap,
        accountId: String,
        postIndex: Int,
    ): Bitmap {
        Log.d(TAG, "transform: accountId=$accountId postIndex=$postIndex " +
                "size=${inputBitmap.width}×${inputBitmap.height}")

        // Build a reproducible seed from (accountId, postIndex)
        val seed = deterministicSeed(accountId, postIndex)
        val rng = SeededRng(seed)

        // ── 1. Brightness shift ───────────────────────────────────────────────
        // Magnitude: LogNormal(mu=ln(0.055), σ=0.35) → range ~3–8%
        // Sign: LSB of seed byte 8 → ±
        val brightnessMagnitude = logNormalDraw(rng, mu = ln(0.055), sigma = 0.35)
            .coerceIn(0.03, 0.08).toFloat()
        val brightnessSign = if (seed.ushr(56) and 1L == 1L) 1f else -1f
        val brightnessScale = 1f + (brightnessSign * brightnessMagnitude)

        // ── 2. Subtle crop ────────────────────────────────────────────────────
        // Each edge trimmed independently: 0–2% of the relevant dimension
        val cropFracLeft   = rng.nextFloat() * 0.02f
        val cropFracTop    = rng.nextFloat() * 0.02f
        val cropFracRight  = rng.nextFloat() * 0.02f
        val cropFracBottom = rng.nextFloat() * 0.02f

        val w = inputBitmap.width
        val h = inputBitmap.height
        val cropLeft   = (w * cropFracLeft).roundToInt()
        val cropTop    = (h * cropFracTop).roundToInt()
        val cropRight  = (w * cropFracRight).roundToInt()
        val cropBottom = (h * cropFracBottom).roundToInt()
        val croppedW   = (w - cropLeft - cropRight).coerceAtLeast(1)
        val croppedH   = (h - cropTop  - cropBottom).coerceAtLeast(1)

        // ── 3. Hue rotation ───────────────────────────────────────────────────
        // ±2–5° hue shift; sign from seed bit 57
        val hueDegrees = (2f + rng.nextFloat() * 3f) *
                if (seed.ushr(57) and 1L == 1L) 1f else -1f

        // ── 4. Subpixel noise σ ───────────────────────────────────────────────
        // σ drawn once: Normal(2, 0.5) clamped to [1, 4]
        val noiseSigma = gaussianDraw(rng, mean = 2.0, std = 0.5)
            .coerceIn(1.0, 4.0)

        // ── 5. JPEG quality ───────────────────────────────────────────────────
        // LogNormal(mu=ln(91), σ=0.04) → 85–96 range
        val jpegQuality = logNormalDraw(rng, mu = ln(91.0), sigma = 0.04)
            .coerceIn(85.0, 96.0).roundToInt()

        Log.d(TAG, "params: brightness=${String.format("%.4f", brightnessScale)} " +
                "crop=($cropLeft,$cropTop,$cropRight,$cropBottom) " +
                "hue=${String.format("%.2f", hueDegrees)}° " +
                "noiseSigma=${String.format("%.2f", noiseSigma)} " +
                "jpegQuality=$jpegQuality")

        // ── Apply transforms ──────────────────────────────────────────────────

        // Step A: crop
        val cropped = Bitmap.createBitmap(inputBitmap, cropLeft, cropTop, croppedW, croppedH)

        // Step B: brightness + hue via ColorMatrix on Canvas
        val colorFiltered = applyColorMatrix(cropped, brightnessScale, hueDegrees)
        if (cropped !== inputBitmap) cropped.recycle()

        // Step C: subpixel noise (modifies pixels in-place on a mutable copy)
        val withNoise = applySubpixelNoise(colorFiltered, noiseSigma, rng)
        colorFiltered.recycle()

        // Step D: JPEG re-encode to vary file signature
        val reEncoded = reEncodeAsJpeg(withNoise, jpegQuality)
        withNoise.recycle()

        Log.d(TAG, "transform complete: output=${reEncoded.width}×${reEncoded.height}")
        return reEncoded
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Step B: ColorMatrix — brightness + hue rotation
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Apply brightness scaling and hue rotation via Android's [ColorMatrix].
     *
     * Hue rotation is approximated using the standard 3×3 RGB rotation
     * decomposition (same approach as CSS filter: hue-rotate).
     * The matrix is constructed once and applied to all pixels via [Paint].
     */
    private fun applyColorMatrix(
        source: Bitmap,
        brightnessScale: Float,
        hueDegrees: Float,
    ): Bitmap {
        val dst = Bitmap.createBitmap(source.width, source.height, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(dst)

        // Build combined ColorMatrix: brightness × hue rotation
        val cm = ColorMatrix()

        // Brightness: scale RGB channels by brightnessScale
        cm.setScale(brightnessScale, brightnessScale, brightnessScale, 1f)

        // Hue rotation matrix (approximate RGB hue rotate)
        val hueRad = Math.toRadians(hueDegrees.toDouble()).toFloat()
        val cosH = kotlin.math.cos(hueRad.toDouble()).toFloat()
        val sinH = kotlin.math.sin(hueRad.toDouble()).toFloat()

        // Standard hue rotation matrix (from CSS filter spec, simplified for RGB)
        val hueMatrix = ColorMatrix(floatArrayOf(
            // R              G              B       A  offset
            0.213f + cosH * 0.787f - sinH * 0.213f,
            0.715f - cosH * 0.715f - sinH * 0.715f,
            0.072f - cosH * 0.072f + sinH * 0.928f, 0f, 0f,
            // G row
            0.213f - cosH * 0.213f + sinH * 0.143f,
            0.715f + cosH * 0.285f + sinH * 0.140f,
            0.072f - cosH * 0.072f - sinH * 0.283f, 0f, 0f,
            // B row
            0.213f - cosH * 0.213f - sinH * 0.787f,
            0.715f - cosH * 0.715f + sinH * 0.715f,
            0.072f + cosH * 0.928f + sinH * 0.072f, 0f, 0f,
            // A row (pass-through)
            0f, 0f, 0f, 1f, 0f,
        ))

        // Combine: first brightness, then hue
        cm.postConcat(hueMatrix)

        val paint = Paint().apply {
            colorFilter = ColorMatrixColorFilter(cm)
            isAntiAlias = false
        }

        canvas.drawBitmap(source, 0f, 0f, paint)
        return dst
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Step C: Subpixel noise
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Add Normal(0, [sigma]) noise to every pixel channel independently.
     *
     * Operates on a mutable ARGB_8888 Bitmap. Noise is generated via
     * Box-Muller using [rng] so it is reproducible for the same seed.
     *
     * σ=2 on a 0-255 scale is below human detection (~0.8% of range) but
     * sufficient to change dozens of pixel values per row, breaking any
     * perceptual hash comparison.
     */
    private fun applySubpixelNoise(
        source: Bitmap,
        sigma: Double,
        rng: SeededRng,
    ): Bitmap {
        // Work on a mutable copy
        val mutable = source.copy(Bitmap.Config.ARGB_8888, true)
        val pixels = IntArray(mutable.width * mutable.height)
        mutable.getPixels(pixels, 0, mutable.width, 0, 0, mutable.width, mutable.height)

        var i = 0
        while (i < pixels.size) {
            val px = pixels[i]
            val a = (px ushr 24) and 0xFF
            val r = (px ushr 16) and 0xFF
            val g = (px ushr  8) and 0xFF
            val b =  px          and 0xFF

            // Generate 3 gaussian samples (Box-Muller pairs — 2 per call → batch 3)
            val nr = gaussianDraw(rng, 0.0, sigma).roundToInt()
            val ng = gaussianDraw(rng, 0.0, sigma).roundToInt()
            val nb = gaussianDraw(rng, 0.0, sigma).roundToInt()

            val newR = (r + nr).coerceIn(0, 255)
            val newG = (g + ng).coerceIn(0, 255)
            val newB = (b + nb).coerceIn(0, 255)

            pixels[i] = (a shl 24) or (newR shl 16) or (newG shl 8) or newB
            i++
        }

        mutable.setPixels(pixels, 0, mutable.width, 0, 0, mutable.width, mutable.height)
        return mutable
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Step D: JPEG re-encode
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Encode [source] as JPEG at [quality] (85–96) and decode back to Bitmap.
     *
     * This step:
     *  - Varies file size (JPEG quality is the primary file-size determinant)
     *  - Applies JPEG DCT quantization noise (different per quality level)
     *  - Destroys any lossless hash relationship to the original
     *
     * The decode-and-return ensures the returned Bitmap reflects the exact
     * pixel values that will be stored in the file, not floating-point
     * intermediates.
     */
    private fun reEncodeAsJpeg(source: Bitmap, quality: Int): Bitmap {
        val baos = ByteArrayOutputStream()
        source.compress(Bitmap.CompressFormat.JPEG, quality, baos)
        val bytes = baos.toByteArray()
        return android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
            ?: source.copy(Bitmap.Config.ARGB_8888, false)  // fallback if decode fails
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Seeded RNG (deterministic, per-account)
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Build a deterministic 64-bit seed from (accountId, postIndex).
     *
     * Uses SHA-256 for diffusion so sequential accountIds don't produce
     * correlated seeds (same diffusion property as distributions.seed_for
     * in the Python backend).
     */
    private fun deterministicSeed(accountId: String, postIndex: Int): Long {
        val payload = "$accountId|$postIndex".toByteArray(Charsets.UTF_8)
        val digest = MessageDigest.getInstance("SHA-256").digest(payload)
        // Take first 8 bytes as a signed Long
        var seed = 0L
        for (i in 0..7) {
            seed = (seed shl 8) or (digest[i].toLong() and 0xFF)
        }
        return seed
    }

    /**
     * Lightweight LCG (Linear Congruential Generator) seeded deterministically.
     *
     * NOT cryptographically secure — this is intentional. The transform values
     * produced here are not secret, just deterministic. Using java.util.Random
     * with a fixed seed gives us exactly the reproducibility we need.
     */
    private class SeededRng(seed: Long) {
        private val rng = java.util.Random(seed)
        fun nextFloat(): Float = rng.nextFloat()
        fun nextDouble(): Double = rng.nextDouble()
        fun nextGaussian(): Double = rng.nextGaussian()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Distribution helpers
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Draw one value from LogNormal(mu, sigma) using [rng].
     * mu is the mean of the underlying Normal (NOT the mode of the LogNormal).
     */
    private fun logNormalDraw(rng: SeededRng, mu: Double, sigma: Double): Double {
        val z = gaussianDraw(rng, 0.0, 1.0)
        return exp(mu + sigma * z)
    }

    /**
     * Draw one value from Normal(mean, std) via Box-Muller using [rng].
     * Uses nextGaussian() from java.util.Random (already Box-Muller internally).
     */
    private fun gaussianDraw(rng: SeededRng, mean: Double, std: Double): Double {
        return mean + std * rng.nextGaussian()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Utility
    // ──────────────────────────────────────────────────────────────────────────

    /** Convenience: compress [bitmap] to JPEG [quality] and write to [outputPath]. */
    fun compressToFile(bitmap: Bitmap, outputPath: String, quality: Int = 92): Boolean {
        return try {
            java.io.FileOutputStream(outputPath).use { fos ->
                bitmap.compress(Bitmap.CompressFormat.JPEG, quality, fos)
            }
            true
        } catch (e: Exception) {
            Log.e(TAG, "compressToFile failed: $outputPath — ${e.message}")
            false
        }
    }
}
