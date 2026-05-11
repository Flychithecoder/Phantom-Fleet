package com.scalerpro.phantomfleet.accessibility

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.graphics.Rect
import android.net.Uri
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import kotlinx.coroutines.delay
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.sqrt

/**
 * Handles Instagram story sticker UI flows via the Android Accessibility API.
 *
 * Supports:
 *   - Poll sticker  ([addPollSticker])  — opens the Poll sticker, types the question
 *     and two options char-by-char with human-realistic jitter, confirms, then drags
 *     the sticker to the center-bottom position where real users place polls.
 *   - Question sticker ([addQuestionSticker]) — opens the Questions sticker, types the
 *     prompt char-by-char, confirms, then drags to vertical center.
 *   - Highlight management ([addStoryToHighlight]) — adds a posted story to an existing
 *     highlight reel or creates a new one.
 *   - Link sticker ([addLinkStickerToStory]) — adds an OF CTA link sticker and drags
 *     it to the bottom-30% of the canvas (standard CTA placement).
 *   - Close Friends posting ([postToCloseFriends]) — selects Close Friends audience
 *     before sending, for mother-account premium content.
 *   - Text overlay ([addTextOverlay]) — types a text card on the canvas and positions
 *     it at top/center/bottom.
 *   - Mother→child repost ([repostStoryFromMotherAccount]) — deep-links to the mother
 *     account's profile, taps the story ring, long-press-adds to editor.
 *
 * All timing uses LogNormal distributions to produce fleet-wide histograms that match
 * real human behaviour rather than rectangular distributions detectable by Meta ML.
 *
 * Pattern and helpers mirror [InstagramPostHandler] exactly.
 *
 * @param service The active [PhantomAccessibilityService] that owns gesture dispatch.
 */
class IGStoryFeatureHandler(private val service: AccessibilityService) {

    private val TAG = "PhantomIGStory"

    // ──────────────────────────────────────────────────────────────────────────
    // Public result types
    // ──────────────────────────────────────────────────────────────────────────

    data class StickerResult(val success: Boolean, val error: String? = null) {
        companion object {
            fun ok() = StickerResult(true)
            fun fail(msg: String) = StickerResult(false, msg)
        }
    }

    enum class OverlayPosition { TOP, CENTER, BOTTOM }

