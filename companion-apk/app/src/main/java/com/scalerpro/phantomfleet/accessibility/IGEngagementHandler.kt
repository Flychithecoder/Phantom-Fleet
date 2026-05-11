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
 * Handles all Instagram engagement UI automation via the Android Accessibility API.
 *
 * Covers follow/unfollow, like, comment, story viewing, reel scrolling, DM sending,
 * and session health checks. Every timing call uses LogNormal distributions to produce
 * fleet-wide histograms that match real human behaviour — not synthetic rectangular
 * distributions that Meta's ML classifier would flag at 20K-account cohort scale.
 *
 * Pattern mirrors [InstagramPostHandler] exactly: same logNormalDelay, same
 * tapButtonWithTextOrId/retryFindAndTap/tapNode helpers, same import set.
 *
 * All methods are suspend functions and must be called from a coroutine.
 *
 * @param service The active [PhantomAccessibilityService] that owns gesture dispatch.
 */
class IGEngagementHandler(private val service: AccessibilityService) {

    private val TAG = "PhantomIGEngage"

    // ──────────────────────────────────────────────────────────────────────────
    // Public result types
    // ──────────────────────────────────────────────────────────────────────────

    data class EngageResult(val success: Boolean, val error: String? = null) {
        companion object {
            fun ok() = EngageResult(true)
            fun fail(msg: String) = EngageResult(false, msg)
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
     * Navigates to [username]'s profile via Instagram deep link and taps the
     * Follow button. Handles the case where Follow is already tapped (returns
     * ok — idempotent).
     *
     * Instagram deep link: `instagram://user?username=<username>`
     */
    suspend fun followUser(username: String, clonePackage: String): EngageResult {
        Log.i(TAG, "followUser: username=$username pkg=$clonePackage")

        val opened = openDeepLink(
            uri = "instagram://user?username=$username",
            clonePackage = clonePackage,
        )
        if (!opened) return EngageResult.fail("deep_link_failed:profile:$username")

        // Wait for profile screen to load
        logNormalDelay(mean = 2800.0, sigma = 0.30)

        // If the Following button is already present, user is already followed — idempotent OK
        val alreadyFollowing = findNodeById(
            "$clonePackage:id/follow_list_follow_button",
            "com.instagram.android:id/follow_list_follow_button",
        )
        if (alreadyFollowing != null) {
            val text = alreadyFollowing.text?.toString() ?: ""
            alreadyFollowing.recycle()
            if (text.contains("Following", ignoreCase = true)) {
                Log.d(TAG, "followUser: already following $username")
                service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
                return EngageResult.ok()
            }
        }

        val tapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/follow_list_follow_button",
                "com.instagram.android:id/follow_list_follow_button",
                "$clonePackage:id/button_follow",
                "com.instagram.android:id/button_follow",
            ),
            descriptions = listOf("Follow"),
            texts = listOf("Follow"),
            step = "follow_button",
            maxAttempts = 3,
        )
        if (!tapped) return EngageResult.fail("node_not_found:follow_button:$username")

        // Human pause after tapping
        logNormalDelay(mean = 1200.0, sigma = 0.3)

        Log.i(TAG, "followUser: followed $username successfully")
        service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
        return EngageResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Unfollow
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Navigates to [username]'s profile and unfollows them by tapping
     * "Following" → confirming "Unfollow" in the dialog.
     */
    suspend fun unfollowUser(username: String, clonePackage: String): EngageResult {
        Log.i(TAG, "unfollowUser: username=$username pkg=$clonePackage")

        val opened = openDeepLink(
            uri = "instagram://user?username=$username",
            clonePackage = clonePackage,
        )
        if (!opened) return EngageResult.fail("deep_link_failed:profile:$username")

        logNormalDelay(mean = 2800.0, sigma = 0.30)

        // Tap the "Following" button to open the unfollow dialog
        val followingTapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/follow_list_follow_button",
                "com.instagram.android:id/follow_list_follow_button",
                "$clonePackage:id/button_follow",
                "com.instagram.android:id/button_follow",
            ),
            descriptions = listOf("Following"),
            texts = listOf("Following"),
            step = "following_button",
            maxAttempts = 3,
        )
        if (!followingTapped) return EngageResult.fail("node_not_found:following_button:$username")

