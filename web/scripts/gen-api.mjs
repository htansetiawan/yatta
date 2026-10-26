// Regenerate src/api/schema.d.ts from the backend's OpenAPI document (no running server needed).
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";

const python = process.env.YATTA_PYTHON ?? "../backend/.venv/bin/python";
const spec = execFileSync(python, ["-c", "import json; from yatta.app import create_app; print(json.dumps(create_app().openapi(), indent=1))"],
  { cwd: "../backend", encoding: "utf8" });
writeFileSync("openapi.json", spec);
execFileSync("npx", ["openapi-typescript", "openapi.json", "-o", "src/api/schema.d.ts"], { stdio: "inherit" });
