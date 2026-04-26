"use strict";

const fs = require("node:fs");
const path = require("node:path");

const nextDir = path.join(__dirname, "..", ".next");
fs.rmSync(nextDir, { recursive: true, force: true });
// eslint-disable-next-line no-console -- CLI script
console.log(`Removed ${nextDir}`);
