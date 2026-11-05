import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import path, { dirname } from "node:path";

export type TelegramWorkerState =
  | "disabled"
  | "blocked"
  | "starting"
  | "running"
  | "stopped";

type WorkerEnvironment = Record<string, string | undefined>;
type WorkerLogger = (state: TelegramWorkerState, category?: string) => void;

export interface TelegramWorkerHandle {
  state: TelegramWorkerState;
  child?: ChildProcess;
}

const REQUIRED_PRODUCTION_SETTINGS = [
  "TELEGRAM_BOT_TOKEN",
  "ADMIN_TELEGRAM_ID",
  "PRO_SIGNALS_CHANNEL_ID",
  "MARKET_ANALYSIS_CHANNEL_ID",
] as const;

export function shouldStartTelegramWorker(env: WorkerEnvironment): boolean {
  return env.NODE_ENV === "production" &&
    env.SMH_ENABLE_TELEGRAM_WORKER === "true";
}

export function isTestEnvironment(env: WorkerEnvironment): boolean {
  return env.SMH_TEST_MODE === "1" ||
    env.SMH_ISOLATED_TEST_INSTANCE === "true" ||
    Boolean(env.SMH_TEST_DATABASE_URL) ||
    env.SMH_TEST_DATABASE_SCHEMA === "smh_test";
}

export function missingWorkerSettings(env: WorkerEnvironment): string[] {
  const missing: string[] = REQUIRED_PRODUCTION_SETTINGS.filter(
    (key) => !env[key]?.trim(),
  );
  if (!env.SMH_DATABASE_URL?.trim() && !env.DATABASE_URL?.trim()) {
    missing.push("DATABASE_URL");
  }
  return missing;
}

export function resolveWorkspaceRoot(
  startDirectory: string,
  pathExists: typeof existsSync = existsSync,
): string {
  let candidate = path.resolve(startDirectory);
  for (let depth = 0; depth < 6; depth += 1) {
    if (
      pathExists(path.join(candidate, "main.py")) &&
      pathExists(path.join(candidate, "pyproject.toml"))
    ) {
      return candidate;
    }
    const parent = dirname(candidate);
    if (parent === candidate) break;
    candidate = parent;
  }
  return path.resolve(startDirectory);
}

export function startTelegramWorker(options: {
  env: WorkerEnvironment;
  workspaceRoot: string;
  spawnProcess?: typeof spawn;
  pathExists?: typeof existsSync;
  log?: WorkerLogger;
}): TelegramWorkerHandle {
  const {
    env,
    workspaceRoot,
    spawnProcess = spawn,
    pathExists = existsSync,
    log = () => {},
  } = options;

  if (!shouldStartTelegramWorker(env)) {
    log("disabled");
    return { state: "disabled" };
  }

  if (isTestEnvironment(env)) {
    log("blocked", "test_environment_not_allowed");
    return { state: "blocked" };
  }

  const missing = missingWorkerSettings(env);
  if (missing.length > 0) {
    // Log names only; environment values may contain secrets.
    log("blocked", `missing_settings:${missing.join(",")}`);
    return { state: "blocked" };
  }

  const pythonPath = path.join(workspaceRoot, ".venv", "bin", "python");
  if (!pathExists(pythonPath)) {
    log("blocked", "python_environment_missing");
    return { state: "blocked" };
  }

  let child: ChildProcess;
  try {
    child = spawnProcess(pythonPath, ["main.py"], {
      cwd: workspaceRoot,
      env: { ...env, PYTHONUNBUFFERED: "1" },
      stdio: "inherit",
    });
  } catch {
    log("blocked", "worker_spawn_failed");
    return { state: "blocked" };
  }

  let state: TelegramWorkerState = "starting";
  const updateState = (next: TelegramWorkerState, category?: string) => {
    state = next;
    log(next, category);
  };

  child.once("spawn", () => updateState("running"));
  child.once("error", (error: NodeJS.ErrnoException) => {
    updateState("stopped", `worker_process_error:${error.code ?? "unknown"}`);
  });
  child.once("exit", (code, signal) => {
    const category = code === 0
      ? "worker_exit:clean"
      : `worker_exit:${signal ? "signal" : `code_${code ?? "unknown"}`}`;
    updateState("stopped", category);
  });

  return {
    get state() {
      return state;
    },
    child,
  };
}

export function stopTelegramWorker(child?: ChildProcess): void {
  if (child && child.exitCode === null && !child.killed) {
    child.kill("SIGTERM");
  }
}
