const ITEMS = [
  {
    name: "Growth agency owner",
    role: "40+ client accounts, 4 verticals",
    quote: "I was burning 40 accounts a week on Onimator. Moved to Phantom Fleet and my survival rate went from 60 days to 180+ in the first month. The cluster monitor alone is worth more than the subscription.",
  },
  {
    name: "DTC brand marketer",
    role: "Dropship store, organic IG growth",
    quote: "The Fresh Target Agent pulled 2,400 fresh US followers for my niche in the first day. I stopped manually maintaining source lists and my store's organic traffic doubled in 6 weeks. The audit harness catches things I never even thought to check.",
  },
  {
    name: "Agency manager",
    role: "Manages multiple creators and brands",
    quote: "The per-persona ROI view changed how I allocate phone time. I can see exactly which accounts drive conversions and which are dead weight. I reallocated resources and 3x'd revenue in 6 weeks without buying a single new phone.",
  },
  {
    name: "Solo creator",
    role: "Single operator, 5 accounts",
    quote: "I don't run an agency. I just needed one thing that worked on my personal growth. The 14-agent mesh runs while I sleep and I wake up to a report every morning. Cluster detection saved me twice from account loss.",
  },
  {
    name: "Lead gen operator",
    role: "B2B cold outreach via DM",
    quote: "Phantom Fleet's DM agent lets me run cold outreach that actually sounds human. The LLM-tell filter matters more than I expected — my reply rates are 3x what I got with raw GPT output.",
  },
  {
    name: "OFM agency founder",
    role: "Runs creators on multiple platforms",
    quote: "We needed cross-platform unification. Phantom Fleet's persona primitive lets one model's identity exist across IG, Threads, Reddit, TikTok with consistent biometrics. No other tool does that.",
  },
];

export function Testimonials() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
      {ITEMS.map((t, i) => (
        <div key={i} className="phantom-panel p-6 flex flex-col">
          <div className="text-phantom-accent text-3xl leading-none mb-3">"</div>
          <p className="text-sm text-phantom-ghost flex-1 leading-relaxed">{t.quote}</p>
          <div className="mt-6 pt-4 border-t border-phantom-border">
            <div className="font-display font-semibold text-sm">{t.name}</div>
            <div className="text-xs text-phantom-ghost mt-0.5">{t.role}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
