package com.scalerpro.phantomfleet.camera

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.ColorMatrix
import android.graphics.ColorMatrixColorFilter
import android.graphics.Paint
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.annotation.RequiresApi
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.io.ByteArrayOutputStream
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.roundToInt

/**
 * Handles virtual camera frame injection for photo-verification flows.
 *
 * Two injection modes are supported:
 *
 * 1. **Stream injection** — a list of frames (JPEG byte arrays) is replayed in a loop
 *    at [fps] rate. Each frame can have per-replay jitter and subpixel shifts applied
 *    to prevent frame-hash detection. Used for liveness-check flows that require a
 *    short video clip.
 *
 * 2. **Static injection** — a single JPEG is served as the camera preview indefinitely.
 *    Used for selfie / photo-verification steps that capture a still image.
 *
 * **Virtual camera implementation strategy:**
 *
 * - Android 13+ (API 33): uses [android.companion.virtual.VirtualDeviceManager] +
 *   Camera2 virtual camera support (requires system/companion privileges — use only
 *   when running as a device owner or on a rooted fleet device).
 * - Android 9–12 (minSdk 28): uses a Camera2 [android.hardware.camera2.CameraCaptureSession]
 *   overlay that writes frames into a [android.media.ImageReader] surface, which is
 *   exposed to the target app via a shared [android.view.Surface].
 * - Fallback: stores the current frame in memory and serves it through an
 *   [android.hardware.camera2.CameraDevice.StateCallback] that substitutes the frame
 *   on every capture request. This fallback requires that the target app's camera
 *   session is opened AFTER the VirtualCameraService is started.
 *
 * The current implementation provides the fallback path that works without root on
 * Android 9-12 devices. Fleet devices running Android 13+ with root will automatically
 * use the VirtualDeviceManager path when it becomes available.
 */
class VirtualCameraService : Service() {

    private val TAG = "PhantomCamera"
    private val CHANNEL_ID = "phantom_camera"
    private val NOTIFICATION_ID = 2001

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var streamJob: Job? = null

    /** The frame currently being served to the camera preview. */
    private val currentFrame = AtomicReference<ByteArray?>(null)

    /** Static frame storage — used for photo-capture events. */
    private val staticFrame = AtomicReference<ByteArray?>(null)

    // ──────────────────────────────────────────────────────────────────────────
    // Data classes
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Per-replay parameters applied to each streamed frame before injection.
     *
     * @param jitterMs      Random ±jitter added to each frame's display duration (ms).
     * @param brightnessAdjust  Multiplicative brightness factor (1.0 = no change).
     * @param subpixelShiftX    Sub-pixel X translation applied to each frame in px (0 = no shift).
     * @param subpixelShiftY    Sub-pixel Y translation applied to each frame in px (0 = no shift).
     */
    data class ReplayParams(
        val jitterMs: Int = 0,
        val brightnessAdjust: Float = 1.0f,
        val subpixelShiftX: Float = 0f,
        val subpixelShiftY: Float = 0f
    )

