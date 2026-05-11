package com.scalerpro.phantomfleet.http

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.media.MediaScannerConnection
import android.util.Log
import android.graphics.BitmapFactory
import com.scalerpro.phantomfleet.accessibility.IGEngagementHandler
import com.scalerpro.phantomfleet.accessibility.IGStoryFeatureHandler
import com.scalerpro.phantomfleet.accessibility.InstagramPostHandler
import com.scalerpro.phantomfleet.accessibility.ThreadsActionHandler
import com.scalerpro.phantomfleet.accessibility.TikTokActionHandler
import com.scalerpro.phantomfleet.camera.StoryTransformHelper
import com.scalerpro.phantomfleet.camera.VirtualCameraService
import java.io.File
import com.scalerpro.phantomfleet.device.DeviceInfoProvider
import com.scalerpro.phantomfleet.proxy.ProxyStatusChecker
import io.ktor.http.*
import io.ktor.serialization.kotlinx.json.*
import io.ktor.server.application.*
import io.ktor.server.engine.*
import io.ktor.server.netty.*
import io.ktor.server.plugins.contentnegotiation.*
import io.ktor.server.request.*
import io.ktor.server.response.*
import io.ktor.server.routing.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonPrimitive
import java.util.Base64

/**
 * Phantom Fleet embedded HTTP server running on port 8090.
 *
 * Started from [com.scalerpro.phantomfleet.PhantomAccessibilityService] once the
 * accessibility service is connected. The backend calls these routes to dispatch
 * UI actions, read device telemetry, and inject virtual camera frames.
 *
 * All routes return JSON. Errors return {"error": "<message>"} with an
 * appropriate HTTP status code.
 */
