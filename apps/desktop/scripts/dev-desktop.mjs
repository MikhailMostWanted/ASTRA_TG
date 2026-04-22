import { spawn } from "node:child_process";
import process from "node:process";

const apiUrl = (process.env.VITE_ASTRA_DESKTOP_API_URL || "http://127.0.0.1:8765").replace(/\/$/, "");
const pythonExecutable = process.env.ASTRA_DESKTOP_API_PYTHON || "python3";
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const desktopRoot = new URL("..", import.meta.url);
const repoRoot = new URL("../../..", import.meta.url);

let apiProcess = null;

async function isApiReachable() {
  try {
    const response = await fetch(`${apiUrl}/health`);
    return response.ok;
  } catch {
    return false;
  }
}

function parseApiTarget(url) {
  const target = new URL(url);
  return {
    host: target.hostname,
    port: target.port ? Number(target.port) : 8765,
  };
}

function startApiIfNeeded() {
  const { host, port } = parseApiTarget(apiUrl);
  apiProcess = spawn(
    pythonExecutable,
    ["-m", "apps.desktop_api", "--host", host, "--port", String(port)],
    {
      cwd: repoRoot,
      env: process.env,
      stdio: "inherit",
    }
  );

  const cleanup = () => {
    if (apiProcess && !apiProcess.killed) {
      apiProcess.kill("SIGTERM");
    }
  };

  process.on("exit", cleanup);
  process.on("SIGINT", () => {
    cleanup();
    process.exit(130);
  });
  process.on("SIGTERM", () => {
    cleanup();
    process.exit(143);
  });
}

async function waitForApi(timeoutMs = 12000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await isApiReachable()) {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  return false;
}

async function main() {
  if (!(await isApiReachable())) {
    startApiIfNeeded();
    const ready = await waitForApi();
    if (!ready) {
      console.error(`Desktop API did not become ready at ${apiUrl}`);
      process.exit(1);
    }
  }

  const child = spawn(npmCommand, ["run", "tauri", "--", "dev"], {
    cwd: desktopRoot,
    env: process.env,
    stdio: "inherit",
  });

  child.on("exit", (code) => {
    if (apiProcess && !apiProcess.killed) {
      apiProcess.kill("SIGTERM");
    }
    process.exit(code ?? 0);
  });
}

await main();
