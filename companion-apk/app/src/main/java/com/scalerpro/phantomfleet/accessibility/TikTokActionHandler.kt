package com.scalerpro.phantomfleet.accessibility

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.graphics.Rect
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking

/**
 * Handles TikTok-specific UI automation actions via the Android Accessibility API.
 *
 * Each public method dispatches one logical user action (scroll, like, comment, etc.)
 * through gesture dispatch or node interaction. The [AccessibilityService] reference
 * is passed at construction time so the handler can be replaced/mocked in tests.
 *
 * All methods return [ActionResult] — callers should check [ActionResult.success] and
 * surface [ActionResult.error] back to the HTTP client when the action fails.
 *
 * **Important:** gestures are dispatched synchronously via [runBlocking]. Do not call
 * these methods from the main thread.
 */
class TikTokActionHandler(private val service: AccessibilityService) {

    private val TAG = "PhantomTikTok"

    // ──────────────────────────────────────────────────────────────────────────
    // Result type
    // ──────────────────────────────────────────────────────────────────────────

    /** Result of a single accessibility action. */
    data class ActionResult(val success: Boolean, val error: String? = null) {
        companion object {
            fun ok() = ActionResult(true)
            fun fail(msg: String) = ActionResult(false, msg)
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Feed scrolling
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Scrolls the TikTok feed upward by performing [swipeCount] swipe-up gestures.
     *
     * Each swipe starts at ~60% of the screen height and ends at ~20%, simulating
     * a natural thumb flick. A short pause between swipes prevents the animation
     * from queuing.
     *
     * @param swipeCount Number of swipes to perform (capped at 20 to limit blast radius).
     * @param durationMs Duration of each swipe stroke in milliseconds.
     */
    fun scrollFeed(swipeCount: Int, durationMs: Int = 300): ActionResult {
        val count = swipeCount.coerceIn(1, 20)
        val metrics = service.resources.displayMetrics
        val screenWidth = metrics.widthPixels.toFloat()
        val screenHeight = metrics.heightPixels.toFloat()

        val startX = screenWidth / 2f
        val startY = screenHeight * 0.65f
        val endY   = screenHeight * 0.20f

        repeat(count) { i ->
            val path = Path().apply {
                moveTo(startX, startY)
                // Slight lateral wobble adds human variation
                val midX = startX + (-8..8).random()
                lineTo(midX.toFloat(), (startY + endY) / 2f)
                lineTo(startX, endY)
            }
            val stroke = GestureDescription.StrokeDescription(path, 0L, durationMs.toLong())
            val gesture = GestureDescription.Builder().addStroke(stroke).build()
            dispatchGestureSync(gesture)
            if (i < count - 1) {
                // Small inter-swipe pause so the video actually advances
                SystemClock.sleep(150L + (0..80L).random())
            }
        }
        Log.d(TAG, "scrollFeed: completed $count swipes")
        return ActionResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Like
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Taps the like (heart) button on the currently visible TikTok video.
     *
     * Tries to find the like button by resource-id first, then falls back to
     * content-description matching.
     *
     * @param pauseMs Delay in milliseconds before tapping (simulates read time).
     */
    fun likeCurrentVideo(pauseMs: Int = 200): ActionResult {
        if (pauseMs > 0) SystemClock.sleep(pauseMs.toLong())

        val node = findNodeById("com.zhiliaoapp.musically:id/gje", "com.ss.android.ugc.trill:id/gje")
            ?: findNodeByDescription("Like")
            ?: return ActionResult.fail("Like button not found")

        return tapNode(node, "likeCurrentVideo")
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Comment
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Opens the comment sheet on the currently visible TikTok video.
     */
    fun tapComment(): ActionResult {
        val node = findNodeById("com.zhiliaoapp.musically:id/gfm", "com.ss.android.ugc.trill:id/gfm")
            ?: findNodeByDescription("Comment")
            ?: return ActionResult.fail("Comment button not found")

        return tapNode(node, "tapComment")
    }

    /**
     * Types [text] into the open TikTok comment input field.
     *
     * Finds the EditText in the comment sheet and injects the text character-by-
     * character with [keystrokeDelayMs] pause between each character, simulating
     * human typing cadence.
     *
     * @param text The comment text to type.
     * @param keystrokeDelayMs Delay between each character (milliseconds).
     */
    fun typeComment(text: String, keystrokeDelayMs: Int = 80): ActionResult {
        if (text.isBlank()) return ActionResult.fail("Comment text is blank")

        val inputNode = findCommentInputNode()
            ?: return ActionResult.fail("Comment input field not found")

        // Focus the field
        inputNode.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        SystemClock.sleep(100)

        // Inject text character-by-character for human-like cadence
        for (char in text) {
            val bundle = Bundle()
            bundle.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, char.toString())
            // Append by reading existing text and appending
            val existing = inputNode.text?.toString() ?: ""
            bundle.putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                existing + char
            )
            inputNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, bundle)
            val jitter = keystrokeDelayMs + (-15..25).random()
            SystemClock.sleep(jitter.coerceAtLeast(10).toLong())
        }

        Log.d(TAG, "typeComment: typed ${text.length} chars")
        inputNode.recycle()
        return ActionResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Follow
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Navigates to [username]'s TikTok profile and taps the Follow button.
     *
     * Strategy: locate the author byline node that contains [username] in the
     * current feed video, tap it to open the profile, then find and tap Follow.
     *
     * @param username TikTok @handle without the @ prefix.
     */
    fun tapFollow(username: String): ActionResult {
        if (username.isBlank()) return ActionResult.fail("Username is blank")

        // Try tapping the username chip in the video byline to open profile
        val authorNode = findNodeByText("@$username")
            ?: findNodeByText(username)

        if (authorNode != null) {
            tapNode(authorNode, "tapFollow:openProfile")
            SystemClock.sleep(800) // wait for profile to load
            authorNode.recycle()
        }

        // Now find the Follow button on the profile page
        val followNode = findNodeById("com.zhiliaoapp.musically:id/btn_follow", "com.ss.android.ugc.trill:id/btn_follow")
            ?: findNodeByDescription("Follow")
            ?: findNodeByText("Follow")
            ?: return ActionResult.fail("Follow button not found for $username")

        // Don't tap if already following
        val nodeText = followNode.text?.toString() ?: ""
        val nodeDesc = followNode.contentDescription?.toString() ?: ""
        if (nodeText.equals("Following", ignoreCase = true) ||
            nodeDesc.equals("Following", ignoreCase = true)) {
            followNode.recycle()
            return ActionResult.fail("Already following $username")
        }

        return tapNode(followNode, "tapFollow:follow")
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Internal helpers
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Dispatches a gesture and blocks until it completes or times out (2 seconds).
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

    /**
     * Finds the first visible node matching any of the given resource-ids.
     * Returns null if none found. Caller is responsible for calling [AccessibilityNodeInfo.recycle].
     */
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

    /**
     * Finds the first node whose content-description contains [description] (case-insensitive).
     */
    private fun findNodeByDescription(description: String): AccessibilityNodeInfo? {
        val root = service.rootInActiveWindow ?: return null
        return findNodeByDescriptionRecursive(root, description).also { root.recycle() }
    }

    private fun findNodeByDescriptionRecursive(node: AccessibilityNodeInfo, desc: String): AccessibilityNodeInfo? {
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

    /**
     * Finds the first node whose text contains [text] (case-insensitive).
     */
    private fun findNodeByText(text: String): AccessibilityNodeInfo? {
        val root = service.rootInActiveWindow ?: return null
        val nodes = root.findAccessibilityNodeInfosByText(text)
        root.recycle()
        return nodes.firstOrNull()
    }

    /**
     * Locates the comment EditText input by class name.
     */
    private fun findCommentInputNode(): AccessibilityNodeInfo? {
        val root = service.rootInActiveWindow ?: return null
        return findEditTextRecursive(root).also { if (it == null) root.recycle() }
    }

    private fun findEditTextRecursive(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        if (node.className?.contains("EditText") == true) return node
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            val match = findEditTextRecursive(child)
            if (match != null) return match
            child.recycle()
        }
        return null
    }

    /**
     * Taps the centre of [node]'s bounding rect via a gesture.
     * Recycles the node after tapping.
     */
    private fun tapNode(node: AccessibilityNodeInfo, tag: String): ActionResult {
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
                ActionResult.ok()
            } else {
                ActionResult.fail("$tag: gesture cancelled")
            }
        } catch (e: Exception) {
            Log.e(TAG, "$tag error: ${e.message}")
            ActionResult.fail("$tag: ${e.message}")
        }
    }

    // LongRange random extension — avoids importing kotlin.random for small ranges
    private fun LongRange.random(): Long = (Math.random() * (endInclusive - start + 1)).toLong() + start
    private fun IntRange.random(): Int = (Math.random() * (endInclusive - start + 1)).toInt() + start
}
