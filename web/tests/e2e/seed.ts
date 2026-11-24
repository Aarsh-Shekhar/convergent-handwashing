import { execFileSync } from "node:child_process";
import { PORT, TOKEN } from "../../playwright.config";

/** Fill the test backend with the demo family (the same script the demo uses). */
export function seed() {
  execFileSync(".venv/bin/python", ["scripts/seed_demo_family.py", "--url", `http://127.0.0.1:${PORT}`, "--reset", "--timezone", process.env.E2E_TZ ?? "America/Chicago"],
    { cwd: "..", env: { ...process.env, CONVERGENT_API_TOKEN: TOKEN }, stdio: "pipe" });
}
export default seed;
