import fs from "node:fs";
import path from "node:path";
import routesDocument from "../config/static-model-routes.json" with { type: "json" };
import { buildStarterRoutePolicy } from "../src/model-routing.ts";

const output = process.argv[2] || path.resolve("config/starter-route-policy.json");
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, JSON.stringify(buildStarterRoutePolicy(routesDocument), null, 2) + "\n", { mode: 0o644 });
console.log("starter policy written: " + output);
