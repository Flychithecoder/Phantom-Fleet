package com.scalerpro.phantomfleet.proxy

import android.util.Log
import java.net.InetSocketAddress
import java.net.Socket

/**
 * Checks whether the local SOCKS5 proxy daemon (typically USBProxy or tun2socks
 * forwarded from the backend host) is reachable on the given loopback port.
 *
 * The check is a raw TCP connect — it does NOT validate the SOCKS5 handshake,
 * only that something is listening on the port. A 1-second connect timeout
 * prevents the check from blocking the HTTP handler.
 */
object ProxyStatusChecker {

    private const val TAG = "PhantomProxy"
    private const val DEFAULT_PORT = 8089
    private const val CONNECT_TIMEOUT_MS = 1_000

    /**
     * Returns `true` if a TCP connection to `127.0.0.1:[port]` succeeds within
     * [CONNECT_TIMEOUT_MS] milliseconds.
     *
     * Safe to call from any thread. Runs synchronously — wrap in Dispatchers.IO
     * when calling from a coroutine context.
     *
     * @param port The local SOCKS5 proxy port to probe (default 8089).
     */
    fun isProxyActive(port: Int = DEFAULT_PORT): Boolean {
        return try {
            Socket().use { socket ->
                socket.connect(InetSocketAddress("127.0.0.1", port), CONNECT_TIMEOUT_MS)
                true
            }
        } catch (e: Exception) {
            Log.d(TAG, "Proxy not active on port $port: ${e.message}")
            false
        }
    }
}