    data class StoryResult(val success: Boolean, val error: String? = null) {
        companion object {
            fun ok() = StoryResult(true)
            fun fail(msg: String) = StoryResult(false, msg)
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Highlight management
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * After a story is posted, tap "Add to Highlight" and select or create a highlight.
     *
     * UI flow:
     *  1. Wait for the story completion screen (highlight button appears here)
     *  2. Tap "Add to Highlight"
     *  3. Search the highlight picker list for [highlightName]
     *  4. If found: tap it → tap "Done"
     *  5. If not found and [createIfMissing]=true: tap "New" → type name → tap "Add" → tap "Done"
     *
     * @param highlightName  Display name of the target highlight reel.
     * @param createIfMissing  If true, create the highlight when not found.
     */
    suspend fun addStoryToHighlight(highlightName: String, createIfMissing: Boolean): Boolean {
        Log.i(TAG, "addStoryToHighlight: name=$highlightName createIfMissing=$createIfMissing")

        // Wait for the story completion / post-story screen
        logNormalDelay(mean = 2000.0, sigma = 0.3)

        // Step 1 — tap "Add to Highlight" button
        val addHighlightTapped = retryFindAndTap(
            ids = listOf("com.instagram.android:id/add_to_highlight_button"),
            descriptions = listOf("Add to Highlight", "Add to highlight"),
            texts = listOf("Add to Highlight", "Add to highlight"),
            step = "add_to_highlight_button",
            maxAttempts = 4,
        )
        if (!addHighlightTapped) {
            Log.w(TAG, "addStoryToHighlight: button not found")
            return false
        }

        // Wait for highlight picker sheet to animate open
        logNormalDelay(mean = 1200.0, sigma = 0.3)

        // Step 2 — look for the highlight in the picker list
        val found = findHighlightInList(highlightName)
        if (found) {
            Log.d(TAG, "addStoryToHighlight: found existing highlight '$highlightName'")
            logNormalDelay(mean = 600.0, sigma = 0.3)
            return tapDoneButton()
        }

        if (!createIfMissing) {
            Log.w(TAG, "addStoryToHighlight: '$highlightName' not found and createIfMissing=false")
            dismissBottomSheet()
            return false
        }

        Log.d(TAG, "addStoryToHighlight: creating new highlight '$highlightName'")

        // Step 3 — tap "New" button in the picker
        val newTapped = retryFindAndTap(
            ids = listOf("com.instagram.android:id/new_highlight_button"),
            descriptions = listOf("New highlight", "Create new highlight"),
            texts = listOf("New", "NEW", "New Highlight"),
            step = "new_highlight_button",
            maxAttempts = 3,
        )
        if (!newTapped) {
            Log.w(TAG, "addStoryToHighlight: 'New' button not found")
            return false
        }

        // Wait for name input sheet
        logNormalDelay(mean = 900.0, sigma = 0.3)

        // Step 4 — type the highlight name
        val nameTyped = typeIntoFieldById(
            text = highlightName,
            ids = listOf("com.instagram.android:id/highlight_name_input"),
            step = "highlight_name_input",
        )
        if (!nameTyped) {
            Log.w(TAG, "addStoryToHighlight: could not type highlight name")
            return false
        }

        // Step 5 — tap "Add" to confirm creation
        logNormalDelay(mean = 500.0, sigma = 0.3)
        val addTapped = retryFindAndTap(
            ids = listOf("com.instagram.android:id/add_button"),
            descriptions = listOf("Add"),
            texts = listOf("Add", "ADD"),
            step = "add_highlight_confirm",
            maxAttempts = 3,
        )
        if (!addTapped) {
            Log.w(TAG, "addStoryToHighlight: 'Add' confirm button not found")
            return false
        }

        // Step 6 — tap "Done"
        logNormalDelay(mean = 600.0, sigma = 0.3)
        return tapDoneButton()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Link sticker
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Add a link sticker to the story editor (call BEFORE tapping "Your Story").
     *
     * UI flow:
     *  1. Tap the sticker tray button (emoji face icon) in the story editor toolbar
     *  2. Tap "Link" sticker tile
     *  3. Clear existing URL → type [url] char-by-char
     *  4. Optionally change label to [stickerLabel]
     *  5. Tap "Done" to insert
     *  6. Drag sticker to bottom 30% of screen (real user CTA placement)
     *
     * @param url            The URL to embed (e.g. an OnlyFans link).
     * @param stickerLabel   Visible label on the sticker (e.g. "Subscribe").
     */
    suspend fun addLinkStickerToStory(url: String, stickerLabel: String): Boolean {
        Log.i(TAG, "addLinkStickerToStory: url=$url label=$stickerLabel")

        // Step 1 — tap sticker tray button
        val stickerTray = openStickerTray()
        if (!stickerTray.success) {
            Log.w(TAG, "addLinkStickerToStory: failed to open sticker tray")
            return false
        }
        logNormalDelay(mean = 800.0, sigma = 0.3)

        // Step 2 — find and tap the "Link" sticker
        val linkStickerTapped = scrollTrayAndTap(
            stickerTexts = listOf("Link", "LINK"),
            stickerDescriptions = listOf("Link sticker", "Add link"),
            step = "link_sticker_tile",
        )
        if (!linkStickerTapped.success) {
            Log.w(TAG, "addLinkStickerToStory: Link sticker tile not found")
            return false
        }
        logNormalDelay(mean = 800.0, sigma = 0.3)

        // Step 3 — clear and type URL
        val urlTyped = typeIntoFieldById(
            text = url,
            ids = listOf(
                "com.instagram.android:id/link_sticker_url_input",
                "com.instagram.android:id/url_input",
            ),
            step = "link_sticker_url",
            clearFirst = true,
        )
        if (!urlTyped) {
            Log.w(TAG, "addLinkStickerToStory: URL input not found")
            return false
        }

        // Step 4 — optionally set custom label
        if (stickerLabel.isNotBlank()) {
            logNormalDelay(mean = 500.0, sigma = 0.3)
            typeIntoFieldById(
                text = stickerLabel,
                ids = listOf(
                    "com.instagram.android:id/link_sticker_label_input",
                    "com.instagram.android:id/sticker_label_input",
                ),
                step = "link_sticker_label",
                required = false,
            )
        }

        // Step 5 — tap "Done"
        logNormalDelay(mean = 500.0, sigma = 0.3)
        val doneTapped = retryFindAndTap(
            ids = listOf("com.instagram.android:id/done_button"),
            descriptions = listOf("Done"),
            texts = listOf("Done", "DONE"),
            step = "link_sticker_done",
            maxAttempts = 3,
        )
        if (!doneTapped) {
            Log.w(TAG, "addLinkStickerToStory: 'Done' button not found after link input")
            return false
        }

        logNormalDelay(mean = 600.0, sigma = 0.3)

        // Step 6 — drag sticker to bottom 30% (CTA placement)
        dragStickerToBottomCta()

        Log.i(TAG, "addLinkStickerToStory: completed")
        return true
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Close Friends posting
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Post a story to Close Friends audience only.
     *
     * UI flow:
     *  1. Before tapping "Your Story", tap the audience selector
     *  2. Select "Close Friends"
     *  3. Tap "Share to Close Friends"
     *
     * @param mediaPath      On-device path (already pushed by caller).
     * @param caption        Overlay text (may be empty).
     * @param clonePackage   Instagram clone package.
     */
    suspend fun postToCloseFriends(
        mediaPath: String,
        caption: String,
        clonePackage: String,
    ): StoryResult {
        Log.i(TAG, "postToCloseFriends: package=$clonePackage")

        val audienceTapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/audience_selector",
                "com.instagram.android:id/audience_selector",
                "$clonePackage:id/close_friends_selector",
                "com.instagram.android:id/close_friends_selector",
            ),
            descriptions = listOf("Audience", "Choose audience", "Story audience"),
            texts = listOf("Close Friends", "Close friends"),
            step = "audience_selector",
            maxAttempts = 3,
        )
        if (!audienceTapped) {
            // Direct fallback
            val directCf = retryFindAndTap(
                ids = listOf("com.instagram.android:id/close_friends_option"),
                descriptions = listOf("Close Friends", "Close friends"),
                texts = listOf("Close Friends", "Close friends", "CLOSE FRIENDS"),
                step = "close_friends_direct",
                maxAttempts = 2,
            )
            if (!directCf) {
                return StoryResult.fail("audience_selector_not_found")
            }
        }

        logNormalDelay(mean = 800.0, sigma = 0.3)

        val shareTapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/share_to_close_friends_button",
                "com.instagram.android:id/share_to_close_friends_button",
            ),
            descriptions = listOf("Share to Close Friends", "Share"),
            texts = listOf("Share to Close Friends", "Share to close friends", "Close Friends"),
            step = "share_to_close_friends",
            maxAttempts = 3,
        )
        if (!shareTapped) {
            return StoryResult.fail("share_to_close_friends_button_not_found")
        }