        // Wait for the confirmation dialog / bottom sheet
        logNormalDelay(mean = 900.0, sigma = 0.3)

        // Tap the "Unfollow" confirmation button in the dialog
        val confirmTapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/follow_sheet_unfollow_row",
                "com.instagram.android:id/follow_sheet_unfollow_row",
                "$clonePackage:id/dialog_confirm_button",
                "com.instagram.android:id/dialog_confirm_button",
            ),
            descriptions = listOf("Unfollow"),
            texts = listOf("Unfollow"),
            step = "confirm_unfollow",
            maxAttempts = 3,
        )
        if (!confirmTapped) {
            service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
            return EngageResult.fail("node_not_found:confirm_unfollow:$username")
        }

        logNormalDelay(mean = 1000.0, sigma = 0.3)

        Log.i(TAG, "unfollowUser: unfollowed $username successfully")
        service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
        return EngageResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Like post
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Opens a post via deep link and taps the Like (heart) button.
     * Instagram deep link: `instagram://media?id=<mediaId>`
     *
     * If already liked, returns ok (idempotent).
     */
    suspend fun likePost(mediaId: String, clonePackage: String): EngageResult {
        Log.i(TAG, "likePost: mediaId=$mediaId pkg=$clonePackage")

        val opened = openDeepLink(
            uri = "instagram://media?id=$mediaId",
            clonePackage = clonePackage,
        )
        if (!opened) return EngageResult.fail("deep_link_failed:media:$mediaId")

        logNormalDelay(mean = 2500.0, sigma = 0.30)

        // Check if already liked (content-desc will be "Unlike" if already liked)
        val likeNode = findNodeById(
            "$clonePackage:id/row_feed_button_like",
            "com.instagram.android:id/row_feed_button_like",
        )
        if (likeNode != null) {
            val desc = likeNode.contentDescription?.toString() ?: ""
            if (desc.contains("Unlike", ignoreCase = true)) {
                likeNode.recycle()
                Log.d(TAG, "likePost: already liked $mediaId")
                service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
                return EngageResult.ok()
            }
            likeNode.recycle()
        }

        val tapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/row_feed_button_like",
                "com.instagram.android:id/row_feed_button_like",
            ),
            descriptions = listOf("Like"),
            texts = emptyList(),
            step = "like_button",
            maxAttempts = 3,
        )
        if (!tapped) return EngageResult.fail("node_not_found:like_button:$mediaId")

        logNormalDelay(mean = 800.0, sigma = 0.3)

        Log.i(TAG, "likePost: liked $mediaId successfully")
        service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
        return EngageResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Comment on post
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Opens a post via deep link, taps the comment icon, types [commentText]
     * character by character with LogNormal delays and an 8% typo rate
     * (same logic as [InstagramPostHandler.typeCaption]), then sends the comment.
     */
    suspend fun commentOnPost(
        mediaId: String,
        commentText: String,
        clonePackage: String,
    ): EngageResult {
        Log.i(TAG, "commentOnPost: mediaId=$mediaId pkg=$clonePackage")

        val opened = openDeepLink(
            uri = "instagram://media?id=$mediaId",
            clonePackage = clonePackage,
        )
        if (!opened) return EngageResult.fail("deep_link_failed:media:$mediaId")

        logNormalDelay(mean = 2500.0, sigma = 0.30)

        // Tap the comment icon
        val commentIconTapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/row_feed_button_comment",
                "com.instagram.android:id/row_feed_button_comment",
            ),
            descriptions = listOf("Comment"),
            texts = emptyList(),
            step = "comment_icon",
            maxAttempts = 3,
        )
        if (!commentIconTapped) return EngageResult.fail("node_not_found:comment_icon:$mediaId")

        logNormalDelay(mean = 1200.0, sigma = 0.30)

        // Focus the comment input field
        val inputFocused = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/layout_comment_thread_edittext",
                "com.instagram.android:id/layout_comment_thread_edittext",
                "$clonePackage:id/comment_input_view",
                "com.instagram.android:id/comment_input_view",
            ),
            descriptions = listOf("Add a comment"),
            texts = emptyList(),
            step = "comment_input_focus",
            maxAttempts = 3,
        )
        if (!inputFocused) return EngageResult.fail("node_not_found:comment_input:$mediaId")

        logNormalDelay(mean = 600.0, sigma = 0.25)

        // Type the comment text with typo simulation
        val typeResult = typeText(commentText, clonePackage)
        if (!typeResult.success) return typeResult

        // Tap the Post / Send button
        logNormalDelay(mean = 400.0, sigma = 0.30)
        val postTapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/layout_comment_thread_post_button_click_area",
                "com.instagram.android:id/layout_comment_thread_post_button_click_area",
                "$clonePackage:id/comment_post_button",
                "com.instagram.android:id/comment_post_button",
            ),
            descriptions = listOf("Post", "Send"),
            texts = listOf("Post", "Send"),
            step = "comment_post_button",
            maxAttempts = 3,
        )
        if (!postTapped) return EngageResult.fail("node_not_found:comment_post_button:$mediaId")

        logNormalDelay(mean = 1000.0, sigma = 0.30)

        Log.i(TAG, "commentOnPost: commented on $mediaId successfully")
        service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
        return EngageResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // View stories
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Navigates to [username]'s profile and taps their story ring to begin
     * viewing. Taps through [storyCount] story segments with a LogNormal
     * dwell time per segment (mean=3–8s to simulate reading/watching).
     * Exits back to the feed after completion.
     */
    suspend fun viewStories(
        username: String,
        storyCount: Int,
        clonePackage: String,
    ): EngageResult {
        Log.i(TAG, "viewStories: username=$username count=$storyCount pkg=$clonePackage")

        val opened = openDeepLink(
            uri = "instagram://user?username=$username",
            clonePackage = clonePackage,
        )
        if (!opened) return EngageResult.fail("deep_link_failed:profile:$username")

        logNormalDelay(mean = 2800.0, sigma = 0.30)

        // Tap the story ring (profile picture with ring indicator)
        // Instagram uses the profile image view as the story tap target
        val storyRingTapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/reel_viewer_avatar",
                "com.instagram.android:id/reel_viewer_avatar",
                "$clonePackage:id/profile_pic_avatar_or_anonymous",
                "com.instagram.android:id/profile_pic_avatar_or_anonymous",
                "$clonePackage:id/circular_avatar_with_story_ring",
                "com.instagram.android:id/circular_avatar_with_story_ring",
            ),
            descriptions = listOf("${username}'s story", "story", "Story"),
            texts = emptyList(),
            step = "story_ring_tap",
            maxAttempts = 3,
        )
        if (!storyRingTapped) return EngageResult.fail("node_not_found:story_ring:$username")

        // Wait for story viewer to open
        logNormalDelay(mean = 1500.0, sigma = 0.30)

        // Tap through each story segment
        for (i in 0 until storyCount) {
            // Check if still in story viewer — look for tap-to-advance surface
            val storyViewer = findNodeById(
                "$clonePackage:id/reel_viewer_root",
                "com.instagram.android:id/reel_viewer_root",
                "$clonePackage:id/story_viewer_container",
                "com.instagram.android:id/story_viewer_container",
            )
            if (storyViewer == null) {
                // Story viewer closed — possibly end of stories
                Log.d(TAG, "viewStories: viewer closed at segment $i/$storyCount")
                break
            }
            storyViewer.recycle()

            // Dwell on this segment: LogNormal(mean=4500ms, sigma=0.45) — real range 1.5–13.5s
            logNormalDelay(mean = 4500.0, sigma = 0.45)

            // Advance to next story by tapping the right side of the screen
            if (i < storyCount - 1) {
                val rect = Rect()
                service.rootInActiveWindow?.getBoundsInScreen(rect)
                val screenWidth  = rect.width().toFloat().coerceAtLeast(1080f)
                val screenHeight = rect.height().toFloat().coerceAtLeast(1920f)
                // Tap right third of screen to advance
                val tapX = screenWidth * (0.72f + (Math.random() * 0.08f).toFloat())
                val tapY = screenHeight * (0.40f + (Math.random() * 0.20f).toFloat())
                tapAt(tapX, tapY, dwellMs = 55L + (0..30L).random())
                logNormalDelay(mean = 400.0, sigma = 0.25)
            }
        }

        // Exit story viewer
        logNormalDelay(mean = 600.0, sigma = 0.25)
        service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
        logNormalDelay(mean = 500.0, sigma = 0.25)

        Log.i(TAG, "viewStories: viewed stories for $username")
        return EngageResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Scroll reel feed
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Navigates to the Reels tab and scrolls through [watchCount] reels.
     * Dwell time per reel is LogNormal: short reels (detected by the ≤30s progress
     * indicator node) use mean=15s, longer reels use mean=45s. This produces a
     * realistic bimodal watch-time distribution across the fleet.
     */
    suspend fun scrollReelFeed(watchCount: Int, clonePackage: String): EngageResult {
        Log.i(TAG, "scrollReelFeed: count=$watchCount pkg=$clonePackage")

        // Tap the Reels tab
        val reelTabTapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/tab_bar_clips_tab",
                "com.instagram.android:id/tab_bar_clips_tab",
                "$clonePackage:id/clips_tab",
                "com.instagram.android:id/clips_tab",
            ),
            descriptions = listOf("Reels"),
            texts = listOf("Reels"),
            step = "reels_tab",
            maxAttempts = 3,
        )
        if (!reelTabTapped) return EngageResult.fail("node_not_found:reels_tab")

        // Wait for reels feed to load
        logNormalDelay(mean = 2000.0, sigma = 0.30)

        for (i in 0 until watchCount) {
            // Detect whether this is a short reel (≤30s) or long reel
            // Instagram shows a video length node for reels longer than 30s
            val videoLengthNode = findNodeById(
                "$clonePackage:id/clips_video_label",
                "com.instagram.android:id/clips_video_label",
            )
            val isLongReel = videoLengthNode != null
            videoLengthNode?.recycle()

            // Dwell: short=mean15s, long=mean45s, both sigma=0.45
            val dwellMean = if (isLongReel) 45_000.0 else 15_000.0
            logNormalDelay(mean = dwellMean, sigma = 0.45)

            // Optionally like the reel with ~25% probability — human-like engagement rate
            if (Math.random() < 0.25) {
                retryFindAndTap(
                    ids = listOf(
                        "$clonePackage:id/clips_like_button",
                        "com.instagram.android:id/clips_like_button",
                    ),
                    descriptions = listOf("Like"),
                    texts = emptyList(),
                    step = "reel_like_optional",
                    maxAttempts = 1,
                )
                logNormalDelay(mean = 500.0, sigma = 0.3)
            }

            // Advance to next reel by swiping up
            if (i < watchCount - 1) {
                val rect = Rect()
                service.rootInActiveWindow?.getBoundsInScreen(rect)
                val screenWidth  = rect.width().toFloat().coerceAtLeast(1080f)
                val screenHeight = rect.height().toFloat().coerceAtLeast(1920f)
                val swipeX   = screenWidth  * (0.45f + (Math.random() * 0.10f).toFloat())
                val swipeY1  = screenHeight * (0.65f + (Math.random() * 0.10f).toFloat())
                val swipeY2  = screenHeight * (0.20f + (Math.random() * 0.10f).toFloat())
                val swipeDur = 220L + (0..120L).random()
                swipe(swipeX, swipeY1, swipeX, swipeY2, swipeDur)
                logNormalDelay(mean = 800.0, sigma = 0.3)
            }
        }

        Log.i(TAG, "scrollReelFeed: scrolled $watchCount reels")
        return EngageResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Send DM
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Opens the DM inbox, searches for [username], opens the thread,
     * types [message], and sends it.
     */
    suspend fun sendDM(
        username: String,
        message: String,
        clonePackage: String,
    ): EngageResult {
        Log.i(TAG, "sendDM: to=$username pkg=$clonePackage")

        // Tap the DM / Messenger icon in the top-right nav bar
        val dmIconTapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/action_bar_inbox_button",
                "com.instagram.android:id/action_bar_inbox_button",
                "$clonePackage:id/direct_inbox_button",
                "com.instagram.android:id/direct_inbox_button",
            ),
            descriptions = listOf("Direct", "Messenger", "Messages"),
            texts = emptyList(),
            step = "dm_icon",
            maxAttempts = 3,
        )
        if (!dmIconTapped) return EngageResult.fail("node_not_found:dm_icon")

        logNormalDelay(mean = 1800.0, sigma = 0.30)

        // Tap the compose / search icon in DM inbox
        val searchTapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/action_bar_search_toggle_button",
                "com.instagram.android:id/action_bar_search_toggle_button",
                "$clonePackage:id/direct_new_message_button",
                "com.instagram.android:id/direct_new_message_button",
            ),
            descriptions = listOf("Compose", "New message", "Search"),
            texts = emptyList(),
            step = "dm_compose_or_search",
            maxAttempts = 3,
        )
        if (!searchTapped) return EngageResult.fail("node_not_found:dm_search:$username")

        logNormalDelay(mean = 800.0, sigma = 0.25)

        // Type the username in the search field
        val searchField = findNodeById(
            "$clonePackage:id/direct_text_autocomplete",
            "com.instagram.android:id/direct_text_autocomplete",
            "$clonePackage:id/search_src_text",
            "com.instagram.android:id/search_src_text",
        ) ?: findNodeByClass("android.widget.EditText")
          ?: return EngageResult.fail("node_not_found:dm_search_input")

        searchField.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        SystemClock.sleep(200)

        val searchBundle = Bundle()
        searchBundle.putCharSequence(
            AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
            username,
        )
        searchField.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, searchBundle)
        searchField.recycle()

        logNormalDelay(mean = 1200.0, sigma = 0.30)

        // Tap the first search result matching the username
        val userResultTapped = retryFindAndTap(
            ids = emptyList(),
            descriptions = listOf(username),
            texts = listOf(username),
            step = "dm_search_result",
            maxAttempts = 3,
        )
        if (!userResultTapped) return EngageResult.fail("node_not_found:dm_search_result:$username")

        logNormalDelay(mean = 1500.0, sigma = 0.30)

        // If there's a "Chat" / "Next" button before the thread opens, tap it
        retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/row_user_header_chat_button",
                "com.instagram.android:id/row_user_header_chat_button",
            ),
            descriptions = listOf("Chat"),
            texts = listOf("Chat", "Next"),
            step = "dm_open_chat_optional",
            maxAttempts = 2,
        )

        logNormalDelay(mean = 1000.0, sigma = 0.30)

        // Tap the message compose box
        val composeFocused = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/row_thread_composer_edittext",
                "com.instagram.android:id/row_thread_composer_edittext",
                "$clonePackage:id/message_compose_text",
                "com.instagram.android:id/message_compose_text",
            ),
            descriptions = listOf("Message"),
            texts = emptyList(),
            step = "dm_compose_box",
            maxAttempts = 3,
        )
        if (!composeFocused) return EngageResult.fail("node_not_found:dm_compose_box:$username")

        logNormalDelay(mean = 500.0, sigma = 0.25)

        // Type the message character by character with typo simulation
        val typeResult = typeText(message, clonePackage)
        if (!typeResult.success) return typeResult

        logNormalDelay(mean = 400.0, sigma = 0.25)

        // Tap the Send button
        val sendTapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/row_thread_composer_button_send",
                "com.instagram.android:id/row_thread_composer_button_send",
                "$clonePackage:id/send_message_button",
                "com.instagram.android:id/send_message_button",
            ),
            descriptions = listOf("Send"),
            texts = listOf("Send"),
            step = "dm_send",
            maxAttempts = 3,
        )
        if (!sendTapped) return EngageResult.fail("node_not_found:dm_send:$username")

        logNormalDelay(mean = 1000.0, sigma = 0.30)

        Log.i(TAG, "sendDM: message sent to $username")
        service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
        return EngageResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Check session
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Launches [clonePackage], waits 3 seconds, and checks whether the home
     * feed tab bar is visible. If Instagram shows a login prompt instead, sets
     * [SessionStatus.needsReauth] = true.
     */
    suspend fun checkSession(clonePackage: String): SessionStatus {
        Log.i(TAG, "checkSession: pkg=$clonePackage")

        val launched = launchInstagram(clonePackage)
        if (!launched) {
            Log.w(TAG, "checkSession: launch failed for $clonePackage")
            return SessionStatus(loggedIn = false, needsReauth = false)
        }

        // Wait for app to settle — exactly 3 seconds per spec
        delay(3_000)

        // Check home feed tab bar — definitive sign of a logged-in session
        val homeFeed = findNodeById(
            "$clonePackage:id/tab_bar_home_tab",
            "com.instagram.android:id/tab_bar_home_tab",
        )
        if (homeFeed != null) {
            homeFeed.recycle()
            Log.d(TAG, "checkSession: session OK for $clonePackage")
            return SessionStatus(loggedIn = true, needsReauth = false)
        }

        // Check for login/reauth indicators
        val loginButton = findNodeByText("Log in") ?: findNodeByText("Log In")
        val reauthPrompt = findNodeByText("Enter your password")
            ?: findNodeByText("Confirm it's you")
            ?: findNodeByText("We detected an unusual login")

        val needsReauth = reauthPrompt != null
        loginButton?.recycle()
        reauthPrompt?.recycle()

        Log.w(TAG, "checkSession: session NOT logged in for $clonePackage (needsReauth=$needsReauth)")
        return SessionStatus(loggedIn = false, needsReauth = needsReauth)
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Deep link opener
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Opens an Instagram deep link URI in [clonePackage].
     * Falls back to the standard app launch if the deep link fails.
     */
    private fun openDeepLink(uri: String, clonePackage: String): Boolean {
        return try {
            val intent = Intent(Intent.ACTION_VIEW).apply {
                data = android.net.Uri.parse(uri)
                setPackage(clonePackage)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            }
            service.startActivity(intent)
            Log.d(TAG, "openDeepLink: $uri in $clonePackage")
            true
        } catch (e: Exception) {
            Log.e(TAG, "openDeepLink failed: $uri — ${e.message}")
            // Fallback: launch app normally
            launchInstagram(clonePackage)
        }
    }

    /**
     * Launches the Instagram clone package to the foreground via an explicit
     * MAIN action intent. Mirrors [InstagramPostHandler.launchInstagram].
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

    // ──────────────────────────────────────────────────────────────────────────
    // Text typing helper (shared by comment + DM)
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Types [text] into the currently-focused EditText field, character by
     * character with LogNormal per-character delay and an 8% typo-and-backspace rate.
     * Identical logic to [InstagramPostHandler.typeCaption].
     */
    private suspend fun typeText(text: String, clonePackage: String): EngageResult {
        val inputNode = findNodeById(
            "$clonePackage:id/layout_comment_thread_edittext",
            "com.instagram.android:id/layout_comment_thread_edittext",
            "$clonePackage:id/row_thread_composer_edittext",
            "com.instagram.android:id/row_thread_composer_edittext",
        ) ?: findNodeByClass("android.widget.EditText")
          ?: return EngageResult.fail("node_not_found:text_input_field")

        inputNode.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        SystemClock.sleep(120)

        val typed = StringBuilder()
        for (char in text) {
            // 8% chance of typo: type wrong char, pause, backspace, retype
            if ((Math.random() * 100).toInt() < 8) {
                val wrongChar = ('a'..'z').random()
                typed.append(wrongChar)
                val bundle = Bundle()
                bundle.putCharSequence(
                    AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                    typed.toString(),
                )
                inputNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, bundle)
                val typoNoticePauseMs = 150L + (0..250L).random()
                SystemClock.sleep(typoNoticePauseMs)
                // Backspace
                typed.deleteCharAt(typed.length - 1)
                val backspaceBundle = Bundle()
                backspaceBundle.putCharSequence(
                    AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                    typed.toString(),
                )
                inputNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, backspaceBundle)
                SystemClock.sleep(80L + (0..80L).random())
            }

            typed.append(char)
            val charBundle = Bundle()
            charBundle.putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                typed.toString(),
            )
            inputNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, charBundle)

            // Per-character delay: LogNormal(mean=80ms, sigma=0.35)
            logNormalDelay(mean = 80.0, sigma = 0.35)
        }

        Log.d(TAG, "typeText: typed ${text.length} chars")
        inputNode.recycle()
        return EngageResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Gesture helpers
    // ──────────────────────────────────────────────────────────────────────────

    private fun tapAt(x: Float, y: Float, dwellMs: Long = 80L) {
        val path = Path().apply { moveTo(x, y) }
        val stroke = GestureDescription.StrokeDescription(path, 0L, dwellMs)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()
        service.dispatchGesture(gesture, null, null)
    }

    private fun swipe(x1: Float, y1: Float, x2: Float, y2: Float, durationMs: Long = 300) {
        val path = Path().apply { moveTo(x1, y1); lineTo(x2, y2) }
        val stroke = GestureDescription.StrokeDescription(path, 0, durationMs)
        service.dispatchGesture(GestureDescription.Builder().addStroke(stroke).build(), null, null)
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Accessibility node helpers (mirrors InstagramPostHandler exactly)
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
    private fun tapNode(node: AccessibilityNodeInfo, tag: String): EngageResult {
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
                EngageResult.ok()
            } else {
                EngageResult.fail("$tag: gesture cancelled")
            }
        } catch (e: Exception) {
            Log.e(TAG, "$tag error: ${e.message}")
            EngageResult.fail("$tag: ${e.message}")
        }
    }

    /**
     * Dispatches a gesture synchronously and blocks until it completes or times out (2s).
     * Mirrors [InstagramPostHandler.dispatchGestureSync].
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
     * Generic button tapper — tries resource IDs first, then content-description,
     * then text. Returns EngageResult.ok() on first match tapped.
     */
    private suspend fun tapButtonWithTextOrId(
        texts: List<String>,
        ids: List<String>,
        descriptions: List<String>,
        step: String,
        maxAttempts: Int = 3,
    ): EngageResult {
        val ok = retryFindAndTap(
            ids = ids,
            descriptions = descriptions,
            texts = texts,
            step = step,
            maxAttempts = maxAttempts,
        )
        return if (ok) EngageResult.ok() else EngageResult.fail("node_not_found:$step")
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
                logNormalDelay(mean = 500.0, sigma = 0.30)
            }
        }
        Log.w(TAG, "$step: not found after $maxAttempts attempts")
        return false
    }

    // ──────────────────────────────────────────────────────────────────────────
    // LogNormal timing — identical to InstagramPostHandler
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Suspends for a LogNormal-distributed delay.
     *
     * Fleet-scale note: LogNormal produces a bell curve on log scale —
     * no rectangular histogram that Meta's ML classifier flags.
     *
     * @param mean  Mean delay in milliseconds.
     * @param sigma Shape parameter (0.2–0.45 matches real human timing variance).
     */
    private suspend fun logNormalDelay(mean: Double, sigma: Double) {
        val mu = ln(mean) - 0.5 * sigma * sigma
        val raw = exp(mu + sigma * randomGaussian())
        val clamped = raw.coerceIn(mean * 0.3, mean * 3.0)
        delay(clamped.toLong())
    }

    /**
     * Box-Muller transform for a standard normal draw.
     */
    private fun randomGaussian(): Double {
        val u1 = Math.random()
        val u2 = Math.random()
        return sqrt(-2.0 * ln(u1.coerceAtLeast(1e-10))) * Math.cos(2 * Math.PI * u2)
    }

    // LongRange + CharRange random extensions — consistent with InstagramPostHandler
    private fun LongRange.random(): Long = (Math.random() * (endInclusive - start + 1)).toLong() + start
    private fun IntRange.random(): Int = (Math.random() * (endInclusive - start + 1)).toInt() + start
    private fun CharRange.random(): Char = (Math.random() * (endInclusive.code - start.code + 1)).toInt().plus(start.code).toChar()
}
