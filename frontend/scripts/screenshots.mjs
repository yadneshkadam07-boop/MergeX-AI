/**
 * Capture the screenshots in docs/screenshots/ against the real stack.
 *
 * Nothing here is mocked: it starts the API on a throwaway SQLite database,
 * serves the production frontend build, imports real projects through the
 * UI, and photographs what happens. The live-progress shot uses a GitHub
 * import precisely because it takes long enough to photograph mid-run; the
 * dashboard shots use the bundled demo because its findings are fixed and
 * the picture is therefore reproducible.
 *
 * Usage (from frontend/):
 *   npm run screenshots
 */

import { spawn } from "node:child_process";
import { openSync } from "node:fs";
import { mkdir, rm } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..");
const FRONTEND = join(ROOT, "frontend");
const BACKEND = join(ROOT, "backend");
const OUT = join(ROOT, "docs", "screenshots");

const API_PORT = 8077;
const WEB_PORT = 4178;
const API = `http://127.0.0.1:${API_PORT}`;
const WEB = `http://127.0.0.1:${WEB_PORT}`;

/**
 * A real React + FastAPI project: exactly what MergeX is for, and big
 * enough (250 files, ~6s end to end) that the stepper can be photographed
 * mid-run rather than already finished.
 */
const LIVE_REPO = "https://github.com/fastapi/full-stack-fastapi-template";

const PYTHON = join(BACKEND, ".venv", "Scripts", "python.exe");
const SCRATCH = join(ROOT, ".screenshots");

const children = [];

/**
 * Start a long-running server, with its output in a log file.
 *
 * Inheriting stdio buries the capture progress under server logs, and —
 * worse — leaves nothing to read when a server dies mid-run.
 */
function serve(command, args, logName, options = {}) {
  const log = openSync(join(SCRATCH, logName), "a");
  const child = spawn(command, args, { stdio: ["ignore", log, log], shell: false, ...options });
  child.on("exit", (code) => {
    if (code !== 0 && code !== null) {
      console.error(`  ! ${logName} exited with code ${code} — see ${join(SCRATCH, logName)}`);
    }
  });
  children.push(child);
  return child;
}

/** Fail loudly rather than letting Playwright time out on a dead server. */
async function assertAlive(label) {
  const response = await fetch(`${API}/health`).catch(() => null);
  if (!response?.ok) {
    throw new Error(`The API is not responding before "${label}". See ${join(SCRATCH, "api.log")}`);
  }
}

function once(command, args, options = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, { stdio: "inherit", shell: false, ...options });
    child.on("error", reject);
    child.on("exit", (code) =>
      code === 0 ? resolvePromise() : reject(new Error(`${command} exited ${code}`)),
    );
  });
}

async function waitFor(url, label, timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Not up yet.
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`${label} did not become ready at ${url}`);
}

function shutDown() {
  for (const child of children) {
    if (!child.killed) {
      try {
        process.platform === "win32"
          ? spawn("taskkill", ["/pid", String(child.pid), "/f", "/t"], { stdio: "ignore" })
          : child.kill("SIGTERM");
      } catch {
        // Best effort.
      }
    }
  }
}

async function shoot(page, name) {
  const path = join(OUT, `${name}.png`);
  await page.screenshot({ path, fullPage: false, animations: "disabled" });
  console.log(`  captured ${name}.png`);
}

async function setTheme(page, theme) {
  const current = await page.evaluate(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  );
  if (current !== theme) {
    await page.getByRole("button", { name: /switch to .* theme/i }).click();
    await page.waitForTimeout(250);
  }
}