        val confirmed = waitForStoryConfirmation(clonePackage, timeoutMs = 15_000)
        return if (confirmed) {
            Log.i(TAG, "postToCloseFriends: success")
            StoryResult.ok()
        } else {
            StoryResult.fail("close_friends_post_timeout")
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Text overlay
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Add a text overlay to the story canvas before posting.
     *
     * UI flow:
     *  1. Tap the text tool (Aa icon) in the editor toolbar
     *  2. Type [text] char-by-char
     *  3. Tap "Done"
     *  4. Drag text element to target [position]
     *
     * @param text      The overlay text to add.
     * @param position  Where to place the text (TOP, CENTER, BOTTOM).
     */
    suspend fun addTextOverlay(text: String, position: OverlayPosition): Boolean {
        Log.i(TAG, "addTextOverlay: text='${text.take(30)}' position=$position")

        // Step 1 — tap text tool
        val textToolTapped = retryFindAndTap(
            ids = listOf(
                "com.instagram.android:id/text_sticker_button",
                "com.instagram.android:id/aa_button",
            ),
            descriptions = listOf("Text", "Add text", "Aa"),
            texts = listOf("Aa"),
            step = "text_tool_button",
            maxAttempts = 3,
        )
        if (!textToolTapped) {
            Log.w(TAG, "addTextOverlay: text tool button not found")
            return false
        }

        logNormalDelay(mean = 500.0, sigma = 0.3)

        // Step 2 — type the text
        val textTyped = typeIntoFieldById(
            text = text,
            ids = listOf(
                "com.instagram.android:id/story_text_input",
                "com.instagram.android:id/text_view_edit",
            ),
            step = "story_text_input",
            required = false,
        )

        // If no field found by ID, type directly via raw method
        if (!textTyped) {
            typeRaw(text)
        }

        logNormalDelay(mean = 400.0, sigma = 0.3)

        // Step 3 — tap "Done"
        retryFindAndTap(
            ids = listOf("com.instagram.android:id/done_button"),
            descriptions = listOf("Done"),
            texts = listOf("Done", "DONE"),
            step = "text_overlay_done",
            maxAttempts = 3,
        )

        logNormalDelay(mean = 500.0, sigma = 0.3)

        // Step 4 — drag text element to target position
        dragTextToPosition(position)

        Log.i(TAG, "addTextOverlay: completed at position=$position")
        return true
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Mother→child repost
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Repost another account's story — opens the mother account's story in the editor.
     *
     * This is the entry point for the mother→child drop flow. After this call returns
     * StoryResult.ok(), the caller applies transforms (link sticker, text overlay)
     * then posts via the normal story send flow.
     *
     * UI flow:
     *  1. Navigate to mother account profile via Instagram deep-link Intent
     *  2. Tap the story ring on their profile
     *  3. Long-press on the story → tap "Add story to your story"
     *  4. Return (story is now in the IG editor)
     *
     * @param motherUsername   Instagram handle of the mother account.
     * @param clonePackage     Instagram clone package (for the child account).
     */
    suspend fun repostStoryFromMotherAccount(
        motherUsername: String,
        clonePackage: String,
    ): StoryResult {
        Log.i(TAG, "repostStoryFromMotherAccount: mother=@$motherUsername pkg=$clonePackage")

        // Step 1 — deep-link to the mother account's profile
        try {
            val intent = Intent(
                Intent.ACTION_VIEW,
                Uri.parse("https://instagram.com/$motherUsername"),
            ).apply {
                setPackage(clonePackage)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            service.startActivity(intent)
        } catch (e: Exception) {
            Log.e(TAG, "repostStoryFromMotherAccount: deep-link failed: ${e.message}")
            return StoryResult.fail("deep_link_failed:${e.message}")
        }

        // Wait for profile screen to load
        logNormalDelay(mean = 3000.0, sigma = 0.35)

        // Step 2 — tap the profile story ring
        val storyRingTapped = retryFindAndTap(
            ids = listOf(
                "$clonePackage:id/profile_header_avatar_container",
                "com.instagram.android:id/profile_header_avatar_container",
                "$clonePackage:id/profile_story_ring",
                "com.instagram.android:id/profile_story_ring",
            ),
            descriptions = listOf("Story ring", "Profile picture", "Open story"),
            texts = emptyList(),
            step = "profile_story_ring",
            maxAttempts = 4,
        )
        if (!storyRingTapped) {
            return StoryResult.fail("profile_story_ring_not_found")
        }

        // Wait for story viewer to open
        logNormalDelay(mean = 1500.0, sigma = 0.35)

        // Step 3 — long-press on story to reveal context menu
        val longPressed = longPressCenter()
        if (!longPressed) {
            return StoryResult.fail("long_press_story_failed")
        }

        logNormalDelay(mean = 600.0, sigma = 0.3)

        // Step 4 — tap "Add story to your story"
        val addToStoryTapped = retryFindAndTap(
            ids = listOf(
                "com.instagram.android:id/add_to_story_option",
                "$clonePackage:id/add_to_story_option",
            ),
            descriptions = listOf("Add story to your story", "Repost to story"),
            texts = listOf(
                "Add story to your story",
                "Add to story",
                "Add to your story",
            ),
            step = "add_to_story_option",
            maxAttempts = 3,
        )
        if (!addToStoryTapped) {
            // Fallback via "Send to" → "Add story to your story"
            val sendToTapped = retryFindAndTap(
                ids = emptyList(),
                descriptions = listOf("Send to", "Share"),
                texts = listOf("Send to", "Share"),
                step = "send_to_fallback",
                maxAttempts = 2,
            )
            if (sendToTapped) {
                logNormalDelay(mean = 500.0, sigma = 0.3)
                retryFindAndTap(
                    ids = emptyList(),
                    descriptions = listOf("Add story to your story"),
                    texts = listOf("Add story to your story"),
                    step = "add_to_story_in_sheet",
                    maxAttempts = 2,
                )
            }
        }

        // Story is now in editor — control returns to caller
        logNormalDelay(mean = 1200.0, sigma = 0.3)
        Log.i(TAG, "repostStoryFromMotherAccount: story loaded in editor for @$motherUsername")
        return StoryResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Poll sticker
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Adds an interactive poll sticker to the currently-open story editor.
     *
     * UI flow:
     *   1. Tap the sticker tray button (smiley icon in editor toolbar)
     *   2. Scroll the sticker tray until "Poll" is visible, then tap it
     *   3. Clear the question field → type [question] char-by-char with jitter
     *   4. Tap option-1 field → type [option1] char-by-char
     *   5. Tap option-2 field → type [option2] char-by-char
     *   6. Tap "Done" — poll sticker lands on the canvas
     *   7. Drag the sticker to center-bottom of frame (real user placement pattern)
     *
     * @param question Full poll question text, e.g. "Which content do you prefer? 🔥"
     * @param option1  First option, e.g. "Spicy 🌶️"
     * @param option2  Second option, e.g. "Sweet 🍯"
     * @return [StickerResult.ok] on success, [StickerResult.fail] with error key otherwise.
     */
    suspend fun addPollSticker(
        question: String,
        option1: String,
        option2: String,
    ): Boolean {
        Log.i(TAG, "addPollSticker: question=${question.take(30)}…")

        // Step 1 — tap sticker tray button
        val stickerTray = openStickerTray()
        if (!stickerTray.success) {
            Log.w(TAG, "addPollSticker: failed to open sticker tray: ${stickerTray.error}")
            return false
        }
        logNormalDelay(mean = 600.0, sigma = 0.3)

        // Step 2 — scroll tray until Poll sticker is visible, tap it
        val pollTap = scrollTrayAndTap(
            stickerTexts = listOf("Poll", "POLL"),
            stickerDescriptions = listOf("Poll sticker"),
            step = "poll_sticker_tap",
        )
        if (!pollTap.success) {
            Log.w(TAG, "addPollSticker: Poll sticker not found: ${pollTap.error}")
            return false
        }
        logNormalDelay(mean = 800.0, sigma = 0.35)

        // Step 3 — clear and type question
        val questionResult = clearAndTypeField(
            fieldTexts = listOf("What's your question?", "Question"),
            fieldDescriptions = listOf("Poll question"),
            content = question,
            step = "poll_question",
        )
        if (!questionResult.success) {
            Log.w(TAG, "addPollSticker: failed to type question: ${questionResult.error}")
            return false
        }
        logNormalDelay(mean = 400.0, sigma = 0.3)

        // Step 4 — tap option-1 field and type
        val opt1Result = clearAndTypeField(
            fieldTexts = listOf("Yes", "Option 1"),
            fieldDescriptions = listOf("Poll option 1"),
            content = option1,
            step = "poll_option1",
        )
        if (!opt1Result.success) {
            Log.w(TAG, "addPollSticker: failed to type option1: ${opt1Result.error}")
            return false
        }
        logNormalDelay(mean = 300.0, sigma = 0.3)

        // Step 5 — tap option-2 field and type
        val opt2Result = clearAndTypeField(
            fieldTexts = listOf("No", "Option 2"),
            fieldDescriptions = listOf("Poll option 2"),
            content = option2,
            step = "poll_option2",
        )
        if (!opt2Result.success) {
            Log.w(TAG, "addPollSticker: failed to type option2: ${opt2Result.error}")
            return false
        }
        logNormalDelay(mean = 400.0, sigma = 0.3)

        // Step 6 — tap Done
        val doneResult = retryFindAndTap(
            ids = listOf("com.instagram.android:id/done_button"),
            descriptions = listOf("Done"),
            texts = listOf("Done", "DONE"),
            step = "poll_done",
            maxAttempts = 3,
        )
        if (!doneResult) {
            Log.w(TAG, "addPollSticker: Done button not found")
            return false
        }
        logNormalDelay(mean = 700.0, sigma = 0.3)

        // Step 7 — drag poll sticker to center-bottom (real user placement)
        dragStickerToCenterBottom()

        Log.i(TAG, "addPollSticker: completed successfully")
        return true
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Question sticker
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Adds an interactive question sticker to the currently-open story editor.
     *
     * UI flow:
     *   1. Tap the sticker tray button
     *   2. Tap the "Questions" sticker
     *   3. Clear the prompt field → type [prompt] char-by-char with jitter
     *   4. Tap Done — question sticker lands on the canvas
     *   5. Drag to vertical center of the frame
     *
     * @param prompt The question prompt text, e.g. "Ask me anything 💬"
     * @return true on success, false on any step failure.
     */
    suspend fun addQuestionSticker(
        prompt: String,
    ): Boolean {
        Log.i(TAG, "addQuestionSticker: prompt=${prompt.take(30)}…")

        // Step 1 — tap sticker tray
        val stickerTray = openStickerTray()
        if (!stickerTray.success) {
            Log.w(TAG, "addQuestionSticker: failed to open sticker tray: ${stickerTray.error}")
            return false
        }
        logNormalDelay(mean = 600.0, sigma = 0.3)

        // Step 2 — tap Questions sticker
        val questionsTap = scrollTrayAndTap(
            stickerTexts = listOf("Questions", "Question"),
            stickerDescriptions = listOf("Questions sticker"),
            step = "questions_sticker_tap",
        )
        if (!questionsTap.success) {
            Log.w(TAG, "addQuestionSticker: Questions sticker not found: ${questionsTap.error}")
            return false
        }
        logNormalDelay(mean = 800.0, sigma = 0.35)

        // Step 3 — clear and type prompt
        val promptResult = clearAndTypeField(
            fieldTexts = listOf("Ask me a question…", "Ask me a question", "Ask me anything"),
            fieldDescriptions = listOf("Question prompt"),
            content = prompt,
            step = "questions_prompt",
        )
        if (!promptResult.success) {
            Log.w(TAG, "addQuestionSticker: failed to type prompt: ${promptResult.error}")
            return false
        }
        logNormalDelay(mean = 400.0, sigma = 0.3)

        // Step 4 — tap Done
        val doneResult = retryFindAndTap(
            ids = listOf("com.instagram.android:id/done_button"),
            descriptions = listOf("Done"),
            texts = listOf("Done", "DONE"),
            step = "questions_done",
            maxAttempts = 3,
        )
        if (!doneResult) {
            Log.w(TAG, "addQuestionSticker: Done button not found")
            return false
        }
        logNormalDelay(mean = 700.0, sigma = 0.3)

        // Step 5 — drag sticker to vertical center of frame
        dragStickerToCenter()

        Log.i(TAG, "addQuestionSticker: completed successfully")
        return true
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Highlight + link + text helper methods
    // ──────────────────────────────────────────────────────────────────────────

    private suspend fun findHighlightInList(name: String): Boolean {
        val directMatch = findNodeByText(name)
        if (directMatch != null) {
            return tapNode(directMatch, "findHighlightInList:direct")
        }
        repeat(3) { scrollAttempt ->
            scrollDown()
            logNormalDelay(mean = 400.0, sigma = 0.3)
            val node = findNodeByText(name)
            if (node != null) {
                return tapNode(node, "findHighlightInList:scroll_$scrollAttempt")
            }
        }
        return false
    }

    private suspend fun tapDoneButton(): Boolean {
        return retryFindAndTap(
            ids = listOf("com.instagram.android:id/done_button"),
            descriptions = listOf("Done"),
            texts = listOf("Done", "DONE"),
            step = "highlight_done",
            maxAttempts = 3,
        )
    }

    private suspend fun dismissBottomSheet() {
        val displayMetrics = service.resources.displayMetrics
        val screenHeight = displayMetrics.heightPixels
        val screenWidth  = displayMetrics.widthPixels
        val cx = screenWidth * 0.5f
        val startY = screenHeight * 0.4f
        val endY   = screenHeight * 0.9f
        val path = Path().apply { moveTo(cx, startY); lineTo(cx, endY) }
        val stroke = GestureDescription.StrokeDescription(path, 0L, 300L)
        dispatchGestureSync(GestureDescription.Builder().addStroke(stroke).build())
    }

    /**
     * Type text into an EditText field found by resource ID.
     * Char-by-char with 8% typo rate and LogNormal per-character delay.
     * Returns false if no matching field is found and [required] is true.
     */
    private suspend fun typeIntoFieldById(
        text: String,
        ids: List<String>,
        step: String,
        clearFirst: Boolean = false,
        required: Boolean = true,
    ): Boolean {
        var node: AccessibilityNodeInfo? = null
        for (id in ids) {
            node = findNodeById(id)
            if (node != null) break
        }
        if (node == null) {
            if (!required) return false
            node = findNodeByClass("android.widget.EditText") ?: return false
        }

        node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        SystemClock.sleep(120)

        if (clearFirst) {
            val clearBundle = Bundle()
            clearBundle.putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, "",
            )
            node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, clearBundle)
            SystemClock.sleep(60)
        }

        val typed = StringBuilder()
        for (char in text) {
            if ((Math.random() * 100).toInt() < 8) {
                val wrongChar = ('a'..'z').random()
                typed.append(wrongChar)
                val wrongBundle = Bundle()
                wrongBundle.putCharSequence(
                    AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, typed.toString(),
                )
                node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, wrongBundle)
                SystemClock.sleep(150L + (0..200L).random())
                typed.deleteCharAt(typed.length - 1)
                val backBundle = Bundle()
                backBundle.putCharSequence(
                    AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, typed.toString(),
                )
                node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, backBundle)
                SystemClock.sleep(80L + (0..60L).random())
            }
            typed.append(char)
            val charBundle = Bundle()
            charBundle.putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, typed.toString(),
            )
            node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, charBundle)
            logNormalDelay(mean = 90.0, sigma = 0.35)
        }
        node.recycle()
        Log.d(TAG, "$step: typed ${text.length} chars")
        return true
    }

