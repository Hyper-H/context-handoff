import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";


const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
await mkdir(dist, { recursive: true });

await build({
  entryPoints: [path.join(root, "src", "server.ts")],
  bundle: true,
  format: "esm",
  platform: "node",
  target: "node20",
  outfile: path.join(dist, "server.mjs"),
  sourcemap: false,
  logLevel: "warning",
});

const browser = await build({
  entryPoints: [path.join(root, "web", "app.ts")],
  bundle: true,
  format: "esm",
  platform: "browser",
  target: ["es2022"],
  write: false,
  minify: true,
  logLevel: "warning",
});
const script = browser.outputFiles.find((file) => file.path.endsWith(".js")) ?? browser.outputFiles[0];
if (!script) {
  throw new Error("Widget JavaScript bundle was not produced.");
}

const [template, css] = await Promise.all([
  readFile(path.join(root, "web", "widget.html"), "utf8"),
  readFile(path.join(root, "web", "styles.css"), "utf8"),
]);
const html = template
  .replace("<!-- AWH_STYLE -->", () => `<style>${css}</style>`)
  .replace(
    "<!-- AWH_SCRIPT -->",
    () => `<script type="module">${script.text.replaceAll("</script", "<\\/script")}</script>`,
  );
if (html.includes("<!-- AWH_STYLE -->") || html.includes("<!-- AWH_SCRIPT -->")) {
  throw new Error("Widget template still contains unreplaced build markers.");
}
await writeFile(path.join(dist, "widget.html"), html, "utf8");
