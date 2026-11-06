import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";
import license from "rollup-plugin-license";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const staticDirectory = fileURLToPath(new URL("../src/betonning/static/", import.meta.url));

function dependencyNotices(dependencies) {
  // Preflight/CSS komt uit Tailwind en staat buiten de JavaScript-modulegraaf.
  const tailwind = JSON.parse(readFileSync(new URL("./node_modules/tailwindcss/package.json", import.meta.url), "utf8"));
  const tailwindText = readFileSync(new URL("./node_modules/tailwindcss/LICENSE", import.meta.url), "utf8");
  dependencies = [...dependencies, {
    name: tailwind.name, version: tailwind.version, license: tailwind.license,
    licenseText: tailwindText,
    text: () => `Name: ${tailwind.name}\nVersion: ${tailwind.version}\nLicense: ${tailwind.license}\nSource: generated frontend CSS\n\n${tailwindText}`,
  }];
  for (const dependency of dependencies) {
    // Deze package mist SPDX-metadata; de meegeleverde tekst is expliciet MIT.
    if (dependency.name === "svelte-toolbelt" && dependency.version === "0.10.6"
        && /^MIT License\s/.test(dependency.licenseText || "")) dependency.license = "MIT";
    if (dependency.private || !dependency.licenseText || !["MIT", "ISC", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "Python-2.0"].includes(dependency.license)) {
      throw new Error(`Licentiereview nodig voor ${dependency.name}@${dependency.version}`);
    }
  }
  const ordered = [...dependencies].sort((a,b) => a.name.localeCompare(b.name, "en"));
  mkdirSync(staticDirectory, { recursive: true });
  writeFileSync(staticDirectory + "third-party-licenses.txt",
    "Third-party frontend licenses for Hegemone\n\n" + ordered.map(dependency => dependency.text()).join("\n---\n\n"));
  writeFileSync(staticDirectory + "third-party-packages.json", JSON.stringify(ordered.map(({name, version, license}) => ({name, version, license})), null, 2) + "\n");
}

// Build → src/betonning/static/, geserveerd door FastAPI (StaticFiles).
// base: "/" zodat asset-paden absoluut zijn (`/assets/...`). Cruciaal met de
// path-routing (BETON-6): op een genest pad als `/BETON/6` zouden relatieve
// paden (`./assets/...`) naar `/BETON/assets/...` resolven en 404'en.
export default defineConfig({
  plugins: [tailwindcss(), svelte(), {
    ...license({
      banner: { content: "Third-party notices: /third-party-licenses.txt", commentStyle: "ignored" },
      thirdParty: { includePrivate: true, output: dependencyNotices },
    }),
    apply: "build",
  }],
  base: "/",
  build: {
    outDir: "../src/betonning/static",
    emptyOutDir: true,
  },
  server: {
    // Dev-proxy: /api en /health naar de FastAPI-dev-server.
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.js"],
  },
});
