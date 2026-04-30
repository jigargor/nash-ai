const fs = require("node:fs");
const path = require("node:path");

function readUtf8(relativePath) {
  const fullPath = path.join(__dirname, "..", relativePath);
  return fs.readFileSync(fullPath, "utf8");
}

function assertIncludes(content, fragment, label, failures) {
  if (!content.includes(fragment)) failures.push(label);
}

function main() {
  const failures = [];

  const robots = readUtf8("src/app/robots.ts");
  assertIncludes(robots, "disallow: [\"/dashboard\", \"/repos\", \"/reviews\", \"/settings\", \"/code-tour\", \"/api\"]", "robots disallow rules", failures);

  const sitemap = readUtf8("src/app/sitemap.ts");
  for (const publicPath of ["/about", "/privacy", "/terms"]) {
    assertIncludes(sitemap, `"${publicPath}"`, `sitemap includes ${publicPath}`, failures);
  }

  const loginPage = readUtf8("src/app/(auth)/login/page.tsx");
  assertIncludes(loginPage, "noindex: true", "login noindex", failures);

  const dashboardLayout = readUtf8("src/app/(dashboard)/layout.tsx");
  assertIncludes(dashboardLayout, "noindex: true", "dashboard noindex", failures);

  const publicPages = [
    "src/app/about/page.tsx",
    "src/app/privacy/page.tsx",
    "src/app/terms/page.tsx",
  ];
  for (const pagePath of publicPages) {
    const page = readUtf8(pagePath);
    assertIncludes(page, "buildSeoMetadata({", `${pagePath} uses shared SEO metadata`, failures);
    if (page.includes("noindex: true")) failures.push(`${pagePath} should not be noindex`);
  }

  if (failures.length > 0) {
    console.error("SEO guardrail check failed:");
    for (const failure of failures) console.error(`- ${failure}`);
    process.exit(1);
  }

  console.log("SEO guardrail check passed.");
}

main();
