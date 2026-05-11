import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";
import { TopBar } from "@/components/top-bar";
import { CommandPalette } from "@/components/command-palette";
import { AgentChatWidget } from "@/components/agent-chat-widget";

export const metadata: Metadata = {
  title: "Phantom Fleet — Fleet Command",
  description: "Invisible automation at fleet scale. A Scaler Pro product.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className="min-h-screen bg-phantom-bg font-sans antialiased">
        <div className="phantom-grid-bg h-screen flex overflow-hidden">
          <Sidebar />
          <div className="flex-1 flex flex-col h-screen overflow-hidden">
            <TopBar />
            <main className="flex-1 overflow-y-auto px-8 py-6">
              <div className="max-w-[1600px] w-full mx-auto">
                {children}
              </div>
            </main>
          </div>
        </div>
        <CommandPalette />
        <AgentChatWidget />
      </body>
    </html>
  );
}
