/**
 * 5-layer architecture diagram — SVG.
 * Top layer: SaaS multi-tenant shell → Agent Mesh → Execution Router → Persona Core → Hardware Fabric.
 * Used on the features page + docs.
 */
export function ArchitectureDiagram() {
  return (
    <div className="phantom-panel p-8">
      <svg viewBox="0 0 900 560" className="w-full h-auto" fill="none">
        <defs>
          <linearGradient id="layerGradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="hsl(162 100% 54%)" stopOpacity="0.15" />
            <stop offset="50%" stopColor="hsl(162 100% 54%)" stopOpacity="0.25" />
            <stop offset="100%" stopColor="hsl(162 100% 54%)" stopOpacity="0.15" />
          </linearGradient>
          <linearGradient id="layerBorder" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="hsl(162 100% 54%)" stopOpacity="0.4" />
            <stop offset="100%" stopColor="hsl(292 91% 68%)" stopOpacity="0.4" />
          </linearGradient>
          <filter id="glow">
            <feGaussianBlur stdDeviation="4" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Layer 5 — SaaS multi-tenant */}
        <g>
          <rect x="60" y="40" width="780" height="80" rx="12"
                fill="url(#layerGradient)" stroke="url(#layerBorder)" strokeWidth="1.5" />
          <text x="84" y="68" fill="hsl(240 5% 64.9%)" fontSize="11" fontFamily="'JetBrains Mono', monospace"
                letterSpacing="1.5">LAYER 5 · SAAS</text>
          <text x="84" y="96" fill="white" fontSize="20" fontWeight="700" fontFamily="Inter"
                letterSpacing="-0.02em">Multi-tenant shell · Stripe + Crypto billing · White-label</text>
        </g>

        <path d="M 450 125 L 450 145" stroke="hsl(162 100% 54%)" strokeWidth="2" filter="url(#glow)" />

        {/* Layer 4 — Agent mesh */}
        <g>
          <rect x="60" y="150" width="780" height="90" rx="12"
                fill="url(#layerGradient)" stroke="url(#layerBorder)" strokeWidth="1.5" />
          <text x="84" y="178" fill="hsl(240 5% 64.9%)" fontSize="11" fontFamily="'JetBrains Mono', monospace"
                letterSpacing="1.5">LAYER 4 · AI AGENT MESH</text>
          <text x="84" y="204" fill="white" fontSize="18" fontWeight="700" fontFamily="Inter"
                letterSpacing="-0.02em">14 autonomous agents</text>
          <text x="84" y="224" fill="hsl(240 5% 64.9%)" fontSize="11" fontFamily="'JetBrains Mono', monospace">
            warming · fresh_target · source_discovery · fingerprint_monitor · dm · content · recovery ·
          </text>
          <text x="84" y="236" fill="hsl(240 5% 64.9%)" fontSize="11" fontFamily="'JetBrains Mono', monospace">
            replacement · proxy · persona_factory · growth · funnel · scout · audit_harness
          </text>
        </g>

        <path d="M 450 245 L 450 265" stroke="hsl(162 100% 54%)" strokeWidth="2" filter="url(#glow)" />

        {/* Layer 3 — Execution router */}
        <g>
          <rect x="60" y="270" width="780" height="70" rx="12"
                fill="url(#layerGradient)" stroke="url(#layerBorder)" strokeWidth="1.5" />
          <text x="84" y="298" fill="hsl(240 5% 64.9%)" fontSize="11" fontFamily="'JetBrains Mono', monospace"
                letterSpacing="1.5">LAYER 3 · EXECUTION ROUTER</text>
          <text x="84" y="322" fill="white" fontSize="18" fontWeight="700" fontFamily="Inter"
                letterSpacing="-0.02em">Pure real-device · mother/slave amplification</text>
        </g>

        <path d="M 450 345 L 450 365" stroke="hsl(162 100% 54%)" strokeWidth="2" filter="url(#glow)" />

        {/* Layer 2 — Persona core */}
        <g>
          <rect x="60" y="370" width="780" height="80" rx="12"
                fill="url(#layerGradient)" stroke="url(#layerBorder)" strokeWidth="1.5" />
          <text x="84" y="398" fill="hsl(240 5% 64.9%)" fontSize="11" fontFamily="'JetBrains Mono', monospace"
                letterSpacing="1.5">LAYER 2 · PERSONA CORE</text>
          <text x="84" y="422" fill="white" fontSize="18" fontWeight="700" fontFamily="Inter"
                letterSpacing="-0.02em">Cross-platform persona primitive · biometrics locked at creation</text>
          <text x="84" y="440" fill="hsl(240 5% 64.9%)" fontSize="11" fontFamily="'JetBrains Mono', monospace">
            accounts die · personas never do
          </text>
        </g>

        <path d="M 450 455 L 450 475" stroke="hsl(162 100% 54%)" strokeWidth="2" filter="url(#glow)" />

        {/* Layer 1 — Hardware fabric */}
        <g>
          <rect x="60" y="480" width="780" height="60" rx="12"
                fill="url(#layerGradient)" stroke="url(#layerBorder)" strokeWidth="1.5" />
          <text x="84" y="506" fill="hsl(240 5% 64.9%)" fontSize="11" fontFamily="'JetBrains Mono', monospace"
                letterSpacing="1.5">LAYER 1 · HARDWARE FABRIC</text>
          <text x="84" y="528" fill="white" fontSize="18" fontWeight="700" fontFamily="Inter"
                letterSpacing="-0.02em">Samsung S10 Lite fleet · Phantom Fleet Companion APK · Wi-Fi ADB</text>
        </g>

        {/* Side annotations */}
        <g fontSize="10" fontFamily="'JetBrains Mono', monospace" fill="hsl(162 100% 54%)" opacity="0.7">
          <text x="860" y="80" textAnchor="end">TENANCY</text>
          <text x="860" y="200" textAnchor="end">AUTONOMY</text>
          <text x="860" y="310" textAnchor="end">ROUTING</text>
          <text x="860" y="410" textAnchor="end">IDENTITY</text>
          <text x="860" y="510" textAnchor="end">PHYSICAL</text>
        </g>
      </svg>
    </div>
  );
}
