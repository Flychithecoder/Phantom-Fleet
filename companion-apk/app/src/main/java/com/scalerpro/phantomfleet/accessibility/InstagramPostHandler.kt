package com.scalerpro.phantomfleet.accessibility

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.graphics.Rect
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.KeyEvent
import android.view.accessibility.AccessibilityNodeInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlin.math.ln
import kotlin.math.exp
import kotlin.math.sqrt

/**
 * Handles Instagram posting UI automation via the Android Accessibility API.
 *
 * Posts grid posts, stories, and reels by selecting media from the phone's
 * gallery (previously pushed via ADB) and interacting with the Instagram
 * UI exactly as a real user would.
 *
 * NEVER uses Meta's third-party media upload API — all posting goes through
 * the phone gallery + accessibility service. This makes the flow
 * indistinguishable from a real user posting from their camera roll.
 *
 * All timing uses LogNormal distributions (see [logNormalDelay]) to produce
 * fleet-wide histograms that match real human behaviour, not synthetic
 * rectangular distributions that Meta's ML classifier flags.
 *
 * Pattern follows [TikTokActionHandler] exactly.
 *
 * @param service The active [PhantomAccessibilityService] that owns gesture dispatch.
 */
class InstagramPostHandler(private val service: AccessibilityService) {

    private val TAG = "PhantomIGPost"

    // ──────────────────────────────────────────────────────────────────────────
    // Public types
    // ──────────────────────────────────────────────────────────────────────────

    enum class PostType { GRID, STORY, REEL }

