#!/usr/bin/env node
/**
 * Read ELK-BPMN JSON from stdin (or a file path arg) and print BPMN 2.0 XML
 * with DI from bpmn-elk-layout. Exit non-zero on failure; errors go to stderr.
 */
import { readFileSync } from "node:fs";
import { BpmnElkLayout } from "bpmn-elk-layout/node";

function readInput() {
  const arg = process.argv[2];
  if (!arg || arg === "-") {
    return readFileSync(0, "utf8");
  }
  return readFileSync(arg, "utf8");
}

async function main() {
  const raw = readInput();
  let json;
  try {
    json = JSON.parse(raw);
  } catch (err) {
    console.error(`bpmn_elk: invalid JSON: ${err.message || err}`);
    process.exit(2);
  }
  try {
    const converter = new BpmnElkLayout();
    const xml = await converter.to_bpmn(json);
    if (!xml || typeof xml !== "string" || !xml.includes("bpmndi:BPMN")) {
      console.error("bpmn_elk: layout returned empty or DI-less XML");
      process.exit(3);
    }
    process.stdout.write(xml.endsWith("\n") ? xml : `${xml}\n`);
  } catch (err) {
    console.error(`bpmn_elk: layout failed: ${err.message || err}`);
    process.exit(4);
  }
}

main();