    /** Type raw text on any focused EditText — fallback for story canvas mode. */
    private suspend fun typeRaw(text: String) {
        val node = findNodeByClass("android.widget.EditText") ?: return
        node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        SystemClock.sleep(100)
        val bundle = Bundle()
        bundle.putCharSequence(
            AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text,
        )
        node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, bundle)
        node.recycle()
    }

    /** Drag link sticker to bottom 30% of screen (CTA placement). */
    private fun dragStickerToBottomCta() {
        val displayMetrics = service.resources.displayMetrics
        val screenHeight = displayMetrics.heightPixels.toFloat()
        val screenWidth  = displayMetrics.widthPixels.toFloat()
        val path = Path().apply {
            moveTo(screenWidth * 0.5f, screenHeight * 0.5f)
            lineTo(screenWidth * 0.5f, screenHeight * 0.75f)
        }
        dispatchGestureSync(GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0L, 500L))
            .build())
        Log.d(TAG, "dragStickerToBottomCta: dragged to bottom 30%")
    }

    /** Drag text overlay to the desired vertical position. */
    private fun dragTextToPosition(position: OverlayPosition) {
        val displayMetrics = service.resources.displayMetrics
        val screenHeight = displayMetrics.heightPixels.toFloat()
        val screenWidth  = displayMetrics.widthPixels.toFloat()
        val startX = screenWidth * 0.5f
        val startY = screenHeight * 0.5f
        val endY = when (position) {
            OverlayPosition.TOP    -> screenHeight * 0.15f
            OverlayPosition.CENTER -> screenHeight * 0.50f
            OverlayPosition.BOTTOM -> screenHeight * 0.80f
        }
        val path = Path().apply { moveTo(startX, startY); lineTo(startX, endY) }
        dispatchGestureSync(GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0L, 400L))
            .build())
        Log.d(TAG, "dragTextToPosition: position=$position endY=$endY")
    }

    /** Long-press at screen centre (opens story context menu). */
    private fun longPressCenter(): Boolean {
        val displayMetrics = service.resources.displayMetrics
        val cx = displayMetrics.widthPixels  * 0.5f
        val cy = displayMetrics.heightPixels * 0.5f
        val path = Path().apply { moveTo(cx, cy) }
        return dispatchGestureSync(GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0L, 600L))
            .build())
    }

    private fun scrollDown() {
        val displayMetrics = service.resources.displayMetrics
        val screenHeight = displayMetrics.heightPixels.toFloat()
        val screenWidth  = displayMetrics.widthPixels.toFloat()
        val path = Path().apply {
            moveTo(screenWidth * 0.5f, screenHeight * 0.7f)
            lineTo(screenWidth * 0.5f, screenHeight * 0.3f)
        }
        dispatchGestureSync(GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0L, 200L))
            .build())
    }

    private suspend fun waitForStoryConfirmation(
        clonePackage: String,
        timeoutMs: Long,
    ): Boolean {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            val shareBtn = findNodeById(
                "$clonePackage:id/share_to_story_button",
                "com.instagram.android:id/share_to_story_button",
            )
            if (shareBtn == null) {
                Log.d(TAG, "waitForStoryConfirmation: share button gone — confirmed")
                return true
            }
            shareBtn.recycle()
            delay(500)
        }
        return false
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Sticker tray helpers
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Taps the sticker tray button in the story editor toolbar.
     *
     * Instagram uses several resource IDs across app versions and clones,
     * so we try the canonical ID, content-description, and text fallbacks.
     */
    private suspend fun openStickerTray(): StickerResult {
        val found = retryFindAndTap(
            ids = listOf(
                "com.instagram.android:id/sticker_tray_button",
                "com.instagram.android:id/sticker_button",
            ),
            descriptions = listOf("Sticker", "Add sticker", "Stickers"),
            texts = listOf("Sticker", "Stickers"),
            step = "sticker_tray_button",
            maxAttempts = 3,
        )
        return if (found) StickerResult.ok()
        else StickerResult.fail("node_not_found:sticker_tray_button")
    }

    /**
     * Scrolls the sticker tray horizontally until a sticker matching [stickerTexts]
     * or [stickerDescriptions] is visible, then taps it.
     *
     * Real users scroll the sticker tray — a direct tap without scrolling
     * assumes the sticker is always in the default visible region, which would
     * be a static behavioural fingerprint across the fleet.
     *
     * Scroll strategy: up to 3 horizontal swipes, each 400px to the left,
     * checking for the target sticker after each swipe.
     */
    private suspend fun scrollTrayAndTap(
        stickerTexts: List<String>,
        stickerDescriptions: List<String>,
        step: String,
    ): StickerResult {
        // First try without scrolling (sticker may already be visible)
        val immediate = retryFindAndTap(
            ids = emptyList(),
            descriptions = stickerDescriptions,
            texts = stickerTexts,
            step = "$step:no_scroll",
            maxAttempts = 1,
        )
        if (immediate) return StickerResult.ok()

        // Scroll up to 3 times then try again each time
        val displayRect = getDisplayRect()
        val scrollY = (displayRect.height() * 0.80).toInt()   // sticker tray is near bottom
        val scrollStartX = (displayRect.width() * 0.75).toInt()
        val scrollEndX = (displayRect.width() * 0.25).toInt()

        repeat(3) { scrollAttempt ->
            // Swipe left across the sticker tray
            val path = Path().apply {
                moveTo(scrollStartX.toFloat(), scrollY.toFloat())
                lineTo(scrollEndX.toFloat(), scrollY.toFloat())
            }
            val stroke = GestureDescription.StrokeDescription(path, 0L, 250L)
            val gesture = GestureDescription.Builder().addStroke(stroke).build()
            dispatchGestureSync(gesture)

            logNormalDelay(mean = 350.0, sigma = 0.25)

            val found = retryFindAndTap(
                ids = emptyList(),
                descriptions = stickerDescriptions,
                texts = stickerTexts,
                step = "$step:scroll_${scrollAttempt + 1}",
                maxAttempts = 1,
            )
            if (found) return StickerResult.ok()
        }

        return StickerResult.fail("node_not_found:$step")
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Field typing helpers
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Finds an EditText by text hints or content-descriptions, clears it,
     * and types [content] character-by-character with:
     *   - LogNormal per-character delay (mean=80ms, σ=0.35)
     *   - 8% typo-and-backspace rate (matching [InstagramPostHandler.typeCaption])
     *
     * The incremental ACTION_SET_TEXT approach triggers normal keyboard input
     * events from Instagram's perspective — same as a real user typing.
     */
    private suspend fun clearAndTypeField(
        fieldTexts: List<String>,
        fieldDescriptions: List<String>,
        content: String,
        step: String,
    ): StickerResult {
        // Find the field
        var fieldNode: AccessibilityNodeInfo? = null
        for (text in fieldTexts) {
            fieldNode = findNodeByText(text)
            if (fieldNode != null) break
        }
        if (fieldNode == null) {
            for (desc in fieldDescriptions) {
                fieldNode = findNodeByDescription(desc)
                if (fieldNode != null) break
            }
        }
        if (fieldNode == null) {
            // Last resort: look for any focused EditText
            fieldNode = findNodeByClass("android.widget.EditText")
        }
        if (fieldNode == null) {
            return StickerResult.fail("node_not_found:$step")
        }

        // Focus and clear
        fieldNode.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        SystemClock.sleep(100)
        val clearBundle = Bundle()
        clearBundle.putCharSequence(
            AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
            "",
        )
        fieldNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, clearBundle)
        SystemClock.sleep(80)

        // Type char-by-char with jitter
        val typed = StringBuilder()
        for (char in content) {
            // 8% typo rate
            if ((Math.random() * 100).toInt() < 8) {
                val wrongChar = ('a'..'z').random()
                typed.append(wrongChar)
                val bundle = Bundle()
                bundle.putCharSequence(
                    AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                    typed.toString(),
                )
                fieldNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, bundle)
                val typoNoticeMs = 150L + (0..250L).random()
                SystemClock.sleep(typoNoticeMs)
                // Backspace
                typed.deleteCharAt(typed.length - 1)
                val backBundle = Bundle()
                backBundle.putCharSequence(
                    AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                    typed.toString(),
                )
                fieldNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, backBundle)
                SystemClock.sleep(80L + (0..80L).random())
            }

            // Correct char
            typed.append(char)
            val charBundle = Bundle()
            charBundle.putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                typed.toString(),
            )
            fieldNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, charBundle)

            // Per-char delay: LogNormal(mean=80ms, σ=0.35)
            logNormalDelay(mean = 80.0, sigma = 0.35)
        }

        Log.d(TAG, "$step: typed ${content.length} chars")
        fieldNode.recycle()
        return StickerResult.ok()
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Sticker drag helpers
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Drags a newly-placed sticker from its default position (center of canvas) to
     * center-bottom — where real users place interactive poll stickers for maximum
     * tap reach.
     *
     * Uses a 400ms drag duration with LogNormal jitter to avoid a fixed dwell
     * fingerprint.  The destination is 75% down from the top of the display,
     * horizontally centered — empirically where poll stickers appear on most
     * real accounts.
     */
    private fun dragStickerToCenterBottom() {
        val rect = getDisplayRect()
        val cx = rect.exactCenterX()
        val cy = rect.exactCenterY()
        val targetY = rect.top + rect.height() * 0.75f
        dragBetween(cx, cy, cx, targetY, durationMs = 380L + (0..80L).random())
    }

    /**
     * Drags a newly-placed sticker from its default position to the vertical center —
     * typical placement for question stickers.
     */
    private fun dragStickerToCenter() {
        val rect = getDisplayRect()
        val cx = rect.exactCenterX()
        val cy = rect.exactCenterY()
        val targetY = rect.top + rect.height() * 0.50f
        dragBetween(cx, cy, cx, targetY, durationMs = 360L + (0..80L).random())
    }

    /**
     * Issues a drag gesture from (startX, startY) to (endX, endY) over [durationMs].
     */
    private fun dragBetween(
        startX: Float,
        startY: Float,
        endX: Float,
        endY: Float,
        durationMs: Long,
    ) {
        val path = Path().apply {
            moveTo(startX, startY)
            lineTo(endX, endY)
        }
        val stroke = GestureDescription.StrokeDescription(path, 0L, durationMs)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()
        dispatchGestureSync(gesture)
    }

    /**
     * Returns a Rect representing the full display bounds.
     * Falls back to a 1080×2340 default if no root window is available.
     */
    private fun getDisplayRect(): Rect {
        val root = service.rootInActiveWindow
        if (root != null) {
            val rect = Rect()
            root.getBoundsInScreen(rect)
            root.recycle()
            if (rect.width() > 0 && rect.height() > 0) return rect
        }
        // Fallback: common full-screen portrait dimensions
        return Rect(0, 0, 1080, 2340)
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Generic node-find + tap helpers (mirrors InstagramPostHandler)
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Retries finding and tapping a node up to [maxAttempts] times with
     * a LogNormal back-off between attempts.
     *
     * Search order: resource ID → content-description → text.
     */
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
                if (node != null) {
                    val ok = tapNode(node, "$step[id=$id]")
                    if (ok) return true
                }
            }
            for (desc in descriptions) {
                val node = findNodeByDescription(desc)
                if (node != null) {
                    val ok = tapNode(node, "$step[desc=$desc]")
                    if (ok) return true
                }
            }
            for (text in texts) {
                val node = findNodeByText(text)
                if (node != null) {
                    val ok = tapNode(node, "$step[text=$text]")
                    if (ok) return true
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
     *
     * Returns true on gesture completion, false on cancellation or exception.
     */
    private fun tapNode(node: AccessibilityNodeInfo, tag: String): Boolean {
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
            if (ok) Log.d(TAG, "$tag: tapped ($cx, $cy)")
            else Log.d(TAG, "$tag: gesture cancelled")
            ok
        } catch (e: Exception) {
            Log.e(TAG, "$tag error: ${e.message}")
            false
        }
    }

    /**
     * Dispatches a gesture synchronously and blocks until it completes or
     * times out (2 seconds). Mirrors [InstagramPostHandler.dispatchGestureSync].
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
    // LogNormal timing (mirrors InstagramPostHandler)
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
        val clamped = raw.coerceIn(mean * 0.3, mean * 3.0)
        delay(clamped.toLong())
    }

    /** Box-Muller transform for a standard normal draw. */
    private fun randomGaussian(): Double {
        val u1 = Math.random()
        val u2 = Math.random()
        return sqrt(-2.0 * ln(u1.coerceAtLeast(1e-10))) * Math.cos(2 * Math.PI * u2)
    }

    // LongRange + CharRange random extensions — consistent with InstagramPostHandler
    private fun LongRange.random(): Long = (Math.random() * (endInclusive - start + 1)).toLong() + start
    private fun CharRange.random(): Char = (Math.random() * (endInclusive.code - start.code + 1)).toInt().plus(start.code).toChar()
}