    data class PostResult(val success: Boolean, val error: String? = null) {
        companion object {
            fun ok() = PostResult(true)
            fun fail(msg: String) = PostResult(false, msg)
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Main entry point
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Full Instagram posting flow — selects media from device gallery and posts
     * it via the Instagram accessibility UI.
     *
     * Must be called from a coroutine (uses [delay] for timing).
     *
     * @param mediaPath   Absolute on-device path, e.g. /sdcard/DCIM/PhantomFleet/xyz.jpg
     * @param caption     Full caption text to type character by character.
     * @param accountId   Account ID — used only for logging.
     * @param clonePackage Package name of the Instagram clone to launch.
     * @param postType    [PostType.GRID], [PostType.STORY], or [PostType.REEL].
     */
    suspend fun postFromGallery(
        mediaPath: String,
        caption: String,
        accountId: String,
        clonePackage: String,
        postType: PostType,
    ): PostResult {
        Log.i(TAG, "[$accountId] postFromGallery: type=$postType pkg=$clonePackage")

        // Step 1 — launch Instagram clone
        val launched = launchInstagram(clonePackage)
        if (!launched) {
            return PostResult.fail("launch_failed:could_not_start_$clonePackage")
        }
        // Wait for app to fully load: LogNormal(mean=2500ms, sigma=0.3)
        logNormalDelay(mean = 2500.0, sigma = 0.3)

        return when (postType) {
            PostType.GRID  -> postGrid(mediaPath, caption, accountId, clonePackage)
            PostType.STORY -> postStory(mediaPath, accountId, clonePackage)
            PostType.REEL  -> postReel(mediaPath, caption, accountId, clonePackage)
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // GRID posting flow
    // ──────────────────────────────────────────────────────────────────────────

    private suspend fun postGrid(
        mediaPath: String,
        caption: String,
        accountId: String,
        clonePackage: String,
    ): PostResult {

        // Step 2 — tap + button (new post)
        val plusTapResult = tapNewPostButton(clonePackage)
        if (!plusTapResult.success) return plusTapResult

        // Step 3 — wait for gallery to open
        logNormalDelay(mean = 1200.0, sigma = 0.3)

        // Step 4 — select most recent image from gallery
        val selectResult = selectMostRecentGalleryItem(clonePackage)
        if (!selectResult.success) return selectResult

        // Step 5 — tap "Next" (crop/size screen)
        logNormalDelay(mean = 800.0, sigma = 0.35)
        val next1 = tapButtonWithTextOrId(
            texts = listOf("Next", "NEXT"),
            ids = listOf(
                "$clonePackage:id/next_button_textview",
                "com.instagram.android:id/next_button_textview",
            ),
            step = "next_after_gallery",
        )
        if (!next1.success) return next1

        // Step 6 — "Next" on filter/crop screen
        logNormalDelay(mean = 600.0, sigma = 0.3)
        val next2 = tapButtonWithTextOrId(
            texts = listOf("Next", "NEXT"),
            ids = listOf(
                "$clonePackage:id/next_button_textview",
                "com.instagram.android:id/next_button_textview",
            ),
            step = "next_after_filter",
        )
        if (!next2.success) return next2

        // Step 7 — type caption
        logNormalDelay(mean = 1000.0, sigma = 0.35)
        if (caption.isNotBlank()) {
            val captionResult = typeCaption(caption, clonePackage)
            if (!captionResult.success) return captionResult
        }

        // Step 9 — tap "Share"
        logNormalDelay(mean = 400.0, sigma = 0.3)
        val shareResult = tapButtonWithTextOrId(
            texts = listOf("Share", "SHARE"),
            ids = listOf(
                "$clonePackage:id/share_footer_button",
                "com.instagram.android:id/share_footer_button",
            ),
            step = "share",
        )
        if (!shareResult.success) return shareResult

        // Step 10 — wait for confirmation (share button disappears or feed returns)
        val confirmed = waitForPostConfirmation(clonePackage, timeoutMs = 15_000)
        if (!confirmed) {
            Log.w(TAG, "[$accountId] share_timeout — post may have succeeded; treating as error")
            return PostResult.fail("share_timeout")
        }

        Log.i(TAG, "[$accountId] GRID post completed successfully")
        return PostResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // STORY posting flow
    // ──────────────────────────────────────────────────────────────────────────

    private suspend fun postStory(
        mediaPath: String,
        accountId: String,
        clonePackage: String,
    ): PostResult {

        // Tap + button
        val plusTapResult = tapNewPostButton(clonePackage)
        if (!plusTapResult.success) return plusTapResult

        logNormalDelay(mean = 1200.0, sigma = 0.3)

        // Switch to Story tab in the gallery view
        val storyTabResult = tapButtonWithTextOrId(
            texts = listOf("Story", "STORY"),
            ids = listOf(
                "$clonePackage:id/story_tab",
                "com.instagram.android:id/story_tab",
            ),
            step = "story_tab",
        )
        if (!storyTabResult.success) return storyTabResult

        logNormalDelay(mean = 800.0, sigma = 0.3)

        // Select most recent media
        val selectResult = selectMostRecentGalleryItem(clonePackage)
        if (!selectResult.success) return selectResult

        logNormalDelay(mean = 1000.0, sigma = 0.3)

        // Tap "Your Story" send button
        val sendResult = tapButtonWithTextOrId(
            texts = listOf("Your Story", "Your story", "Send To"),
            ids = listOf(
                "$clonePackage:id/share_to_story_button",
                "com.instagram.android:id/share_to_story_button",
            ),
            step = "send_to_story",
        )
        if (!sendResult.success) return sendResult

        val confirmed = waitForPostConfirmation(clonePackage, timeoutMs = 15_000)
        if (!confirmed) return PostResult.fail("share_timeout")

        Log.i(TAG, "[$accountId] STORY post completed successfully")
        return PostResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // REEL posting flow
    // ──────────────────────────────────────────────────────────────────────────

    private suspend fun postReel(
        mediaPath: String,
        caption: String,
        accountId: String,
        clonePackage: String,
    ): PostResult {

        // Tap + button
        val plusTapResult = tapNewPostButton(clonePackage)
        if (!plusTapResult.success) return plusTapResult

        logNormalDelay(mean = 1200.0, sigma = 0.3)

        // Switch to Reels tab
        val reelTabResult = tapButtonWithTextOrId(
            texts = listOf("Reels", "REELS", "Reel"),
            ids = listOf(
                "$clonePackage:id/reels_tab",
                "com.instagram.android:id/reels_tab",
            ),
            step = "reels_tab",
        )
        if (!reelTabResult.success) return reelTabResult

        logNormalDelay(mean = 800.0, sigma = 0.3)

        // Select most recent video from gallery
        val selectResult = selectMostRecentGalleryItem(clonePackage)
        if (!selectResult.success) return selectResult

        // If video > 60s, attempt to trim — tap trim handle at ~60s mark
        // The trim panel appears automatically for long videos
        logNormalDelay(mean = 1200.0, sigma = 0.35)
        tryTrimToSixtySeconds()

        // Tap "Next"
        logNormalDelay(mean = 800.0, sigma = 0.3)
        val next1 = tapButtonWithTextOrId(
            texts = listOf("Next", "NEXT"),
            ids = listOf(
                "$clonePackage:id/next_button_textview",
                "com.instagram.android:id/next_button_textview",
            ),
            step = "next_after_reel_select",
        )
        if (!next1.success) return next1

        // Caption screen
        logNormalDelay(mean = 1000.0, sigma = 0.35)
        if (caption.isNotBlank()) {
            val captionResult = typeCaption(caption, clonePackage)
            if (!captionResult.success) return captionResult
        }

        // Share
        logNormalDelay(mean = 400.0, sigma = 0.3)
        val shareResult = tapButtonWithTextOrId(
            texts = listOf("Share", "SHARE", "Post"),
            ids = listOf(
                "$clonePackage:id/share_footer_button",
                "com.instagram.android:id/share_footer_button",
            ),
            step = "share_reel",
        )
        if (!shareResult.success) return shareResult

        val confirmed = waitForPostConfirmation(clonePackage, timeoutMs = 20_000)
        if (!confirmed) return PostResult.fail("share_timeout")

        Log.i(TAG, "[$accountId] REEL post completed successfully")
        return PostResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Core UI helpers
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Launches the Instagram clone package to the foreground via an explicit
     * MAIN action intent.
     */
    private fun launchInstagram(clonePackage: String): Boolean {
        return try {
            val intent = service.packageManager.getLaunchIntentForPackage(clonePackage)
                ?: Intent(Intent.ACTION_MAIN).apply {
                    setPackage(clonePackage)
                    addCategory(Intent.CATEGORY_LAUNCHER)
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
                }
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            service.startActivity(intent)
            Log.d(TAG, "launchInstagram: started $clonePackage")
            true
        } catch (e: Exception) {
            Log.e(TAG, "launchInstagram failed for $clonePackage: ${e.message}")
            false
        }
    }

    /**
     * Taps the + (new post) tab button in the Instagram navigation bar.
     * Tries resource ID first (stock + common clone patterns), then
     * content-description fallback.
     */
    private suspend fun tapNewPostButton(clonePackage: String): PostResult {
        val result = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/tab_bar_new_post_tab",
                "com.instagram.android:id/tab_bar_new_post_tab",
                "$clonePackage:id/creation_tab",
                "com.instagram.android:id/creation_tab",
            ),
            descriptions = listOf("New Post", "New post", "Create"),
            texts = emptyList(),
            step = "new_post_button",
            maxAttempts = 3,
        )
        return if (result) PostResult.ok() else PostResult.fail("node_not_found:new_post_button")
    }

    /**
     * Selects the most recent item in the Instagram gallery picker.
     * The gallery recycler's first child is always the newest media.
     */
    private suspend fun selectMostRecentGalleryItem(clonePackage: String): PostResult {
        var attempts = 0
        while (attempts < 3) {
            attempts++
            val galleryNode = findNodeById(
                "$clonePackage:id/gallery_recycler_view",
                "com.instagram.android:id/gallery_recycler_view",
            )
            if (galleryNode != null) {
                if (galleryNode.childCount > 0) {
                    val firstItem = galleryNode.getChild(0)
                    if (firstItem != null) {
                        val tapOk = tapNode(firstItem, "selectMostRecentGalleryItem")
                        galleryNode.recycle()
                        return if (tapOk.success) PostResult.ok()
                        else PostResult.fail("node_not_found:gallery_first_item_tap_failed")
                    }
                }
                galleryNode.recycle()
            }
            // Fallback: try finding any grid image view in the picker
            val fallback = findNodeByDescription("Image") ?: findNodeByDescription("Photo")
            if (fallback != null) {
                val tapOk = tapNode(fallback, "selectMostRecentGalleryItem:fallback")
                return if (tapOk.success) PostResult.ok()
                else PostResult.fail("node_not_found:gallery_fallback_tap_failed")
            }
            logNormalDelay(mean = 600.0, sigma = 0.25)
        }
        return PostResult.fail("node_not_found:gallery_recycler_view")
    }

    /**
     * Types [caption] into the Instagram caption EditText field, character by
     * character with LogNormal per-character delay and an 8% typo-and-backspace rate.
     *
     * Uses ACTION_SET_TEXT progressively (building up the string) which triggers
     * normal keyboard input events from Instagram's perspective.
     */
    private suspend fun typeCaption(caption: String, clonePackage: String): PostResult {
        val captionNode = findNodeById(
            "$clonePackage:id/caption_input_text_view",
            "com.instagram.android:id/caption_input_text_view",
        ) ?: findNodeByClass("android.widget.EditText")
          ?: return PostResult.fail("node_not_found:caption_input")

        // Focus the field
        captionNode.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        SystemClock.sleep(120)

        val typed = StringBuilder()
        for (char in caption) {
            // 8% chance of typo: type a wrong char, pause, backspace, retype
            val typoRoll = (Math.random() * 100).toInt()
            if (typoRoll < 8) {
                val wrongChar = ('a'..'z').random()
                // Type wrong char
                typed.append(wrongChar)
                val bundle = Bundle()
                bundle.putCharSequence(
                    AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                    typed.toString(),
                )
                captionNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, bundle)
                // Pause — notice the mistake
                val typoNoticePauseMs = 150L + (0..250L).random()
                SystemClock.sleep(typoNoticePauseMs)
                // Backspace
                typed.deleteCharAt(typed.length - 1)
                val backspaceBundle = Bundle()
                backspaceBundle.putCharSequence(
                    AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                    typed.toString(),
                )
                captionNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, backspaceBundle)
                // Short pause before retyping
                SystemClock.sleep(80L + (0..80L).random())
            }

            // Type the correct character
            typed.append(char)
            val charBundle = Bundle()
            charBundle.putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                typed.toString(),
            )
            captionNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, charBundle)

            // Per-character delay: LogNormal(mean=80ms, sigma=0.35)
            logNormalDelay(mean = 80.0, sigma = 0.35)
        }

        Log.d(TAG, "typeCaption: typed ${caption.length} chars into caption field")
        captionNode.recycle()
        return PostResult.ok()
    }

