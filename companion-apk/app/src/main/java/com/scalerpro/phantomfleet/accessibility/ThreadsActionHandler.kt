package com.scalerpro.phantomfleet.accessibility

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.graphics.Rect
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import kotlinx.coroutines.delay
import kotlin.math.ln
import kotlin.math.exp
import kotlin.math.sqrt

/**
 * Handles Threads engagement UI automation via the Android Accessibility API.
 *
 * Covers follow/unfollow, like, comment, scroll feed, and session health checks
 * for both stock Threads (com.instagram.barcelona) and any NomixCloner clone package.
 *
 * Pattern mirrors [IGEngagementHandler] exactly: same logNormalDelay helpers,
 * same retryFindAndTap logic, same clone-package fallback chain (try clone ID
 * first, fall back to stock package ID, then content-description, then text).
 *
 * All methods are suspend functions and must be called from a coroutine.
 *
 * @param service The active [PhantomAccessibilityService] that owns gesture dispatch.
 */
class ThreadsActionHandler(private val service: AccessibilityService) {

    private val TAG = "PhantomThreads"

    companion object {
        /** Stock Threads package — fallback when no clone package is specified. */
        const val THREADS_PKG = "com.instagram.barcelona"
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Public result types
    // ──────────────────────────────────────────────────────────────────────────

    data class ThreadsResult(val success: Boolean, val error: String? = null) {
        companion object {
            fun ok() = ThreadsResult(true)
            fun fail(msg: String) = ThreadsResult(false, msg)
        }
    }

    data class SessionStatus(
        val loggedIn: Boolean,
        val needsReauth: Boolean = false,
    )

    // ──────────────────────────────────────────────────────────────────────────
    // Follow
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Opens [username]'s Threads profile via threads.net deep link and taps Follow.
     * Idempotent — returns ok if already following.
     */
    suspend fun followUser(username: String, clonePackage: String): ThreadsResult {
        Log.i(TAG, "followUser: username=$username pkg=$clonePackage")

        val opened = openProfile(username = username, clonePackage = clonePackage)
        if (!opened) return ThreadsResult.fail("open_profile_failed:$username")

        logNormalDelay(mean = 3000.0, sigma = 0.30)

        // Idempotency: already following?
        val existingNode = findNodeById(
            "$clonePackage:id/follow_button",
            "$THREADS_PKG:id/follow_button",
            "$clonePackage:id/profile_header_follow_button",
            "$THREADS_PKG:id/profile_header_follow_button",
        )
        if (existingNode != null) {
            val text = existingNode.text?.toString() ?: ""
            val desc = existingNode.contentDescription?.toString() ?: ""
            existingNode.recycle()
            if (text.contains("Following", ignoreCase = true) ||
                desc.contains("Following", ignoreCase = true)) {
                Log.d(TAG, "followUser: already following $username")
                service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
                return ThreadsResult.ok()
            }
        }

        val tapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/follow_button",
                "$THREADS_PKG:id/follow_button",
                "$clonePackage:id/profile_header_follow_button",
                "$THREADS_PKG:id/profile_header_follow_button",
            ),
            descriptions = listOf("Follow"),
            texts = listOf("Follow"),
            step = "follow_button",
            maxAttempts = 3,
        )
        if (!tapped) return ThreadsResult.fail("node_not_found:follow_button:$username")