class LocalHttpServer(
    private val context: Context,
    private val service: AccessibilityService,
    private val tikTokHandler: TikTokActionHandler,
    private val instagramPostHandler: InstagramPostHandler,
    private val igStoryFeatureHandler: IGStoryFeatureHandler,
    private val igEngagementHandler: IGEngagementHandler,
    private val threadsHandler: ThreadsActionHandler,
    private val virtualCamera: VirtualCameraService,
    private val port: Int = 8090
) {
    private val TAG = "PhantomHTTP"
    private var engine: io.ktor.server.engine.ApplicationEngine? = null

    private val json = Json {
        prettyPrint = false
        ignoreUnknownKeys = true
        isLenient = true
    }

    /** Start the Ktor Netty engine. Safe to call multiple times — no-op if already running. */
    fun start() {
        if (engine != null) return
        engine = embeddedServer(Netty, port = port, host = "0.0.0.0") {
            install(ContentNegotiation) { json(json) }
            routing {
                healthRoutes()
                deviceRoutes()
                cameraRoutes()
                tiktokRoutes()
                instagramRoutes()
                instagramStickerRoutes()
                instagramStoryFeatureRoutes()
                instagramEngageRoutes()
                threadsRoutes()
                mediaRoutes()
                mediaTransformRoutes()
                proxyRoutes()
            }
        }.also { it.start(wait = false) }
        Log.i(TAG, "HTTP server started on port $port")
    }

    /** Gracefully shut down the Ktor engine. */
    fun stop() {
        engine?.stop(gracePeriodMillis = 1_000, timeoutMillis = 3_000)
        engine = null
        Log.i(TAG, "HTTP server stopped")
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Health
    // ──────────────────────────────────────────────────────────────────────────

    private fun Routing.healthRoutes() {
        /**
         * GET /health
         * Response: { "status": "ok", "serial": "<android_id>" }
         */
        get("/health") {
            val serial = DeviceInfoProvider.getAndroidId(context)
            call.respond(HealthResponse(status = "ok", serial = serial))
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Device info
    // ──────────────────────────────────────────────────────────────────────────

    private fun Routing.deviceRoutes() {
        /**
         * GET /device/info
         * Response: hardware model, OS version, android_id, carrier, locale, timezone.
         */
        get("/device/info") {
            call.respond(
                DeviceInfoResponse(
                    model = DeviceInfoProvider.getModel(),
                    android_version = DeviceInfoProvider.getAndroidVersion(),
                    android_id = DeviceInfoProvider.getAndroidId(context),
                    carrier = DeviceInfoProvider.getCarrierName(context),
                    mcc_mnc = DeviceInfoProvider.getMccMnc(context),
                    locale = DeviceInfoProvider.getLocale(),
                    timezone = DeviceInfoProvider.getTimezone()
                )
            )
        }

        /**
         * GET /device/gaid
         * Response: { "gaid": "<advertising_id>" }
         * Fetches Google Advertising ID asynchronously and suspends until resolved.
         */
        get("/device/gaid") {
            val deferred = kotlinx.coroutines.CompletableDeferred<String>()
            DeviceInfoProvider.getAdvertisingId(context) { gaid -> deferred.complete(gaid) }
            val gaid = deferred.await()
            call.respond(GaidResponse(gaid = gaid))
        }

        /**
         * GET /device/installed-packages
         * Response: { "packages": ["com.example.app", ...] }
         */
        get("/device/installed-packages") {
            val packages = DeviceInfoProvider.getInstalledPackages(context)
            call.respond(InstalledPackagesResponse(packages = packages))
        }

        /**
         * GET /device/foreground-package
         *
         * Returns the package name of the app currently in the foreground.
         * Used by the backend "Detect Clone" flow: the user opens their clone app,
         * then the backend calls this endpoint to auto-detect the package name
         * and save it to accounts.clone_package.
         *
         * Response: { "package": "com.instagram.android.clone1" }
         */
        get("/device/foreground-package") {
            val pkg = service.rootInActiveWindow?.let { root ->
                val name = root.packageName?.toString() ?: ""
                root.recycle()
                name
            } ?: ""
            call.respond(ForegroundPackageResponse(pkg = pkg))
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Camera injection
    // ──────────────────────────────────────────────────────────────────────────

    private fun Routing.cameraRoutes() {
        /**
         * POST /camera/inject/stream
         * Injects a list of base64-encoded frames into the virtual camera stream.
         * Body: { "frames": ["<b64>", ...], "fps": 30.0, "replay": { "jitter_ms": 5,
         *         "brightness_adjust": 1.0, "subpixel_shift_x": 0.0, "subpixel_shift_y": 0.0 } }
         */
        post("/camera/inject/stream") {
            val body = call.receive<StreamInjectRequest>()
            val frames = body.frames.map { Base64.getDecoder().decode(it) }
            val replay = VirtualCameraService.ReplayParams(
                jitterMs = body.replay.jitter_ms,
                brightnessAdjust = body.replay.brightness_adjust,
                subpixelShiftX = body.replay.subpixel_shift_x,
                subpixelShiftY = body.replay.subpixel_shift_y
            )
            virtualCamera.receiveStreamFrames(frames, body.fps, replay)
            call.respond(ActionResultResponse(success = true, error = null))
        }

        /**
         * POST /camera/inject/static
         * Injects a single static JPEG for selfie/photo-verification flows.
         * Body: { "image_b64": "<b64>", "brightness_adjust": 1.0, "exif_timestamp_offset": 0 }
         */
        post("/camera/inject/static") {
            val body = call.receive<StaticInjectRequest>()
            val imageBytes = Base64.getDecoder().decode(body.image_b64)
            virtualCamera.receiveStaticImage(
                imageBytes = imageBytes,
                brightnessAdjust = body.brightness_adjust,
                exifTimestampOffset = body.exif_timestamp_offset
            )
            call.respond(ActionResultResponse(success = true, error = null))
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // TikTok actions
    // ──────────────────────────────────────────────────────────────────────────

    private fun Routing.tiktokRoutes() {
        /**
         * POST /tiktok/action
         * Dispatches a single TikTok UI action via the accessibility service.
         * Body: { "action": "<scrollFeed|likeVideo|tapComment|typeComment|tapFollow>",
         *         "params": { ... } }
         */
        post("/tiktok/action") {
            val body = call.receive<TikTokActionRequest>()
            val p = body.params

            fun int(key: String, default: Int) =
                p[key]?.jsonPrimitive?.doubleOrNull?.toInt() ?: default

            fun str(key: String) = p[key]?.jsonPrimitive?.contentOrNull ?: ""

            val result = when (body.action) {
                "scrollFeed"  -> tikTokHandler.scrollFeed(
                    swipeCount = int("swipe_count", 1),
                    durationMs = int("duration_ms", 300)
                )
                "likeVideo"   -> tikTokHandler.likeCurrentVideo(
                    pauseMs = int("pause_ms", 200)
                )
                "tapComment"  -> tikTokHandler.tapComment()
                "typeComment" -> tikTokHandler.typeComment(
                    text = str("text"),
                    keystrokeDelayMs = int("keystroke_delay_ms", 80)
                )
                "tapFollow"   -> tikTokHandler.tapFollow(username = str("username"))
                else -> {
                    call.respond(
                        HttpStatusCode.BadRequest,
                        ActionResultResponse(success = false, error = "Unknown action: ${body.action}")
                    )
                    return@post
                }
            }

            if (result.success) {
                call.respond(ActionResultResponse(success = true, error = null))
            } else {
                call.respond(
                    HttpStatusCode.UnprocessableEntity,
                    ActionResultResponse(success = false, error = result.error)
                )
            }
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Instagram posting
    // ──────────────────────────────────────────────────────────────────────────

    private fun Routing.instagramRoutes() {
        /**
         * POST /instagram/post
         * Posts a grid image/video from the on-device gallery via accessibility service.
         * Body: InstagramPostRequest with postType = "GRID"
         *
         * The media file must already be present on the device at [mediaPath]
         * (pushed via ADB) and visible in the gallery (MediaScanner triggered).
         */
        post("/instagram/post") {
            val req = call.receive<InstagramPostRequest>()
            val postType = try {
                InstagramPostHandler.PostType.valueOf(req.postType.uppercase())
            } catch (e: IllegalArgumentException) {
                call.respond(
                    HttpStatusCode.BadRequest,
                    ActionResultResponse(success = false, error = "Invalid postType: ${req.postType}"),
                )
                return@post
            }
            val result = withContext(Dispatchers.Main) {
                instagramPostHandler.postFromGallery(
                    mediaPath    = req.mediaPath,
                    caption      = req.caption,
                    accountId    = req.accountId,
                    clonePackage = req.clonePackage,
                    postType     = postType,
                )
            }
            if (result.success) {
                call.respond(ActionResultResponse(success = true, error = null))
            } else {
                call.respond(
                    HttpStatusCode.UnprocessableEntity,
                    ActionResultResponse(success = false, error = result.error),
                )
            }
        }

        /**
         * POST /instagram/story
         * Posts a story from gallery. Convenience alias for postType=STORY.
         */
        post("/instagram/story") {
            val req = call.receive<InstagramPostRequest>()
            val result = withContext(Dispatchers.Main) {
                instagramPostHandler.postFromGallery(
                    mediaPath    = req.mediaPath,
                    caption      = req.caption,
                    accountId    = req.accountId,
                    clonePackage = req.clonePackage,
                    postType     = InstagramPostHandler.PostType.STORY,
                )
            }
            if (result.success) {
                call.respond(ActionResultResponse(success = true, error = null))
            } else {
                call.respond(
                    HttpStatusCode.UnprocessableEntity,
                    ActionResultResponse(success = false, error = result.error),
                )
            }
        }

        /**
         * POST /instagram/reel
         * Posts a reel from gallery. Convenience alias for postType=REEL.
         */
        post("/instagram/reel") {
            val req = call.receive<InstagramPostRequest>()
            val result = withContext(Dispatchers.Main) {
                instagramPostHandler.postFromGallery(
                    mediaPath    = req.mediaPath,
                    caption      = req.caption,
                    accountId    = req.accountId,
                    clonePackage = req.clonePackage,
                    postType     = InstagramPostHandler.PostType.REEL,
                )
            }
            if (result.success) {
                call.respond(ActionResultResponse(success = true, error = null))
            } else {
                call.respond(
                    HttpStatusCode.UnprocessableEntity,
                    ActionResultResponse(success = false, error = result.error),
                )
            }
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Instagram story stickers
    // ──────────────────────────────────────────────────────────────────────────

    private fun Routing.instagramStickerRoutes() {
        /**
         * POST /instagram/story/add_poll
         * Adds an interactive poll sticker to the currently-open story editor.
         *
         * Assumes the story editor is already open and the canvas is the active
         * foreground screen (i.e. called between media selection and the
         * final "Your Story" send tap).
         *
         * Body: { "question": "...", "option1": "...", "option2": "..." }
         * Response: { "success": true|false }
         */
        post("/instagram/story/add_poll") {
            val req = call.receive<PollStickerRequest>()
            val ok = withContext(Dispatchers.Main) {
                igStoryFeatureHandler.addPollSticker(
                    question = req.question,
                    option1  = req.option1,
                    option2  = req.option2,
                )
            }
            call.respond(mapOf("success" to ok))
        }

        /**
         * POST /instagram/story/add_question
         * Adds an interactive question sticker to the currently-open story editor.
         *
         * Body: { "prompt": "..." }
         * Response: { "success": true|false }
         */
        post("/instagram/story/add_question") {
            val req = call.receive<QuestionStickerRequest>()
            val ok = withContext(Dispatchers.Main) {
                igStoryFeatureHandler.addQuestionSticker(prompt = req.prompt)
            }
            call.respond(mapOf("success" to ok))
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Instagram story feature routes (highlight, link sticker, close friends)
    // ──────────────────────────────────────────────────────────────────────────

    // These routes are called by ig_story_agent.py for advanced story actions.
    // They all assume the story editor is already open unless noted otherwise.

    // POST /instagram/story/add_highlight
    // POST /instagram/story/add_link_sticker
    // POST /instagram/story/close_friends
    // POST /instagram/story/add_text_overlay
    // POST /instagram/story/repost_from_mother
    // are implemented above via instagramStickerRoutes; adding the new ones here:

    private fun Routing.instagramStoryFeatureRoutes() {
        /**
         * POST /instagram/story/add_to_highlight
         * Adds a just-posted story to a highlight reel.
         * Body: { "highlightName": "...", "createIfMissing": true }
         */
        post("/instagram/story/add_to_highlight") {
            val req = call.receive<AddToHighlightRequest>()
            val ok = withContext(Dispatchers.Main) {
                igStoryFeatureHandler.addStoryToHighlight(
                    highlightName  = req.highlightName,
                    createIfMissing = req.createIfMissing,
                )
            }
            call.respond(ActionResultResponse(success = ok, error = if (ok) null else "highlight_failed"))
        }

        /**
         * POST /instagram/story/add_link_sticker
         * Adds a link sticker to the currently open story editor.
         * Body: { "url": "https://...", "stickerLabel": "Subscribe" }
         */
        post("/instagram/story/add_link_sticker") {
            val req = call.receive<AddLinkStickerRequest>()
            val ok = withContext(Dispatchers.Main) {
                igStoryFeatureHandler.addLinkStickerToStory(
                    url          = req.url,
                    stickerLabel = req.stickerLabel,
                )
            }
            call.respond(ActionResultResponse(success = ok, error = if (ok) null else "link_sticker_failed"))
        }

        /**
         * POST /instagram/story/close_friends
         * Selects Close Friends audience and posts the story.
         * Body: { "mediaPath": "...", "caption": "...", "clonePackage": "..." }
         */
        post("/instagram/story/close_friends") {
            val req = call.receive<InstagramPostRequest>()
            val result = withContext(Dispatchers.Main) {
                igStoryFeatureHandler.postToCloseFriends(
                    mediaPath    = req.mediaPath,
                    caption      = req.caption,
                    clonePackage = req.clonePackage,
                )
            }
            if (result.success) {
                call.respond(ActionResultResponse(success = true, error = null))
            } else {
                call.respond(
                    HttpStatusCode.UnprocessableEntity,
                    ActionResultResponse(success = false, error = result.error),
                )
            }
        }

        /**
         * POST /instagram/story/add_text_overlay
         * Adds a text card to the open story canvas.
         * Body: { "text": "...", "position": "TOP|CENTER|BOTTOM" }
         */
        post("/instagram/story/add_text_overlay") {
            val req = call.receive<AddTextOverlayRequest>()
            val position = try {
                IGStoryFeatureHandler.OverlayPosition.valueOf(req.position.uppercase())
            } catch (_: IllegalArgumentException) {
                IGStoryFeatureHandler.OverlayPosition.CENTER
            }
            val ok = withContext(Dispatchers.Main) {
                igStoryFeatureHandler.addTextOverlay(text = req.text, position = position)
            }
            call.respond(ActionResultResponse(success = ok, error = if (ok) null else "text_overlay_failed"))
        }

        /**
         * POST /instagram/story/repost_from_mother
         * Deep-links to mother account profile, taps story ring, adds story to editor.
         * Body: { "motherUsername": "...", "clonePackage": "..." }
         */
        post("/instagram/story/repost_from_mother") {
            val req = call.receive<RepostFromMotherRequest>()
            val result = withContext(Dispatchers.Main) {
                igStoryFeatureHandler.repostStoryFromMotherAccount(
                    motherUsername = req.motherUsername,
                    clonePackage   = req.clonePackage,
                )
            }
            if (result.success) {
                call.respond(ActionResultResponse(success = true, error = null))
            } else {
                call.respond(
                    HttpStatusCode.UnprocessableEntity,
                    ActionResultResponse(success = false, error = result.error),
                )
            }
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Instagram engagement (follow, unfollow, like, comment, stories, reels, DM)
    // ──────────────────────────────────────────────────────────────────────────

    private fun Routing.instagramEngageRoutes() {
        /**
         * POST /instagram/engage/follow
         * Body: { "username": "...", "clonePackage": "..." }
         * Navigates to the user's profile and taps Follow. Idempotent if already following.
         */
        post("/instagram/engage/follow") {
            val req = call.receive<EngageFollowRequest>()
            val result = withContext(Dispatchers.Main) {
                igEngagementHandler.followUser(
                    username     = req.username,
                    clonePackage = req.clonePackage,
                )
            }
            respondEngageResult(result)
        }

        /**
         * POST /instagram/engage/unfollow
         * Body: { "username": "...", "clonePackage": "..." }
         * Navigates to the user's profile, taps Following → confirms Unfollow.
         */
        post("/instagram/engage/unfollow") {
            val req = call.receive<EngageFollowRequest>()
            val result = withContext(Dispatchers.Main) {
                igEngagementHandler.unfollowUser(
                    username     = req.username,
                    clonePackage = req.clonePackage,
                )
            }
            respondEngageResult(result)
        }

        /**
         * POST /instagram/engage/like
         * Body: { "mediaId": "...", "clonePackage": "..." }
         * Opens the post via deep link and taps the Like heart. Idempotent.
         */
        post("/instagram/engage/like") {
            val req = call.receive<EngageLikeRequest>()
            val result = withContext(Dispatchers.Main) {
                igEngagementHandler.likePost(
                    mediaId      = req.mediaId,
                    clonePackage = req.clonePackage,
                )
            }
            respondEngageResult(result)
        }

        /**
         * POST /instagram/engage/comment
         * Body: { "mediaId": "...", "commentText": "...", "clonePackage": "..." }
         * Opens the post, taps the comment icon, types the comment, and posts it.
         */
        post("/instagram/engage/comment") {
            val req = call.receive<EngageCommentRequest>()
            val result = withContext(Dispatchers.Main) {
                igEngagementHandler.commentOnPost(
                    mediaId      = req.mediaId,
                    commentText  = req.commentText,
                    clonePackage = req.clonePackage,
                )
            }
            respondEngageResult(result)
        }

        /**
         * POST /instagram/engage/view_stories
         * Body: { "username": "...", "storyCount": 5, "clonePackage": "..." }
         * Opens the user's story ring and taps through storyCount segments.
         */
        post("/instagram/engage/view_stories") {
            val req = call.receive<EngageViewStoriesRequest>()
            val result = withContext(Dispatchers.Main) {
                igEngagementHandler.viewStories(
                    username     = req.username,
                    storyCount   = req.storyCount,
                    clonePackage = req.clonePackage,
                )
            }
            respondEngageResult(result)
        }

        /**
         * POST /instagram/engage/scroll_reels
         * Body: { "watchCount": 5, "clonePackage": "..." }
         * Opens Reels tab and scrolls through watchCount reels with LogNormal dwell.
         */
        post("/instagram/engage/scroll_reels") {
            val req = call.receive<EngageScrollReelsRequest>()
            val result = withContext(Dispatchers.Main) {
                igEngagementHandler.scrollReelFeed(
                    watchCount   = req.watchCount,
                    clonePackage = req.clonePackage,
                )
            }
            respondEngageResult(result)
        }

        /**
         * POST /instagram/engage/send_dm
         * Body: { "username": "...", "message": "...", "clonePackage": "..." }
         * Opens DM inbox, searches for user, opens thread, types and sends message.
         */
        post("/instagram/engage/send_dm") {
            val req = call.receive<EngageSendDMRequest>()
            val result = withContext(Dispatchers.Main) {
                igEngagementHandler.sendDM(
                    username     = req.username,
                    message      = req.message,
                    clonePackage = req.clonePackage,
                )
            }
            respondEngageResult(result)
        }

        /**
         * GET /instagram/engage/check_session?clonePackage=<pkg>
         * Launches the clone, waits 3s, checks if home feed is visible.
         * Response: { "loggedIn": true|false, "needsReauth": true|false }
         */
        get("/instagram/engage/check_session") {
            val clonePackage = call.request.queryParameters["clonePackage"] ?: run {
                call.respond(
                    HttpStatusCode.BadRequest,
                    ActionResultResponse(success = false, error = "missing clonePackage query param"),
                )
                return@get
            }
            val status = withContext(Dispatchers.Main) {
                igEngagementHandler.checkSession(clonePackage = clonePackage)
            }
            call.respond(SessionStatusResponse(
                loggedIn    = status.loggedIn,
                needsReauth = status.needsReauth,
            ))
        }
    }

    /** Shared responder: maps [IGEngagementHandler.EngageResult] to HTTP responses. */
    private suspend fun io.ktor.server.application.ApplicationCall.respondEngageResult(
        result: IGEngagementHandler.EngageResult,
    ) {
        if (result.success) {
            respond(ActionResultResponse(success = true, error = null))
        } else {
            respond(
                HttpStatusCode.UnprocessableEntity,
                ActionResultResponse(success = false, error = result.error),
            )
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Threads actions
    // ──────────────────────────────────────────────────────────────────────────

    private fun Routing.threadsRoutes() {
        /**
         * POST /threads/engage/follow
         * Body: { "username": "...", "clonePackage": "com.instagram.barcelona.clone1" }
         */
        post("/threads/engage/follow") {
            val req = call.receive<ThreadsFollowRequest>()
            val result = withContext(Dispatchers.Main) {
                threadsHandler.followUser(username = req.username, clonePackage = req.clonePackage)
            }
            respondThreadsResult(result)
        }

        /**
         * POST /threads/engage/unfollow
         * Body: { "username": "...", "clonePackage": "..." }
         */
        post("/threads/engage/unfollow") {
            val req = call.receive<ThreadsFollowRequest>()
            val result = withContext(Dispatchers.Main) {
                threadsHandler.unfollowUser(username = req.username, clonePackage = req.clonePackage)
            }
            respondThreadsResult(result)
        }

        /**
         * POST /threads/engage/like
         * Body: { "postUrl": "https://www.threads.net/@user/post/CODE", "clonePackage": "..." }
         */
        post("/threads/engage/like") {
            val req = call.receive<ThreadsLikeRequest>()
            val result = withContext(Dispatchers.Main) {
                threadsHandler.likePost(postUrl = req.postUrl, clonePackage = req.clonePackage)
            }
            respondThreadsResult(result)
        }

        /**
         * POST /threads/engage/comment
         * Body: { "postUrl": "...", "commentText": "...", "clonePackage": "..." }
         */
        post("/threads/engage/comment") {
            val req = call.receive<ThreadsCommentRequest>()
            val result = withContext(Dispatchers.Main) {
                threadsHandler.commentOnPost(
                    postUrl     = req.postUrl,
                    commentText = req.commentText,
                    clonePackage = req.clonePackage,
                )
            }
            respondThreadsResult(result)
        }

        /**
         * POST /threads/engage/scroll_feed
         * Body: { "swipeCount": 5, "clonePackage": "..." }
         */
        post("/threads/engage/scroll_feed") {
            val req = call.receive<ThreadsScrollRequest>()
            val result = withContext(Dispatchers.Main) {
                threadsHandler.scrollFeed(
                    swipeCount   = req.swipeCount,
                    clonePackage = req.clonePackage,
                )
            }
            respondThreadsResult(result)
        }

        /**
         * GET /threads/engage/check_session?clonePackage=<pkg>
         * Launches the clone, waits, checks if home feed is visible.
         * Response: { "loggedIn": true|false, "needsReauth": true|false }
         */
        get("/threads/engage/check_session") {
            val clonePackage = call.request.queryParameters["clonePackage"] ?: run {
                call.respond(
                    HttpStatusCode.BadRequest,
                    ActionResultResponse(success = false, error = "missing clonePackage query param"),
                )
                return@get
            }
            val status = withContext(Dispatchers.Main) {
                threadsHandler.checkSession(clonePackage = clonePackage)
            }
            call.respond(SessionStatusResponse(loggedIn = status.loggedIn, needsReauth = status.needsReauth))
        }
    }

    private suspend fun io.ktor.server.application.ApplicationCall.respondThreadsResult(
        result: ThreadsActionHandler.ThreadsResult,
    ) {
        if (result.success) {
            respond(ActionResultResponse(success = true, error = null))
        } else {
            respond(HttpStatusCode.UnprocessableEntity, ActionResultResponse(success = false, error = result.error))
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Media staging
    // ──────────────────────────────────────────────────────────────────────────

    private fun Routing.mediaRoutes() {
        /**
         * POST /media/scan
         * Triggers Android's MediaScanner on [path] so the gallery sees the new file.
         *
         * Call this after ADB-pushing a media file but before posting, so Instagram's
         * gallery picker can find and display the file.
         *
         * Body: { "path": "/sdcard/DCIM/PhantomFleet/abc123.jpg" }
         */
        post("/media/scan") {
            val req = call.receive<MediaScanRequest>()
            MediaScannerConnection.scanFile(
                context,
                arrayOf(req.path),
                null,
            ) { scannedPath, uri ->
                Log.d("PhantomHTTP", "MediaScanner: scanned $scannedPath → $uri")
            }
            call.respond(mapOf("ok" to true))
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Media transform (per-child visual variation for anti-cluster fingerprinting)
    // ──────────────────────────────────────────────────────────────────────────

    private fun Routing.mediaTransformRoutes() {
        /**
         * POST /media/transform
         *
         * Applies per-account visual transforms to an image to prevent content-cluster
         * fingerprinting when many child accounts repost the same mother story frame.
         *
         * The transform pipeline (brightness shift, subtle crop, hue rotation, subpixel
         * noise, JPEG re-encode) is deterministic per (accountId, postIndex) — same
         * inputs always produce the same output, enabling debugging.
         *
         * Body:
         *   {
         *     "inputPath":  "/sdcard/DCIM/PhantomFleet/source.jpg",
         *     "outputPath": "/sdcard/DCIM/PhantomFleet/child_acct001.jpg",
         *     "accountId":  "acct_001",
         *     "postIndex":  0
         *   }
         *
         * Response: { "ok": true, "outputPath": "..." }
         */
        post("/media/transform") {
            val req = call.receive<TransformRequest>()
            val inputBitmap = BitmapFactory.decodeFile(req.inputPath)
                ?: run {
                    call.respond(
                        HttpStatusCode.BadRequest,
                        mapOf("ok" to false, "error" to "cannot_decode:${req.inputPath}"),
                    )
                    return@post
                }

            val transformed = StoryTransformHelper.transform(
                inputBitmap = inputBitmap,
                accountId   = req.accountId,
                postIndex   = req.postIndex,
            )
            inputBitmap.recycle()

            val outputFile = File(req.outputPath)
            outputFile.parentFile?.mkdirs()
            val written = StoryTransformHelper.compressToFile(
                bitmap     = transformed,
                outputPath = req.outputPath,
                quality    = 92,
            )
            transformed.recycle()

            if (written) {
                call.respond(TransformResponse(ok = true, outputPath = req.outputPath))
            } else {
                call.respond(
                    HttpStatusCode.InternalServerError,
                    mapOf("ok" to false, "error" to "write_failed:${req.outputPath}"),
                )
            }
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Proxy status
    // ──────────────────────────────────────────────────────────────────────────

    private fun Routing.proxyRoutes() {
        /**
         * GET /proxy/status?port=8089
         * Returns whether the local SOCKS5 proxy on the given port is reachable.
         */
        get("/proxy/status") {
            val proxyPort = call.request.queryParameters["port"]?.toIntOrNull() ?: 8089
            val active = ProxyStatusChecker.isProxyActive(proxyPort)
            call.respond(ProxyStatusResponse(active = active, port = proxyPort))
        }

        /**
         * POST /proxy/status
         * Body: { "port": 8089 }
         */
        post("/proxy/status") {
            val body = runCatching { call.receive<ProxyStatusRequest>() }.getOrElse { ProxyStatusRequest() }
            val active = ProxyStatusChecker.isProxyActive(body.port)
            call.respond(ProxyStatusResponse(active = active, port = body.port))
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Wire types (request / response DTOs)
    // ──────────────────────────────────────────────────────────────────────────

    @Serializable
    data class HealthResponse(val status: String, val serial: String)

    @Serializable
    data class DeviceInfoResponse(
        val model: String,
        val android_version: String,
        val android_id: String,
        val carrier: String,
        val mcc_mnc: String,
        val locale: String,
        val timezone: String
    )

    @Serializable
    data class GaidResponse(val gaid: String)

    @Serializable
    data class InstalledPackagesResponse(val packages: List<String>)

    @Serializable
    data class ActionResultResponse(val success: Boolean, val error: String?)

    @Serializable
    data class ProxyStatusResponse(val active: Boolean, val port: Int)

    @Serializable
    data class ProxyStatusRequest(val port: Int = 8089)

    @Serializable
    data class ReplayParamsWire(
        val jitter_ms: Int = 0,
        val brightness_adjust: Float = 1.0f,
        val subpixel_shift_x: Float = 0f,
        val subpixel_shift_y: Float = 0f
    )

    @Serializable
    data class StreamInjectRequest(
        val frames: List<String>,
        val fps: Float,
        val replay: ReplayParamsWire = ReplayParamsWire()
    )

    @Serializable
    data class StaticInjectRequest(
        val image_b64: String,
        val brightness_adjust: Float = 1.0f,
        val exif_timestamp_offset: Int = 0
    )

    @Serializable
    data class TikTokActionRequest(
        val action: String,
        val params: JsonObject = JsonObject(emptyMap())
    )

    /**
     * Request body for all Instagram posting endpoints.
     *
     * @param mediaPath    Absolute on-device path to the media file, e.g.
     *                     /sdcard/DCIM/PhantomFleet/abc123.jpg
     * @param caption      Caption text. May be empty for stories/reels.
     * @param accountId    Phantom Fleet account ID — for logging only.
     * @param clonePackage Package name of the Instagram clone to use.
     * @param postType     "GRID", "STORY", or "REEL". Defaults to "GRID".
     */
    @Serializable
    data class InstagramPostRequest(
        val mediaPath: String,
        val caption: String,
        val accountId: String,
        val clonePackage: String,
        val postType: String = "GRID",
    )

    /**
     * Request body for /media/scan — triggers MediaScanner so the gallery
     * picks up a file pushed via ADB.
     */
    @Serializable
    data class MediaScanRequest(val path: String)

    /**
     * Request body for POST /instagram/story/add_poll.
     *
     * @param question  The poll question text, e.g. "Which content do you prefer? 🔥"
     * @param option1   First option label, e.g. "Spicy 🌶️"
     * @param option2   Second option label, e.g. "Sweet 🍯"
     */
    @Serializable
    data class PollStickerRequest(
        val question: String,
        val option1: String,
        val option2: String,
    )

    /**
     * Request body for POST /instagram/story/add_question.
     *
     * @param prompt  The question prompt text, e.g. "Ask me anything 💬"
     */
    @Serializable
    data class QuestionStickerRequest(val prompt: String)

    /** POST /instagram/story/add_to_highlight */
    @Serializable
    data class AddToHighlightRequest(
        val highlightName: String,
        val createIfMissing: Boolean = true,
    )

    /** POST /instagram/story/add_link_sticker */
    @Serializable
    data class AddLinkStickerRequest(
        val url: String,
        val stickerLabel: String = "",
    )

    /** POST /instagram/story/add_text_overlay */
    @Serializable
    data class AddTextOverlayRequest(
        val text: String,
        val position: String = "BOTTOM",
    )

    /** POST /instagram/story/repost_from_mother */
    @Serializable
    data class RepostFromMotherRequest(
        val motherUsername: String,
        val clonePackage: String,
    )

    /**
     * Request body for POST /media/transform.
     *
     * @param inputPath   Absolute on-device path to the source image.
     * @param outputPath  Absolute on-device path to write the transformed image.
     * @param accountId   Account ID — seeds deterministic transform parameters.
     * @param postIndex   Post sequence counter — ensures different transform each post.
     */
    @Serializable
    data class TransformRequest(
        val inputPath:  String,
        val outputPath: String,
        val accountId:  String,
        val postIndex:  Int,
    )

    /** Response body for POST /media/transform. */
    @Serializable
    data class TransformResponse(
        val ok: Boolean,
        val outputPath: String,
    )

    // ── Engagement request DTOs ───────────────────────────────────────────────

    /** POST /instagram/engage/follow and /instagram/engage/unfollow */
    @Serializable
    data class EngageFollowRequest(
        val username: String,
        val clonePackage: String,
    )

    /** POST /instagram/engage/like */
    @Serializable
    data class EngageLikeRequest(
        val mediaId: String,
        val clonePackage: String,
    )

    /** POST /instagram/engage/comment */
    @Serializable
    data class EngageCommentRequest(
        val mediaId: String,
        val commentText: String,
        val clonePackage: String,
    )

    /** POST /instagram/engage/view_stories */
    @Serializable
    data class EngageViewStoriesRequest(
        val username: String,
        val storyCount: Int = 5,
        val clonePackage: String,
    )

    /** POST /instagram/engage/scroll_reels */
    @Serializable
    data class EngageScrollReelsRequest(
        val watchCount: Int = 5,
        val clonePackage: String,
    )

    /** POST /instagram/engage/send_dm */
    @Serializable
    data class EngageSendDMRequest(
        val username: String,
        val message: String,
        val clonePackage: String,
    )

    /** GET /instagram/engage/check_session response */
    @Serializable
    data class SessionStatusResponse(
        val loggedIn: Boolean,
        val needsReauth: Boolean,
    )

    // ── Foreground package detection ──────────────────────────────────────────

    /** GET /device/foreground-package response */
    @Serializable
    data class ForegroundPackageResponse(val pkg: String)

    // ── Threads request DTOs ──────────────────────────────────────────────────

    /** POST /threads/engage/follow and /threads/engage/unfollow */
    @Serializable
    data class ThreadsFollowRequest(
        val username: String,
        val clonePackage: String,
    )

    /** POST /threads/engage/like */
    @Serializable
    data class ThreadsLikeRequest(
        val postUrl: String,
        val clonePackage: String,
    )

    /** POST /threads/engage/comment */
    @Serializable
    data class ThreadsCommentRequest(
        val postUrl: String,
        val commentText: String,
        val clonePackage: String,
    )

    /** POST /threads/engage/scroll_feed */
    @Serializable
    data class ThreadsScrollRequest(
        val swipeCount: Int = 5,
        val clonePackage: String,
    )
}
