package com.scalerpro.phantomfleet.device

import android.content.Context
import android.os.Build
import android.provider.Settings
import android.telephony.TelephonyManager
import android.util.Log
import com.google.android.gms.ads.identifier.AdvertisingIdClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.util.Locale
import java.util.TimeZone

/**
 * Reads static and semi-static device hardware / OS properties.
 *
 * All methods are safe to call from any thread. [getAdvertisingId] is async
 * because the Play Services GAID lookup requires a background thread.
 */
object DeviceInfoProvider {

    private const val TAG = "PhantomDevice"

    // ──────────────────────────────────────────────────────────────────────────
    // Hardware / OS
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Returns a human-readable device model string, e.g. "Samsung Galaxy S21".
     * Combines manufacturer + model, deduplicating when manufacturer already
     * appears at the start of the model string.
     */
    fun getModel(): String {
        val manufacturer = Build.MANUFACTURER.trim()
        val model = Build.MODEL.trim()
        return if (model.startsWith(manufacturer, ignoreCase = true)) model
        else "$manufacturer $model"
    }

    /**
     * Returns the Android version release string, e.g. "14" or "13".
     */
    fun getAndroidVersion(): String = Build.VERSION.RELEASE

    /**
     * Returns [Settings.Secure.ANDROID_ID] — a 64-bit number in hex that is
     * unique per app/signing key on Android 8+. Returns "unknown" on failure.
     */
    fun getAndroidId(context: Context): String =
        Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)
            ?: "unknown"

    // ──────────────────────────────────────────────────────────────────────────
    // Advertising ID (async — requires Google Play Services)
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Fetches the Google Advertising ID on a background thread and delivers
     * the result via [callback].
     *
     * Returns "00000000-0000-0000-0000-000000000000" when:
     * - the user has opted out of ad personalisation, or
     * - Play Services is unavailable.
     *
     * Must NOT be called on the main thread.
     */
    fun getAdvertisingId(context: Context, callback: (String) -> Unit) {
        CoroutineScope(Dispatchers.IO).launch {
            val gaid = try {
                val info = AdvertisingIdClient.getAdvertisingIdInfo(context.applicationContext)
                if (info.isLimitAdTrackingEnabled) {
                    "00000000-0000-0000-0000-000000000000"
                } else {
                    info.id ?: "00000000-0000-0000-0000-000000000000"
                }
            } catch (e: Exception) {
                Log.w(TAG, "GAID fetch failed: ${e.message}")
                "00000000-0000-0000-0000-000000000000"
            }
            callback(gaid)
        }
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Carrier / network
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Returns the SIM operator display name, e.g. "T-Mobile". Falls back to
     * "unknown" when no SIM is present or READ_PHONE_STATE is not granted.
     */
    fun getCarrierName(context: Context): String {
        val tm = context.getSystemService(Context.TELEPHONY_SERVICE) as? TelephonyManager
        return tm?.networkOperatorName?.takeIf { it.isNotBlank() } ?: "unknown"
    }

    /**
     * Returns the MCC+MNC string of the registered network, e.g. "310260".
     * Falls back to empty string when unavailable.
     */
    fun getMccMnc(context: Context): String {
        val tm = context.getSystemService(Context.TELEPHONY_SERVICE) as? TelephonyManager
        return tm?.networkOperator?.takeIf { it.isNotBlank() } ?: ""
    }

    // ──────────────────────────────────────────────────────────────────────────
    // Locale / time
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Returns the default locale BCP-47 language tag, e.g. "en-US".
     */
    fun getLocale(): String = Locale.getDefault().toLanguageTag()

    /**
     * Returns the default timezone ID, e.g. "America/New_York".
     */
    fun getTimezone(): String = TimeZone.getDefault().id

    // ──────────────────────────────────────────────────────────────────────────
    // Installed packages
    // ──────────────────────────────────────────────────────────────────────────

    /**
     * Returns a sorted list of all installed application package names.
     * Requires QUERY_ALL_PACKAGES permission (already declared in manifest).
     */
    fun getInstalledPackages(context: Context): List<String> {
        val pm = context.packageManager
        return pm.getInstalledPackages(0)
            .map { it.packageName }
            .sorted()
    }
}