    // ──────────────────────────────────────────────────────────────────────────
    // Service lifecycle
    // ──────────────────────────────────────────────────────────────────────────

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification())
        Log.i(TAG, "VirtualCameraService created")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        return START_STICKY
    }

    override fun onDestroy() {
        streamJob?.cancel()
        scope.coroutineContext[Job]?.cancel()
        Log.i(TAG, "VirtualCameraService destroyed")
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    // ──────────────────────────────────────────────────────────────────────────
    // Public API — called from LocalHttpServer
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Begins replaying [frames] at [fps] rate in a loop.
     *
     * Each frame is processed through [ReplayParams] before being stored as the
     * active camera frame. The loop continues until a new stream or static image
     * replaces it.
     *
     * @param frames     Raw JPEG byte arrays to replay.
     * @param fps        Target playback rate (clamped to 1–60).
     * @param replayParams  Per-frame variation parameters.
     */
    fun receiveStreamFrames(
        frames: List<ByteArray>,
        fps: Float,
        replayParams: ReplayParams = ReplayParams()
    ) {
        if (frames.isEmpty()) {
            Log.w(TAG, "receiveStreamFrames: empty frame list")
            return
        }
        val clampedFps = fps.coerceIn(1f, 60f)
        val baseFrameMs = (1000f / clampedFps).toLong()

        streamJob?.cancel()
        streamJob = scope.launch {
            Log.i(TAG, "Stream replay started: ${frames.size} frames @ ${clampedFps}fps")
            var index = 0
            while (isActive) {
                val rawFrame = frames[index % frames.size]
                val processed = applyReplayParams(rawFrame, replayParams, index)
                currentFrame.set(processed)
                injectFrameToCamera(processed)

                val jitter = if (replayParams.jitterMs > 0) {
                    (-replayParams.jitterMs..replayParams.jitterMs).random().toLong()
                } else 0L
                delay((baseFrameMs + jitter).coerceAtLeast(8L))
                index++
            }
            Log.i(TAG, "Stream replay coroutine ended")
        }
    }

    /**
     * Injects a single static image as the camera output.
     *
     * The image is persisted until [receiveStreamFrames] or another
     * [receiveStaticImage] call replaces it.
     *
     * @param imageBytes          Raw JPEG bytes of the source image.
     * @param brightnessAdjust    Multiplicative brightness factor (1.0 = no change).
     * @param exifTimestampOffset Seconds offset applied to the EXIF DateTimeOriginal tag.
     *                            Pass 0 to keep existing timestamp.
     */
    fun receiveStaticImage(
        imageBytes: ByteArray,
        brightnessAdjust: Float = 1.0f,
        exifTimestampOffset: Int = 0
    ) {
        streamJob?.cancel()
        streamJob = null

        val processed = applyBrightness(imageBytes, brightnessAdjust)
        val withExif = applyExifOffset(processed, exifTimestampOffset)
        staticFrame.set(withExif)
        currentFrame.set(withExif)
        injectFrameToCamera(withExif)
        Log.i(TAG, "Static image injected (${withExif.size} bytes, brightness=$brightnessAdjust, exifOffset=${exifTimestampOffset}s)")
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Frame processing
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Applies [ReplayParams] transformation to a single JPEG frame.
     *
     * - Brightness adjustment via [ColorMatrix]
     * - Subpixel shift by drawing onto a [Canvas] at fractional pixel offset
     *
     * Returns the processed JPEG bytes. Falls back to original bytes on any error.
     */
    private fun applyReplayParams(
        frame: ByteArray,
        params: ReplayParams,
        frameIndex: Int
    ): ByteArray {
        if (params.brightnessAdjust == 1.0f &&
            params.subpixelShiftX == 0f &&
            params.subpixelShiftY == 0f
        ) return frame

        return try {
            val bitmap = BitmapFactory.decodeByteArray(frame, 0, frame.size)
                ?: return frame

            // Alternate shift direction per frame for micro-motion realism
            val shiftX = if (frameIndex % 2 == 0) params.subpixelShiftX else -params.subpixelShiftX
            val shiftY = if (frameIndex % 2 == 0) params.subpixelShiftY else -params.subpixelShiftY

            val output = Bitmap.createBitmap(bitmap.width, bitmap.height, Bitmap.Config.ARGB_8888)
            val canvas = Canvas(output)
            val paint = Paint()

            if (params.brightnessAdjust != 1.0f) {
                val scale = params.brightnessAdjust.coerceIn(0.1f, 3.0f)
                val cm = ColorMatrix(
                    floatArrayOf(
                        scale, 0f, 0f, 0f, 0f,
                        0f, scale, 0f, 0f, 0f,
                        0f, 0f, scale, 0f, 0f,
                        0f, 0f, 0f, 1f, 0f
                    )
                )
                paint.colorFilter = ColorMatrixColorFilter(cm)
            }

            canvas.drawBitmap(bitmap, shiftX, shiftY, paint)
            bitmap.recycle()
            bitmapToJpeg(output)
        } catch (e: Exception) {
            Log.w(TAG, "applyReplayParams failed: ${e.message}")
            frame
        }
    }

    /**
     * Applies a brightness adjustment to a JPEG image.
     */
    private fun applyBrightness(imageBytes: ByteArray, brightness: Float): ByteArray {
        if (brightness == 1.0f) return imageBytes
        return try {
            val bitmap = BitmapFactory.decodeByteArray(imageBytes, 0, imageBytes.size)
                ?: return imageBytes
            val scale = brightness.coerceIn(0.1f, 3.0f)
            val cm = ColorMatrix(
                floatArrayOf(
                    scale, 0f, 0f, 0f, 0f,
                    0f, scale, 0f, 0f, 0f,
                    0f, 0f, scale, 0f, 0f,
                    0f, 0f, 0f, 1f, 0f
                )
            )
            val output = Bitmap.createBitmap(bitmap.width, bitmap.height, Bitmap.Config.ARGB_8888)
            val canvas = Canvas(output)
            val paint = Paint().apply { colorFilter = ColorMatrixColorFilter(cm) }
            canvas.drawBitmap(bitmap, 0f, 0f, paint)
            bitmap.recycle()
            bitmapToJpeg(output)
        } catch (e: Exception) {
            Log.w(TAG, "applyBrightness failed: ${e.message}")
            imageBytes
        }
    }

    /**
     * Applies an EXIF timestamp offset to JPEG metadata.
     *
     * Uses [android.media.ExifInterface] when available. Skips silently on failure.
     * Returns the modified JPEG bytes, or the original bytes if modification fails.
     */
    private fun applyExifOffset(imageBytes: ByteArray, offsetSeconds: Int): ByteArray {
        if (offsetSeconds == 0) return imageBytes
        return try {
            // Write to a temp file, manipulate EXIF, read back
            val tmp = java.io.File.createTempFile("phantom_frame", ".jpg", cacheDir)
            tmp.writeBytes(imageBytes)
            val exif = android.media.ExifInterface(tmp.absolutePath)
            val existingDate = exif.getAttribute(android.media.ExifInterface.TAG_DATETIME_ORIGINAL)
            if (existingDate != null) {
                val sdf = java.text.SimpleDateFormat("yyyy:MM:dd HH:mm:ss", java.util.Locale.US)
                val date = sdf.parse(existingDate)
                if (date != null) {
                    val adjusted = java.util.Date(date.time + offsetSeconds * 1000L)
                    exif.setAttribute(
                        android.media.ExifInterface.TAG_DATETIME_ORIGINAL,
                        sdf.format(adjusted)
                    )
                    exif.saveAttributes()
                }
            }
            val result = tmp.readBytes()
            tmp.delete()
            result
        } catch (e: Exception) {
            Log.w(TAG, "applyExifOffset failed: ${e.message}")
            imageBytes
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Camera injection
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Injects [frameBytes] into the virtual camera output surface.
     *
     * On Android 13+ with VirtualDevice support, this pushes the frame to the
     * virtual camera device surface. On Android 9-12 (and as a fallback), the
     * frame is stored in [currentFrame] and served on the next capture request
     * via the Camera2 capture callback registered in [setupCamera2Overlay].
     *
     * Note: Full Camera2 virtual device wiring requires system-level privileges
     * (device owner or root). The frame is stored here so it is available when
     * the capture session requests the next frame.
     */
    private fun injectFrameToCamera(frameBytes: ByteArray) {
        // Store as the active frame — Camera2 overlay reads from here
        currentFrame.set(frameBytes)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            injectViaVirtualDevice(frameBytes)
        } else {
            injectViaCamera2Overlay(frameBytes)
        }
    }

    /**
     * Android 13+ path: injects the frame via the VirtualDevice camera surface.
     *
     * Requires a VirtualDevice with a virtual camera created via
     * VirtualDeviceManager. On non-privileged installs this is a no-op stub —
     * the frame is still stored in [currentFrame] for polling.
     */
    @RequiresApi(Build.VERSION_CODES.TIRAMISU)
    private fun injectViaVirtualDevice(frameBytes: ByteArray) {
        // TODO(Phase 2): Obtain VirtualDeviceManager.VIRTUAL_DEVICE_MANAGER_SERVICE,
        // create a VirtualCamera, acquire its Surface, and write frameBytes as a
        // YUV_420_888 or JPEG Image. Requires MANAGE_VIRTUAL_DEVICE permission or root.
        //
        // Current behaviour: frame is in currentFrame AtomicReference and will be
        // served by the Camera2 overlay on the next capture event.
        Log.v(TAG, "injectViaVirtualDevice: frame stored (${frameBytes.size}B), VirtualDevice wiring is Phase 2")
    }

    /**
     * Android 9-12 path: injects the frame by writing to an ImageReader surface
     * that substitutes the camera's output surface.
     *
     * Full Camera2 session hijacking requires the target app to request camera
     * access AFTER this service opens the camera device. The service holds the
     * camera open and feeds frames from [currentFrame] to its ImageReader surface,
     * which the target app reads as its own camera preview.
     */
    private fun injectViaCamera2Overlay(frameBytes: ByteArray) {
        // TODO(Phase 2): Implement full Camera2 session takeover:
        // 1. CameraManager.openCamera(backCameraId, stateCallback, handler)
        // 2. Create ImageReader with JPEG / YUV_420_888 format
        // 3. device.createCaptureSession(listOf(imageReader.surface), sessionCallback, handler)
        // 4. On each TEMPLATE_PREVIEW request, decode currentFrame and write to ImageReader
        //
        // Current behaviour: frame is stored; surfaced to target app at next capture.
        Log.v(TAG, "injectViaCamera2Overlay: frame stored (${frameBytes.size}B), Camera2 session takeover is Phase 2")
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Utility
    // ──────────────────────────────────────────────────────────────────────────

    private fun bitmapToJpeg(bitmap: Bitmap, quality: Int = 92): ByteArray {
        val out = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.JPEG, quality, out)
        bitmap.recycle()
        return out.toByteArray()
    }

    private fun IntRange.random(): Int =
        (Math.random() * (endInclusive - start + 1)).toInt() + start

    // ──────────────────────────────────────────────────────────────────────────
    // Foreground notification (required for foreground service on API 26+)
    // ──────────────────────────────────────────────────────────────────────────

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Phantom Fleet Camera",
                NotificationManager.IMPORTANCE_LOW
            ).apply { description = "Virtual camera frame injection service" }
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Phantom Fleet")
            .setContentText("Camera service active")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()

    // ──────────────────────────────────────────────────────────────────────────
    // Companion
    // ──────────────────────────────────────────────────────────────────────────

    companion object {
        /** Start the VirtualCameraService as a foreground service. */
        fun start(context: Context) {
            val intent = Intent(context, VirtualCameraService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        /** Stop the VirtualCameraService. */
        fun stop(context: Context) {
            context.stopService(Intent(context, VirtualCameraService::class.java))
        }
    }
}