    /**
     * Polls for post confirmation: waits for the Share button to disappear (indicating
     * submission was accepted) or for the main feed to return. Timeout [timeoutMs].
     *
     * Returns true if confirmed, false on timeout.
     */
    private suspend fun waitForPostConfirmation(
        clonePackage: String,
        timeoutMs: Long,
    ): Boolean {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            val shareButton = findNodeById(
                "$clonePackage:id/share_footer_button",
                "com.instagram.android:id/share_footer_button",
            )
            if (shareButton == null) {
                // Share button gone — post submitted
                Log.d(TAG, "waitForPostConfirmation: share button disappeared — confirmed")
                return true
            }
            shareButton.recycle()
            // Check if profile/feed tab is visible (returned to home)
            val feedTab = findNodeById(
                "$clonePackage:id/tab_bar_home_tab",
                "com.instagram.android:id/tab_bar_home_tab",
            )
            if (feedTab != null) {
                feedTab.recycle()
                Log.d(TAG, "waitForPostConfirmation: feed tab visible — confirmed")
                return true
            }
            delay(500)
        }
        Log.w(TAG, "waitForPostConfirmation: timed out after ${timeoutMs}ms")
        return false
    }

    /**
     * Attempts to trim a reel to ~60 seconds by tapping the trim end handle.
     * This is a best-effort operation — if the trim panel isn't present, it
     * is silently skipped (video may already be ≤60s).
     */
    private fun tryTrimToSixtySeconds() {
        try {
            val trimHandle = findNodeByDescription("Trim end") ?: findNodeByDescription("End handle")
            if (trimHandle != null) {
                val rect = Rect()
                trimHandle.getBoundsInScreen(rect)
                // The handle can be dragged left — tap it (UI will show trim controls)
                tapNode(trimHandle, "tryTrimToSixtySeconds")
                trimHandle.recycle()
                Log.d(TAG, "tryTrimToSixtySeconds: trim handle found and tapped")
            } else {
                Log.d(TAG, "tryTrimToSixtySeconds: no trim handle found — skipping")
            }
        } catch (e: Exception) {
            Log.d(TAG, "tryTrimToSixtySeconds: skipped — ${e.message}")
        }
    }

