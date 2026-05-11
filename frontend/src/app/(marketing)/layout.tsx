import Link from "next/link";

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="phantom-grid-bg min-h-screen">
      <nav className="h-16 border-b border-phantom-border/50 backdrop-blur-xl sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6 h-full flex items-center justify-between">
          <Link href="/welcome" className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-md bg-gradient-accent flex items-center justify-center shadow-[0_0_24px_hsl(162_100%_54%/0.4)]">
              <span className="text-phantom-bg font-black text-sm">Φ</span>
            </div>
            <span className="font-display font-bold text-base tracking-tight">
              PHANTOM<span className="text-phantom-ghost ml-1 font-medium tracking-[0.2em] text-xs">FLEET</span>
            </span>
          </Link>
          <div className="hidden md:flex items-center gap-8 text-sm text-phantom-ghost">
            <Link href="/features" className="hover:text-white transition-colors">Features</Link>
            <Link href="/pricing" className="hover:text-white transition-colors">Pricing</Link>
            <Link href="/comparison" className="hover:text-white transition-colors">Compare</Link>
            <Link href="/docs" className="hover:text-white transition-colors">Docs</Link>
            <Link href="/" className="px-4 h-9 flex items-center rounded-lg bg-phantom-accent text-phantom-bg font-semibold text-sm shadow-[0_0_24px_hsl(162_100%_54%/0.3)] hover:shadow-[0_0_32px_hsl(162_100%_54%/0.5)] transition-shadow">
              Open App
            </Link>
          </div>
        </div>
      </nav>
      <main>{children}</main>
      <footer className="border-t border-phantom-border/50 py-12 mt-24">
        <div className="max-w-7xl mx-auto px-6 flex items-center justify-between text-xs text-phantom-ghost">
          <span>© 2026 Phantom Fleet · A Scaler Pro product</span>
          <span className="font-mono">v0.0.1</span>
        </div>
      </footer>
    </div>
  );
}