        logNormalDelay(mean = 1200.0, sigma = 0.3)
        Log.i(TAG, "followUser: followed $username")
        service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
        return ThreadsResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Unfollow
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Opens [username]'s profile and unfollows by tapping Following → Unfollow.
     */
    suspend fun unfollowUser(username: String, clonePackage: String): ThreadsResult {
        Log.i(TAG, "unfollowUser: username=$username pkg=$clonePackage")

        val opened = openProfile(username = username, clonePackage = clonePackage)
        if (!opened) return ThreadsResult.fail("open_profile_failed:$username")

        logNormalDelay(mean = 3000.0, sigma = 0.30)

        val followingTapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/follow_button",
                "$THREADS_PKG:id/follow_button",
                "$clonePackage:id/profile_header_follow_button",
                "$THREADS_PKG:id/profile_header_follow_button",
            ),
            descriptions = listOf("Following"),
            texts = listOf("Following"),
            step = "following_button",
            maxAttempts = 3,
        )
        if (!followingTapped) return ThreadsResult.fail("node_not_found:following_button:$username")

        logNormalDelay(mean = 900.0, sigma = 0.3)

        val confirmTapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/unfollow_button",
                "$THREADS_PKG:id/unfollow_button",
                "$clonePackage:id/dialog_confirm_button",
                "$THREADS_PKG:id/dialog_confirm_button",
            ),
            descriptions = listOf("Unfollow"),
            texts = listOf("Unfollow"),
            step = "confirm_unfollow",
            maxAttempts = 3,
        )
        if (!confirmTapped) {
            service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
            return ThreadsResult.fail("node_not_found:confirm_unfollow:$username")
        }

        logNormalDelay(mean = 1000.0, sigma = 0.3)
        Log.i(TAG, "unfollowUser: unfollowed $username")
        service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
        return ThreadsResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Like post
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Opens a Threads post URL and taps the Like (heart) button.
     * [postUrl] should be the full threads.net URL: https://www.threads.net/@user/post/CODE
     * Idempotent — returns ok if already liked.
     */
    suspend fun likePost(postUrl: String, clonePackage: String): ThreadsResult {
        Log.i(TAG, "likePost: url=$postUrl pkg=$clonePackage")

        val opened = openUrl(url = postUrl, clonePackage = clonePackage)
        if (!opened) return ThreadsResult.fail("open_post_failed:$postUrl")

        logNormalDelay(mean = 2500.0, sigma = 0.30)

        // Idempotency: already liked?
        val likeNode = findNodeById(
            "$clonePackage:id/like_button",
            "$THREADS_PKG:id/like_button",
            "$clonePackage:id/row_feed_button_like",
            "$THREADS_PKG:id/row_feed_button_like",
        )
        if (likeNode != null) {
            val desc = likeNode.contentDescription?.toString() ?: ""
            if (desc.contains("Unlike", ignoreCase = true)) {
                likeNode.recycle()
                Log.d(TAG, "likePost: already liked")
                service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
                return ThreadsResult.ok()
            }
            likeNode.recycle()
        }

        val tapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/like_button",
                "$THREADS_PKG:id/like_button",
                "$clonePackage:id/row_feed_button_like",
                "$THREADS_PKG:id/row_feed_button_like",
            ),
            descriptions = listOf("Like", "Like post"),
            texts = emptyList(),
            step = "like_button",
            maxAttempts = 3,
        )
        if (!tapped) return ThreadsResult.fail("node_not_found:like_button")

        logNormalDelay(mean = 800.0, sigma = 0.3)
        Log.i(TAG, "likePost: liked post")
        service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
        return ThreadsResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Comment / Reply
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Opens a Threads post URL, taps Reply, types [commentText], and posts it.
     * Uses the same 8% typo-and-backspace simulation as [IGEngagementHandler].
     */
    suspend fun commentOnPost(
        postUrl: String,
        commentText: String,
        clonePackage: String,
    ): ThreadsResult {
        Log.i(TAG, "commentOnPost: url=$postUrl pkg=$clonePackage")

        val opened = openUrl(url = postUrl, clonePackage = clonePackage)
        if (!opened) return ThreadsResult.fail("open_post_failed:$postUrl")

        logNormalDelay(mean = 2500.0, sigma = 0.30)

        val commentTapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/reply_button",
                "$THREADS_PKG:id/reply_button",
                "$clonePackage:id/comment_button",
                "$THREADS_PKG:id/comment_button",
                "$clonePackage:id/row_feed_button_comment",
                "$THREADS_PKG:id/row_feed_button_comment",
            ),
            descriptions = listOf("Reply", "Comment"),
            texts = listOf("Reply", "Add a reply…", "Add a comment…"),
            step = "comment_icon",
            maxAttempts = 3,
        )
        if (!commentTapped) return ThreadsResult.fail("node_not_found:comment_icon")

        logNormalDelay(mean = 1200.0, sigma = 0.30)

        val typed = typeText(commentText, clonePackage)
        if (!typed.success) return typed

        logNormalDelay(mean = 800.0, sigma = 0.25)

        val sendTapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/post_button",
                "$THREADS_PKG:id/post_button",
                "$clonePackage:id/send_button",
                "$THREADS_PKG:id/send_button",
                "$clonePackage:id/layout_comment_thread_post",
                "$THREADS_PKG:id/layout_comment_thread_post",
            ),
            descriptions = listOf("Post", "Send"),
            texts = listOf("Post", "Send"),
            step = "send_button",
            maxAttempts = 3,
        )
        if (!sendTapped) return ThreadsResult.fail("node_not_found:send_button")

        logNormalDelay(mean = 1500.0, sigma = 0.3)
        Log.i(TAG, "commentOnPost: replied successfully")
        service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
        return ThreadsResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Scroll feed
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Launches Threads and scrolls the feed [swipeCount] times with
     * LogNormal-distributed dwell time between swipes.
     */
    suspend fun scrollFeed(swipeCount: Int, clonePackage: String): ThreadsResult {
        Log.i(TAG, "scrollFeed: swipes=$swipeCount pkg=$clonePackage")

        val launched = launchThreads(clonePackage)
        if (!launched) return ThreadsResult.fail("launch_failed:$clonePackage")

        logNormalDelay(mean = 2500.0, sigma = 0.30)

        val metrics = service.resources.displayMetrics
        val screenW = metrics.widthPixels.toFloat()
        val screenH = metrics.heightPixels.toFloat()
        val startX = screenW * 0.5f
        val startY = screenH * 0.72f
        val endY   = screenH * 0.28f

        repeat(swipeCount) {
            val durationMs = (250L + (0..120L).random())
            val path = Path().apply { moveTo(startX, startY); lineTo(startX, endY) }
            val stroke = GestureDescription.StrokeDescription(path, 0, durationMs)
            service.dispatchGesture(
                GestureDescription.Builder().addStroke(stroke).build(), null, null,
            )
            logNormalDelay(mean = 1800.0, sigma = 0.35)
        }

        return ThreadsResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Session check
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Launches the Threads clone, waits for it to settle, then checks whether
     * the home feed is visible (loggedIn=true) or a login screen is shown.
     */
    suspend fun checkSession(clonePackage: String): SessionStatus {
        val launched = launchThreads(clonePackage)
        if (!launched) return SessionStatus(loggedIn = false, needsReauth = true)

        logNormalDelay(mean = 3000.0, sigma = 0.25)

        // Home feed: compose/new-thread button is the most reliable indicator
        val feedNode = findNodeById(
            "$clonePackage:id/compose_button",
            "$THREADS_PKG:id/compose_button",
            "$clonePackage:id/threads_compose_button",
            "$THREADS_PKG:id/threads_compose_button",
        ) ?: findNodeByDescription("New thread")
          ?: findNodeByDescription("New post")
          ?: findNodeByDescription("Create")

        if (feedNode != null) {
            feedNode.recycle()
            return SessionStatus(loggedIn = true)
        }

        val loginNode = findNodeByText("Log in") ?: findNodeByText("Log In")
            ?: findNodeByText("Sign in")
        if (loginNode != null) {
            loginNode.recycle()
            return SessionStatus(loggedIn = false, needsReauth = true)
        }

        return SessionStatus(loggedIn = false)
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Navigation helpers
    // ──────────────────────────────────────────────────────────────────────────

    private fun launchThreads(clonePackage: String): Boolean {
        return try {
            val intent = service.packageManager.getLaunchIntentForPackage(clonePackage)
                ?: Intent(Intent.ACTION_MAIN).apply {
                    setPackage(clonePackage)
                    addCategory(Intent.CATEGORY_LAUNCHER)
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
                }
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            service.startActivity(intent)
            Log.d(TAG, "launchThreads: started $clonePackage")
            true
        } catch (e: Exception) {
            Log.e(TAG, "launchThreads failed for $clonePackage: ${e.message}")
            false
        }
    }

    /**
     * Opens a Threads user profile via threads.net deep link targeted at [clonePackage].
     * Falls back to launching the app if the deep link fails.
     */
    private fun openProfile(username: String, clonePackage: String): Boolean {
        return try {
            val intent = Intent(
                Intent.ACTION_VIEW,
                android.net.Uri.parse("https://www.threads.net/@$username"),
            ).apply {
                setPackage(clonePackage)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            service.startActivity(intent)
            true
        } catch (e: Exception) {
            Log.w(TAG, "openProfile deep link failed, launching app: ${e.message}")
            launchThreads(clonePackage)
        }
    }

    /**
     * Opens any threads.net URL (post, profile) via VIEW intent targeted at [clonePackage].
     */
    private fun openUrl(url: String, clonePackage: String): Boolean {
        return try {
            val intent = Intent(
                Intent.ACTION_VIEW,
                android.net.Uri.parse(url),
            ).apply {
                setPackage(clonePackage)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            service.startActivity(intent)
            true
        } catch (e: Exception) {
            Log.e(TAG, "openUrl failed for $url: ${e.message}")
            false
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Text typing (mirrors IGEngagementHandler.typeText exactly)
    // ──────────────────────────────────────────────────────────────────────────

    private suspend fun typeText(text: String, clonePackage: String): ThreadsResult {
        val inputNode = findNodeById(
            "$clonePackage:id/reply_composer_text",
            "$THREADS_PKG:id/reply_composer_text",
            "$clonePackage:id/layout_comment_thread_edittext",
            "$THREADS_PKG:id/layout_comment_thread_edittext",
            "$clonePackage:id/row_thread_composer_edittext",
            "$THREADS_PKG:id/row_thread_composer_edittext",
        ) ?: findNodeByClass("android.widget.EditText")
          ?: return ThreadsResult.fail("node_not_found:text_input_field")

        inputNode.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        SystemClock.sleep(120)

        val typed = StringBuilder()
        for (char in text) {
            // 8% typo rate — matches IGEngagementHandler
            if ((Math.random() * 100).toInt() < 8) {
                val wrongChar = ('a'..'z').random()
                typed.append(wrongChar)
                val b = Bundle()
                b.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, typed.toString())
                inputNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, b)
                SystemClock.sleep(150L + (0..250L).random())
                typed.deleteCharAt(typed.length - 1)
                val bb = Bundle()
                bb.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, typed.toString())
                inputNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, bb)
                SystemClock.sleep(80L + (0..80L).random())
            }

            typed.append(char)
            val charBundle = Bundle()
            charBundle.putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                typed.toString(),
            )
            inputNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, charBundle)
            logNormalDelay(mean = 80.0, sigma = 0.35)
        }

        inputNode.recycle()
        return ThreadsResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Accessibility node helpers (identical to IGEngagementHandler)
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
        if ((node.contentDescription?.toString() ?: "").contains(desc, ignoreCase = true)) return node
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

    private fun tapNode(node: AccessibilityNodeInfo, tag: String): ThreadsResult {
        return try {
            val rect = Rect()
            node.getBoundsInScreen(rect)
            val cx = rect.exactCenterX()
            val cy = rect.exactCenterY()
            node.recycle()
            val path = Path().apply { moveTo(cx, cy) }
            val dwellMs = 60L + (0..40L).random()
            val stroke = GestureDescription.StrokeDescription(path, 0L, dwellMs)
            val ok = dispatchGestureSync(GestureDescription.Builder().addStroke(stroke).build())
            if (ok) ThreadsResult.ok() else ThreadsResult.fail("$tag: gesture cancelled")
        } catch (e: Exception) {
            ThreadsResult.fail("$tag: ${e.message}")
        }
    }

    private fun dispatchGestureSync(gesture: GestureDescription): Boolean {
        var done = false
        var succeeded = false
        service.dispatchGesture(gesture, object : AccessibilityService.GestureResultCallback() {
            override fun onCompleted(g: GestureDescription) { succeeded = true; done = true }
            override fun onCancelled(g: GestureDescription) { done = true }
        }, null)
        val deadline = SystemClock.elapsedRealtime() + 2_000
        while (!done && SystemClock.elapsedRealtime() < deadline) SystemClock.sleep(16)
        return succeeded
    }

    private suspend fun retryFindAndTap(
        ids: List<String>,
        descriptions: List<String>,
        texts: List<String>,
        step: String,
        maxAttempts: Int,
    ): Boolean {
        repeat(maxAttempts) { attempt ->
            for (id in ids) {
                val node = findNodeById(id)
                if (node != null && tapNode(node, "$step[id=$id]").success) return true
            }
            for (desc in descriptions) {
                val node = findNodeByDescription(desc)
                if (node != null && tapNode(node, "$step[desc=$desc]").success) return true
            }
            for (text in texts) {
                val node = findNodeByText(text)
                if (node != null && tapNode(node, "$step[text=$text]").success) return true
            }
            if (attempt < maxAttempts - 1) {
                Log.d(TAG, "$step: attempt ${attempt + 1}/$maxAttempts not found, retrying…")
                logNormalDelay(mean = 500.0, sigma = 0.30)
            }
        }
        Log.w(TAG, "$step: not found after $maxAttempts attempts")
        return false
    }

    // ──────────────────────────────────────────────────────────────────────────
    // LogNormal timing (identical to IGEngagementHandler)
    // ──────────────────────────────────────────────────────────────────────────

    private suspend fun logNormalDelay(mean: Double, sigma: Double) {
        val mu  = ln(mean) - 0.5 * sigma * sigma
        val raw = exp(mu + sigma * randomGaussian())
        delay(raw.coerceIn(mean * 0.3, mean * 3.0).toLong())
    }

    private fun randomGaussian(): Double {
        val u1 = Math.random().coerceAtLeast(1e-10)
        val u2 = Math.random()
        return sqrt(-2.0 * ln(u1)) * Math.cos(2 * Math.PI * u2)
    }

    private fun LongRange.random(): Long  = (Math.random() * (endInclusive - start + 1)).toLong() + start
    private fun IntRange.random():  Int   = (Math.random() * (endInclusive - start + 1)).toInt()  + start
    private fun CharRange.random(): Char  = (Math.random() * (endInclusive.code - start.code + 1)).toInt().plus(start.code).toChar()
}