    /**
     * Generic button tapper — tries resource IDs first, then text, then
     * content-description. Returns PostResult.ok() on first match tapped.
     */
    private suspend fun tapButtonWithTextOrId(
        texts: List<String>,
        ids: List<String>,
        step: String,
        maxAttempts: Int = 3,
    ): PostResult {
        val ok = retryFindAndTap(
            ids = ids,
            descriptions = emptyList(),
            texts = texts,
            step = step,
            maxAttempts = maxAttempts,
        )
        return if (ok) PostResult.ok() else PostResult.fail("node_not_found:$step")
    }

    /**
     * Retries finding and tapping a node up to [maxAttempts] times,
     * with a LogNormal back-off between attempts.
     */
    private suspend fun retryFindAndTap(
        ids: List<String>,
        descriptions: List<String>,
        texts: List<String>,
        step: String,
        maxAttempts: Int,
    ): Boolean {
        repeat(maxAttempts) { attempt ->
            // Try by resource ID
            for (id in ids) {
                val node = findNodeById(id)
                if (node != null) {
                    val result = tapNode(node, "$step[id=$id]")
                    if (result.success) return true
                }
            }
            // Try by content-description
            for (desc in descriptions) {
                val node = findNodeByDescription(desc)
                if (node != null) {
                    val result = tapNode(node, "$step[desc=$desc]")
                    if (result.success) return true
                }
            }
            // Try by text
            for (text in texts) {
                val node = findNodeByText(text)
                if (node != null) {
                    val result = tapNode(node, "$step[text=$text]")
                    if (result.success) return true
                }
            }
            if (attempt < maxAttempts - 1) {
                Log.d(TAG, "$step: attempt ${attempt + 1}/$maxAttempts not found, retrying…")
                logNormalDelay(mean = 500.0, sigma = 0.3)
            }
        }
        Log.w(TAG, "$step: not found after $maxAttempts attempts")
        return false
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Accessibility node helpers (mirrors TikTokActionHandler style)
    // ──────────────────────────────────────────────────────────────────────────

    private fun findNodeById(vararg ids: String): AccessibilityNodeInfo? {
        val root = service.rootInActiveWindow ?: return null
        for (id in ids) {
            val nodes = root.findAccessibilityNodeInfosByViewId(id)
            if (nodes.isNotEmpty()) {
                root.recycle()
                return nodes.first()
            }
        }
        root.recycle()
        return null
    }

    private fun findNodeByDescription(description: String): AccessibilityNodeInfo? {
        val root = service.rootInActiveWindow ?: return null
        return findNodeByDescriptionRecursive(root, description).also {
            if (it == null) root.recycle()
        }
    }

    private fun findNodeByDescriptionRecursive(
        node: AccessibilityNodeInfo,
        desc: String,
    ): AccessibilityNodeInfo? {
        val nodeDesc = node.contentDescription?.toString() ?: ""
        if (nodeDesc.contains(desc, ignoreCase = true)) return node
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            val match = findNodeByDescriptionRecursive(child, desc)
            if (match != null) return match
            child.recycle()
        }
        return null
    }

