/**
 * /manifest.webmanifest
 *
 * What Android and desktop Chrome read when someone adds the site to a home
 * screen or installs it: the name under the icon, the icon itself, and the colour
 * of the window chrome. Without it the home-screen tile is a screenshot of the page.
 *
 * The icons are the same artwork as app/icon.png (256px) and app/apple-icon.png,
 * plus a 192px copy in public/ because that is the size Android asks for. No new
 * drawing: public/icon-192.png is app/icon.png resized.
 *
 * `theme_color` and `background_color` are the light `--bg` from app/layout.tsx's
 * viewport block; a manifest takes one value, and light is the site's default.
 */

import type { MetadataRoute } from "next";

import { SITE_NAME, HOME_DESCRIPTION } from "@/lib/site";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: SITE_NAME,
    short_name: SITE_NAME,
    description: HOME_DESCRIPTION,
    start_url: "/",
    display: "browser",
    background_color: "#fbfbfd",
    theme_color: "#fbfbfd",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon.png", sizes: "256x256", type: "image/png" },
      { src: "/apple-icon.png", sizes: "180x180", type: "image/png" },
    ],
  };
}
