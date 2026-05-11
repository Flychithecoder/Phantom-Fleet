/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    optimizePackageImports: ["lucide-react", "recharts", "framer-motion"],
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: "http://localhost:8002/api/v1/:path*",
      },
      {
        source: "/ws/:path*",
        destination: "http://localhost:8002/ws/:path*",
      },
    ];
  },
};

export default nextConfig;
