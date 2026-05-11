package com.scalerpro.phantomfleet

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import com.scalerpro.phantomfleet.accessibility.IGEngagementHandler
import com.scalerpro.phantomfleet.accessibility.IGStoryFeatureHandler
import com.scalerpro.phantomfleet.accessibility.InstagramPostHandler
import com.scalerpro.phantomfleet.accessibility.ThreadsActionHandler
import com.scalerpro.phantomfleet.accessibility.TikTokActionHandler
import com.scalerpro.phantomfleet.camera.VirtualCameraService
import com.scalerpro.phantomfleet.http.LocalHttpServer

/**
 * Phantom Fleet Accessibility Service — the driver behind every UI action.
 *
 * Lifecycle:
 *  - [onServiceConnected]: spins up the [LocalHttpServer] on port 8090 and
 *    starts the [VirtualCameraService] foreground service.
 *  - [onInterrupt] / [onUnbind]: shuts both down cleanly.
 *
 * All gestures use [GestureDescription] so we can encode the persona's
 * biometric curves (Bezier swipes, LogNormal tap dwell, tap offset noise).
 *
 * The HTTP server holds a reference to [TikTokActionHandler] (which requires
 * the service instance) and to [VirtualCameraService] (resolved through the
 * singleton pattern).
 */
class PhantomAccessibilityService : AccessibilityService() {

    private val TAG = "PhantomFleet"

    private lateinit var tikTokHandler: TikTokActionHandler
    private lateinit var instagramPostHandler: InstagramPostHandler
    private lateinit var igStoryFeatureHandler: IGStoryFeatureHandler
    private lateinit var igEngagementHandler: IGEngagementHandler
    private lateinit var threadsHandler: ThreadsActionHandler
    private lateinit var httpServer: LocalHttpServer

    // ──────────────────────────────────────────────────────────────────────────
    // Lifecycle
    // ──────────────────────────────────────────────────────────────────────────

    override fun onServiceConnected() {
        Log.i(TAG, "Phantom Fleet Accessibility Service connected")

        // Build handlers now that 'this' (the service) is ready
        tikTokHandler          = TikTokActionHandler(service = this)
        instagramPostHandler   = InstagramPostHandler(service = this)
        igStoryFeatureHandler  = IGStoryFeatureHandler(service = this)
        igEngagementHandler    = IGEngagementHandler(service = this)
        threadsHandler         = ThreadsActionHandler(service = this)

        val virtualCamera = VirtualCameraService()
        // Start the virtual camera as a bound foreground service
        VirtualCameraService.start(applicationContext)

        httpServer = LocalHttpServer(
            context               = applicationContext,
            service               = this,
            tikTokHandler         = tikTokHandler,
            instagramPostHandler  = instagramPostHandler,
            igStoryFeatureHandler = igStoryFeatureHandler,
            igEngagementHandler   = igEngagementHandler,
            threadsHandler        = threadsHandler,
            virtualCamera         = virtualCamera,
        )
        httpServer.start()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // Phase 1: events are consumed by TikTokActionHandler / future Instagram handler
        // via rootInActiveWindow — no polling required here.
    }

    override fun onInterrupt() {
        Log.d(TAG, "PhantomFleet accessibility service interrupted")
        shutDown()
    }

    override fun onUnbind(intent: Intent?): Boolean {
        shutDown()
        return super.onUnbind(intent)
    }

    private fun shutDown() {
        if (::httpServer.isInitialized) httpServer.stop()
        VirtualCameraService.stop(applicationContext)
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Gesture primitives (shared across action handlers)
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Dispatches a tap at (x, y) with persona-biometric dwell time.
     *
     * @param x       Screen X coordinate in pixels.
     * @param y       Screen Y coordinate in pixels.
     * @param dwellMs Contact duration in milliseconds (simulates finger press time).
     */
    fun tapAt(x: Float, y: Float, dwellMs: Long = 100) {
        val path = Path().apply { moveTo(x, y) }
        val stroke = GestureDescription.StrokeDescription(path, 0, dwellMs)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()
        dispatchGesture(gesture, null, null)
    }

    /**
     * Dispatches a swipe gesture from (x1, y1) to (x2, y2) over [durationMs].
     * Used for reel scrolling, story advancing, and general scroll operations.
     *
     * @param x1         Start X coordinate in pixels.
     * @param y1         Start Y coordinate in pixels.
     * @param x2         End X coordinate in pixels.
     * @param y2         End Y coordinate in pixels.
     * @param durationMs Duration of the swipe gesture in milliseconds.
     */
    fun swipe(x1: Float, y1: Float, x2: Float, y2: Float, durationMs: Long = 300) {
        val path = Path().apply { moveTo(x1, y1); lineTo(x2, y2) }
        val stroke = GestureDescription.StrokeDescription(path, 0, durationMs)
        dispatchGesture(GestureDescription.Builder().addStroke(stroke).build(), null, null)
    }

    /**
     * Simulates the hardware Back button.
     * Used by engagement handlers to exit profiles, post views, and story viewers.
     */
    fun pressBack() {
        performGlobalAction(GLOBAL_ACTION_BACK)
    }

    /**
     * Simulates the hardware Home button.
     * Used as a recovery action when the UI is in an unexpected state.
     */
    fun pressHome() {
        performGlobalAction(GLOBAL_ACTION_HOME)
    }

}
