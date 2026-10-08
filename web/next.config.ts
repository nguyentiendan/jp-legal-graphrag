import type { NextConfig } from "next";

// Static export → build ra thư mục out/ và được Nginx phục vụ (xem web/nginx/).
// Mọi lời gọi API dùng đường dẫn tương đối /api → Nginx reverse proxy tới service api:8000.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
};

export default nextConfig;