async function main() {
  await rm(SCRATCH, { recursive: true, force: true });
  await mkdir(SCRATCH, { recursive: true });
  await mkdir(OUT, { recursive: true });

  console.log("› preparing database");
  const dbFile = join(SCRATCH, "screenshots.db");
  await once(PYTHON, [join(ROOT, "scripts", "screenshot_db.py"), dbFile], { cwd: ROOT });

  console.log("› starting API");
  serve(
    PYTHON,
    ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(API_PORT)],
    "api.log",
    {
      cwd: BACKEND,
      env: {
        ...process.env,
        APP_ENV: "local",
        LOG_LEVEL: "WARNING",
        DATABASE_URL: `sqlite+aiosqlite:///${dbFile.replaceAll("\\", "/")}`,
        WORKSPACE_DIR: join(SCRATCH, "workspace"),
        RATE_LIMIT_PER_MINUTE: "100000",
        CORS_ORIGINS: WEB,
        GEMINI_API_KEY: "",
      },
    },
  );
  await waitFor(`${API}/health`, "API");

  console.log("› building frontend");
  await once("npm", ["run", "build"], {
    cwd: FRONTEND,
    shell: true,
    env: { ...process.env, VITE_API_BASE_URL: API },
  });

  console.log("› serving frontend");
  // Vite's JS entry point, run by this same node: Node 26 refuses to spawn
  // a .cmd shim without a shell, and a shell would detach the child from
  // the clean-up below.
  serve(
    process.execPath,
    [
      join(FRONTEND, "node_modules", "vite", "bin", "vite.js"),
      "preview",
      "--port",
      String(WEB_PORT),
      "--strictPort",
    ],
    "web.log",
    { cwd: FRONTEND },
  );
  await waitFor(WEB, "frontend");

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    colorScheme: "dark",
  });
  const page = await context.newPage();

  try {
    console.log("› landing page");
    await page.goto(WEB);
    await page.getByRole("heading", { name: /layers actually fit together/i }).waitFor();
    await setTheme(page, "dark");
    await shoot(page, "01-landing-dark");
    await setTheme(page, "light");
    await shoot(page, "02-landing-light");
    await setTheme(page, "dark");

    await assertAlive("live analysis");
    console.log(`› live analysis (importing ${LIVE_REPO})`);
    await page.getByLabel("Repository URL").fill(LIVE_REPO);
    await page.getByRole("button", { name: /analyse repository/i }).click();
    // The clone takes seconds, so the stepper really is mid-run here.
    await page.waitForURL(/\/analyses\/[0-9a-f-]+$/, { timeout: 120_000 });
    await page.getByTestId("stage-stepper").waitFor();
    await page.waitForTimeout(1_200);
    await shoot(page, "03-analysis-live");

    // Let it finish, then photograph the completed stepper before it
    // redirects to the report.
    // The page moves on to the report shortly after the run finishes, so
    // this shot is opportunistic: it is the stepper's finished state, not a
    // state the user has to sit in.
    try {
      await page.getByRole("heading", { name: /analysis complete/i }).waitFor({ timeout: 300_000 });
      await shoot(page, "04-analysis-complete");
    } catch {
      console.log("  (missed the completed stepper; it redirects quickly)");
    }

    await assertAlive("demo analysis");
    console.log("› demo analysis");
    await page.goto(WEB);
    await page.getByRole("button", { name: /load demo/i }).click();
    await page.waitForURL(/\/analyses\/[0-9a-f-]+\/report$/, { timeout: 180_000 });
    await page.getByRole("heading", { name: /demo/i }).waitFor();
    await page.waitForTimeout(800); // let the charts settle
    await shoot(page, "05-dashboard-dark");

    await setTheme(page, "light");
    await shoot(page, "06-dashboard-light");
    await setTheme(page, "dark");

    console.log("› issue drawer");
    await page.getByRole("row", { name: /typo/i }).first().click();
    await page.getByRole("dialog").waitFor();
    await page.waitForTimeout(400);
    await shoot(page, "07-issue-drawer");

    // Wait for the dialog to detach, not just for the key press: while it is
    // open Radix hides the rest of the page from the accessibility tree, so
    // a role query made too early finds nothing.
    await page.keyboard.press("Escape");
    await page.getByRole("dialog").waitFor({ state: "detached" });

    console.log("› coverage tab");
    await page.getByRole("tab", { name: /what was checked/i }).click();
    // The drawer restores the scroll position it was opened at, which can be
    // past the end of a shorter tab's content.
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(400);
    await shoot(page, "08-coverage");

    console.log("› architecture placeholder");
    await page.getByRole("tab", { name: /architecture/i }).click();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(300);
    await shoot(page, "09-architecture-placeholder");

    console.log("› mobile");
    const mobile = await browser.newContext({
      viewport: { width: 390, height: 844 },
      deviceScaleFactor: 2,
      colorScheme: "dark",
    });
    const small = await mobile.newPage();
    await small.goto(page.url().replace(/#.*$/, ""));
    await small.evaluate(() => window.scrollTo(0, 0));
    await small.waitForTimeout(1_200);
    await small.screenshot({ path: join(OUT, "10-dashboard-mobile.png"), animations: "disabled" });
    console.log("  captured 10-dashboard-mobile.png");
    await mobile.close();
  } finally {
    await browser.close();
  }

  console.log(`\nScreenshots written to ${OUT}`);
}

process.on("exit", shutDown);
process.on("SIGINT", () => {
  shutDown();
  process.exit(130);
});

main()
  .then(() => {
    shutDown();
    process.exit(0);
  })
  .catch((error) => {
    console.error(error);
    shutDown();
    process.exit(1);
  });
