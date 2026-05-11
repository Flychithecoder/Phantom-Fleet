import { Panel } from "@/components/panel";
import { StatRing } from "@/components/stat-ring";
import { Sparkline } from "@/components/sparkline";
import { Users } from "lucide-react";

const PERSONAS = [
  {
    id: "tatiana",
    name: "Tatiana",
    gender: "Female, 22, NYC",
    accounts: 97,
    alive: 97,
    phones: 9,
    aggressiveness: 1.08,
    survival30d: 0.994,
    engagement: 0.067,
    conversion: 0.032,
    of_revenue: 2_340,
    sparkline: [22, 28, 31, 25, 29, 34, 38, 41, 37, 42, 44, 39, 45, 48, 52],
  },
  {
    id: "melodie",
    name: "Melodie",
    gender: "Female, 21, Brooklyn",
    accounts: 122,
    alive: 121,
    phones: 10,
    aggressiveness: 0.96,
    survival30d: 0.992,
    engagement: 0.081,
    conversion: 0.045,
    of_revenue: 3_120,
    sparkline: [18, 24, 27, 30, 33, 31, 36, 40, 42, 45, 43, 48, 51, 49, 54],
  },
];

export default function PersonasPage() {
  return (
    <div className="space-y-8">
      <div>
        <div className="text-[11px] uppercase tracking-[0.15em] text-phantom-ghost font-medium">
          Cross-platform identity layer
        </div>
        <h1 className="font-display text-4xl font-bold mt-2 tracking-tight flex items-center gap-3">
          <Users className="w-9 h-9 text-phantom-accent" strokeWidth={1.5} />
          <span className="phantom-accent-text">Personas</span>
        </h1>
        <p className="text-phantom-ghost mt-2 text-sm max-w-xl">
          Accounts die. Personas never do. Each persona spans every platform with a consistent
          identity, biometric profile, and targeting source config. When an account under a
          persona dies, a replacement is auto-provisioned under the same identity.
        </p>
      </div>

      {PERSONAS.map((p) => (
        <Panel
          key={p.id}
          label={`persona · ${p.id}`}
          title={
            <span className="flex items-center gap-3">
              <span>{p.name}</span>
              <span className="text-xs text-phantom-ghost font-normal">{p.gender}</span>
            </span>
          }
          subtitle="Locked biometrics, aggressiveness, active hours, peak hour, device model, OS version — all sampled once and immutable."
        >
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 items-center">
            <div className="flex justify-center">
              <StatRing
                value={p.survival30d}
                label="30-day survival"
                sub={`${p.alive}/${p.accounts}`}
                color="phantom-alive"
              />
            </div>
            <div className="flex justify-center">
              <StatRing
                value={p.engagement}
                label="engagement rate"
                color="phantom-accent"
              />
            </div>
            <div className="flex justify-center">
              <StatRing
                value={p.conversion}
                label="funnel conversion"
                color="phantom-magenta"
              />
            </div>
            <div className="lg:col-span-2 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">Accounts</div>
                  <div className="phantom-metric text-3xl">{p.accounts}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">Phones</div>
                  <div className="phantom-metric text-3xl">{p.phones}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">Aggressiveness</div>
                  <div className="phantom-metric text-2xl tabular-nums">{p.aggressiveness.toFixed(2)}×</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost">OF revenue (30d)</div>
                  <div className="phantom-metric text-2xl tabular-nums text-phantom-accent">
                    ${p.of_revenue.toLocaleString()}
                  </div>
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-[0.15em] text-phantom-ghost mb-1">
                  Follower growth · 15d
                </div>
                <Sparkline data={p.sparkline} label="followers/day" />
              </div>
            </div>
          </div>
        </Panel>
      ))}
    </div>
  );
}
