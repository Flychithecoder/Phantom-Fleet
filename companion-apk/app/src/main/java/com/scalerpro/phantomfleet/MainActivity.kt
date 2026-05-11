package com.scalerpro.phantomfleet

import android.os.Bundle
import android.provider.Settings
import android.content.Intent
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    StatusScreen(
                        onEnableAccessibility = {
                            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
                        }
                    )
                }
            }
        }
    }
}

@Composable
fun StatusScreen(onEnableAccessibility: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Text("Phantom Fleet Companion", style = MaterialTheme.typography.headlineMedium)
        Text("A Scaler Pro product", style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(24.dp))
        Text("Service status: stub (Phase 0 scaffold)")
        Text("HTTP server: not yet started")
        Button(onClick = onEnableAccessibility) {
            Text("Enable Accessibility Service")
        }
    }
}
