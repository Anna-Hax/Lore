// Copies each Lore contract's ABI from Foundry's out/ to packages/shared/src/abi/<Name>.json.
// Run from contracts/ after `forge build`:  node script/export-abi.mjs
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const CONTRACTS = ['LoreRoles', 'MockUSDC', 'TopicGraph', 'Submissions', 'Access', 'Royalties', 'Reports'];

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(root, '..', 'packages', 'shared', 'src', 'abi');
mkdirSync(outDir, { recursive: true });

for (const name of CONTRACTS) {
  const artifact = JSON.parse(readFileSync(join(root, 'out', `${name}.sol`, `${name}.json`), 'utf8'));
  writeFileSync(join(outDir, `${name}.json`), JSON.stringify(artifact.abi, null, 2) + '\n');
  console.log(`abi/${name}.json (${artifact.abi.length} entries)`);
}