    private fun findNodeByText(text: String): AccessibilityNodeInfo? {
        val root = service.rootInActiveWindow ?: return null
        val nodes = root.findAccessibilityNodeInfosByText(text)
        root.recycle()
        return nodes.firstOrNull()
    }

    private fun findNodeByClass(className: String): AccessibilityNodeInfo? {
        val root = service.rootInActiveWindow ?: return null
        return findNodeByClassRecursive(root, className).also {
            if (it == null) root.recycle()
        }
    }

    private fun findNodeByClassRecursive(
        node: AccessibilityNodeInfo,
        className: String,
    ): AccessibilityNodeInfo? {
        if (node.className?.contains(className, ignoreCase = true) == true) return node
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            val match = findNodeByClassRecursive(child, className)
            if (match != null) return match
            child.recycle()
        }
        return null
    }

    /**
     * Taps the centre of [node]'s bounding rect via a GestureDescription.
     * Recycles the node after tapping.
     */
    private fun tapNode(node: AccessibilityNodeInfo, tag: String): PostResult {
        return try {
            val rect = Rect()
            node.getBoundsInScreen(rect)
            val cx = rect.exactCenterX()
            val cy = rect.exactCenterY()
            node.recycle()

            val path = Path().apply { moveTo(cx, cy) }
            val dwellMs = 60L + (0..40L).random()
            val stroke = GestureDescription.StrokeDescription(path, 0L, dwellMs)
            val gesture = GestureDescription.Builder().addStroke(stroke).build()
            val ok = dispatchGestureSync(gesture)
            if (ok) {
                Log.d(TAG, "$tag: tapped ($cx, $cy)")
                PostResult.ok()
            } else {
                PostResult.fail("$tag: gesture cancelled")
            }
        } catch (e: Exception) {
            Log.e(TAG, "$tag error: ${e.message}")
            PostResult.fail("$tag: ${e.message}")
        }
    }

    /**
     * Dispatches a gesture synchronously and blocks until it completes or
     * times out (2 seconds). Mirrors [TikTokActionHandler.dispatchGestureSync].
     */
    private fun dispatchGestureSync(gesture: GestureDescription): Boolean {
        var done = false
        var succeeded = false
        service.dispatchGesture(gesture, object : AccessibilityService.GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription) {
                succeeded = true; done = true
            }
            override fun onCancelled(gestureDescription: GestureDescription) {
                done = true
            }
        }, null)
        val deadline = SystemClock.elapsedRealtime() + 2_000
        while (!done && SystemClock.elapsedRealtime() < deadline) {
            SystemClock.sleep(16)
        }
        return succeeded
    }

    // ──────────────────────────────────────────────────────────────────────────
    // LogNormal timing
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Suspends for a LogNormal-distributed delay.
     *
     * @param mean  Mean delay in milliseconds.
     * @param sigma Shape parameter (0.2–0.4 matches real human timing variance).
     *
     * Fleet-scale note: LogNormal produces a bell curve on log scale —
     * no rectangular histogram that Meta's ML classifier would flag.
     */
    private suspend fun logNormalDelay(mean: Double, sigma: Double) {
        val mu = ln(mean) - 0.5 * sigma * sigma
        val raw = exp(mu + sigma * randomGaussian())
        // Clamp to [0.3×mean, 3×mean] to prevent occasional extreme outliers
        val clamped = raw.coerceIn(mean * 0.3, mean * 3.0)
        delay(clamped.toLong())
    }

    /**
     * Box-Muller transform for a standard normal draw.
     * Using stdlib Math.random() is sufficient here — the timing jitter it
     * produces is entirely local device-side and never sent to Meta.
     */
    private fun randomGaussian(): Double {
        val u1 = Math.random()
        val u2 = Math.random()
        return sqrt(-2.0 * ln(u1.coerceAtLeast(1e-10))) * Math.cos(2 * Math.PI * u2)
    }

    // LongRange + CharRange random extensions — consistent with TikTokActionHandler
    private fun LongRange.random(): Long = (Math.random() * (endInclusive - start + 1)).toLong() + start
    private fun IntRange.random(): Int = (Math.random() * (endInclusive - start + 1)).toInt() + start
    private fun CharRange.random(): Char = (Math.random() * (endInclusive.code - start.code + 1)).toInt().plus(start.code).toChar()
}
