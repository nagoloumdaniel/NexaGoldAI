import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const roots = ["src/app", "src/components", "src/lib"];
const mojibake = /Ã|Â|â†|â€|�/;
const requiredLabels = [
  "Achat",
  "Vente",
  "Attente",
  "Pas de trade",
  "Tendance haussière",
  "Tendance baissière",
  "Absente broker",
  "Clôturée broker",
  "Expected-return paper",
];

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    const stat = statSync(path);
    if (stat.isDirectory()) return files(path);
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

const failures = [];
for (const root of roots) {
  for (const file of files(root)) {
    const text = readFileSync(file, "utf8");
    if (mojibake.test(text)) failures.push(`${file}: caractères corrompus`);
  }
}

const labels = readFileSync("src/lib/labels.ts", "utf8");
for (const label of requiredLabels) {
  if (!labels.includes(label)) failures.push(`labels.ts: libellé manquant "${label}"`);
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}

console.log("UI text check OK");
