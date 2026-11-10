import path from "node:path";
import type { NextConfig } from "next";

// 정적 빌드: web/out을 FastAPI(app/api.py)가 제공한다. 센터 PC에 Node가 없어도 실행된다.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  turbopack: {
    root: path.resolve(__dirname),
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
