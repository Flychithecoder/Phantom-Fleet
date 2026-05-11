plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.serialization") version "2.0.20"
}

android {
    namespace = "com.scalerpro.phantomfleet"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.scalerpro.phantomfleet"
        minSdk = 28   // Android 9 minimum (covers all S10 Lites in the fleet)
        targetSdk = 34
        versionCode = 1
        versionName = "0.0.1"
    }

    buildFeatures {
        compose = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.15"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    packaging {
        resources {
            // Ktor + Netty bundle duplicate META-INF entries
            excludes += "/META-INF/INDEX.LIST"
            excludes += "/META-INF/io.netty.versions.properties"
            excludes += "/META-INF/DEPENDENCIES"
        }
    }
}

dependencies {
    // ── Compose / UI ──────────────────────────────────────────────────────────
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.compose.ui:ui:1.7.5")
    implementation("androidx.compose.material3:material3:1.3.1")
    implementation("androidx.compose.ui:ui-tooling-preview:1.7.5")

    // ── Ktor embedded HTTP server ─────────────────────────────────────────────
    // Server core + Netty engine
    implementation("io.ktor:ktor-server-core:3.0.1")
    implementation("io.ktor:ktor-server-netty:3.0.1")
    // JSON content negotiation (kotlinx.serialization)
    implementation("io.ktor:ktor-server-content-negotiation:3.0.1")
    implementation("io.ktor:ktor-serialization-kotlinx-json:3.0.1")
    // Ktor client — used for proxy connectivity checks if needed
    implementation("io.ktor:ktor-client-core:3.0.1")
    implementation("io.ktor:ktor-client-okhttp:3.0.1")

    // ── kotlinx.serialization runtime ────────────────────────────────────────
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")

    // ── Google Advertising ID ─────────────────────────────────────────────────
    // AdvertisingIdClient lives in play-services-ads-identifier (no full ads SDK needed)
    implementation("com.google.android.gms:play-services-ads-identifier:18.1.0")

    // ── CameraX — preview surface + ImageCapture for frame injection ──────────
    val cameraxVersion = "1.4.1"
    implementation("androidx.camera:camera-core:$cameraxVersion")
    implementation("androidx.camera:camera-camera2:$cameraxVersion")
    implementation("androidx.camera:camera-lifecycle:$cameraxVersion")
    // CameraX View (optional — needed if you add a preview SurfaceView to MainActivity)
    implementation("androidx.camera:camera-view:$cameraxVersion")

    // ── Coroutines ────────────────────────────────────────────────────────────
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.9.0")

    // ── Lifecycle (for foreground service coroutine scope) ───────────────────
    implementation("androidx.lifecycle:lifecycle-service:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
}
