/**
 * Read-only BPMN diagram preview (bpmn-js NavigatedViewer).
 * Generated BA XML often has no BPMNDI — inject a simple left-to-right layout.
 */

import NavigatedViewer from 'bpmn-js/lib/NavigatedViewer';
import 'bpmn-js/dist/assets/diagram-js.css';
import 'bpmn-js/dist/assets/bpmn-js.css';
import 'bpmn-js/dist/assets/bpmn-font/css/bpmn-embedded.css';

const BPMN_NS = 'http://www.omg.org/spec/BPMN/20100524/MODEL';
const BPMNDI_NS = 'http://www.omg.org/spec/BPMN/20100524/DI';
const DC_NS = 'http://www.omg.org/spec/DD/20100524/DC';
const DI_NS = 'http://www.omg.org/spec/DD/20100524/DI';

const FLOW_NODES = new Set([
  'startEvent',
  'endEvent',
  'intermediateCatchEvent',
  'intermediateThrowEvent',
  'boundaryEvent',
  'task',
  'userTask',
  'serviceTask',
  'sendTask',
  'receiveTask',
  'scriptTask',
  'businessRuleTask',
  'manualTask',
  'callActivity',
  'subProcess',
  'exclusiveGateway',
  'parallelGateway',
  'inclusiveGateway',
  'eventBasedGateway',
  'complexGateway',
]);

let viewer = null;
let importGen = 0;

export function resizeBpmnPreview() {
  if (!viewer) return;
  try {
    const canvas = viewer.get('canvas');
    canvas.resized();
    canvas.zoom('fit-viewport', 'auto');
  } catch {
    /* viewport may be 0 during layout */
  }
}

export function destroyBpmnPreview() {
  importGen += 1;
  if (!viewer) return;
  try {
    viewer.destroy();
  } catch {
    /* already gone */
  }
  viewer = null;
}

export async function renderBpmnDiagram(container, xml) {
  const gen = ++importGen;
  if (viewer) {
    try {
      viewer.destroy();
    } catch {
      /* ignore */
    }
    viewer = null;
  }
  if (!container) return;

  container.dataset.bpmnReady = 'false';
  delete container.dataset.bpmnError;
  container.replaceChildren();

  try {
    const withDi = ensureBpmnDi(xml);
    if (gen !== importGen) return;

    const instance = new NavigatedViewer({ container });
    viewer = instance;
    await instance.importXML(withDi);
    if (gen !== importGen || viewer !== instance) return;

    try {
      instance.get('canvas').zoom('fit-viewport', 'auto');
    } catch {
      /* viewport may be 0 during layout */
    }
    container.dataset.bpmnReady = 'true';
  } catch (err) {
    if (gen !== importGen) return;
    if (viewer) {
      try {
        viewer.destroy();
      } catch {
        /* ignore */
      }
      viewer = null;
    }
    container.dataset.bpmnReady = 'false';
    container.dataset.bpmnError = '1';
    const msg = document.createElement('div');
    msg.className = 'bpmn-preview-error';
    msg.textContent = 'Không thể vẽ sơ đồ BPMN. XML không hợp lệ hoặc thiếu diagram.';
    container.replaceChildren(msg);
    console.warn('BPMN preview failed:', err);
  }
}

export function ensureBpmnDi(xml) {
  const text = String(xml || '').trim();
  if (!text) {
    throw new Error('Empty BPMN XML');
  }
  const doc = new DOMParser().parseFromString(text, 'application/xml');
  const parseError = doc.querySelector('parsererror');
  if (parseError) {
    throw new Error('BPMN XML is not well-formed');
  }
  if (doc.getElementsByTagNameNS(BPMNDI_NS, 'BPMNDiagram').length > 0) {
    return text;
  }
  if (doc.getElementsByTagName('BPMNDiagram').length > 0) {
    return text;
  }
  injectDiagramInterchange(doc);
  return new XMLSerializer().serializeToString(doc);
}

function injectDiagramInterchange(doc) {
  const defs = doc.documentElement;
  if (!defs) {
    throw new Error('BPMN XML has no root element');
  }
  const process = firstByLocalName(defs, 'process');
  if (!process) {
    throw new Error('BPMN XML has no process');
  }

  defs.setAttribute('xmlns:bpmndi', BPMNDI_NS);
  defs.setAttribute('xmlns:dc', DC_NS);
  defs.setAttribute('xmlns:di', DI_NS);

  const nodes = [];
  const outgoing = new Map();
  const incoming = new Map();
  const flows = [];

  for (const child of process.children) {
    const local = child.localName;
    const id = child.getAttribute('id');
    if (!id) continue;
    if (FLOW_NODES.has(local)) {
      nodes.push({ id, local });
      if (!outgoing.has(id)) outgoing.set(id, []);
      if (!incoming.has(id)) incoming.set(id, []);
    } else if (local === 'sequenceFlow') {
      const source = child.getAttribute('sourceRef');
      const target = child.getAttribute('targetRef');
      flows.push({ id, source, target });
      if (source && target) {
        if (!outgoing.has(source)) outgoing.set(source, []);
        outgoing.get(source).push(target);
        if (!incoming.has(target)) incoming.set(target, []);
        incoming.get(target).push(source);
      }
    }
  }

  if (nodes.length === 0) {
    throw new Error('BPMN process has no flow nodes');
  }

  const placed = layoutNodes(nodes, outgoing, incoming);
  const processId = process.getAttribute('id') || 'Process_1';

  const diagram = doc.createElementNS(BPMNDI_NS, 'bpmndi:BPMNDiagram');
  diagram.setAttribute('id', 'BPMNDiagram_preview');
  const plane = doc.createElementNS(BPMNDI_NS, 'bpmndi:BPMNPlane');
  plane.setAttribute('id', 'BPMNPlane_preview');
  plane.setAttribute('bpmnElement', processId);

  for (const node of nodes) {
    const box = placed.get(node.id);
    const shape = doc.createElementNS(BPMNDI_NS, 'bpmndi:BPMNShape');
    shape.setAttribute('id', `${node.id}_di`);
    shape.setAttribute('bpmnElement', node.id);
    if (node.local.toLowerCase().includes('gateway')) {
      shape.setAttribute('isMarkerVisible', 'true');
    }
    const bounds = doc.createElementNS(DC_NS, 'dc:Bounds');
    bounds.setAttribute('x', String(box.x));
    bounds.setAttribute('y', String(box.y));
    bounds.setAttribute('width', String(box.w));
    bounds.setAttribute('height', String(box.h));
    shape.appendChild(bounds);
    plane.appendChild(shape);
  }

  for (const flow of flows) {
    const src = placed.get(flow.source);
    const tgt = placed.get(flow.target);
    if (!src || !tgt || !flow.id) continue;
    const edge = doc.createElementNS(BPMNDI_NS, 'bpmndi:BPMNEdge');
    edge.setAttribute('id', `${flow.id}_di`);
    edge.setAttribute('bpmnElement', flow.id);
    for (const [x, y] of edgeWaypoints(src, tgt)) {
      const wp = doc.createElementNS(DI_NS, 'di:waypoint');
      wp.setAttribute('x', String(x));
      wp.setAttribute('y', String(y));
      edge.appendChild(wp);
    }
    plane.appendChild(edge);
  }

  diagram.appendChild(plane);
  defs.appendChild(diagram);
}

function firstByLocalName(parent, localName) {
  for (const child of parent.children) {
    if (child.localName === localName) return child;
  }
  return parent.getElementsByTagNameNS(BPMN_NS, localName)[0] || null;
}

function nodeSize(localName) {
  const name = localName.toLowerCase();
  if (name.includes('gateway')) return { w: 50, h: 50 };
  if (name.includes('event')) return { w: 36, h: 36 };
  return { w: 100, h: 80 };
}

function layoutNodes(nodes, outgoing, incoming) {
  const colWidth = 170;
  const rowHeight = 130;
  const originX = 80;
  const originY = 80;
  const placed = new Map();
  const visited = new Set();
  const colCount = new Map();

  const starts = nodes.filter((n) => (incoming.get(n.id) || []).length === 0);
  const queue = (starts.length ? starts : [nodes[0]]).map((n) => ({ id: n.id, col: 0 }));

  while (queue.length) {
    const { id, col } = queue.shift();
    if (visited.has(id)) continue;
    visited.add(id);
    const meta = nodes.find((n) => n.id === id);
    if (!meta) continue;
    const size = nodeSize(meta.local);
    const row = colCount.get(col) || 0;
    colCount.set(col, row + 1);
    placed.set(id, {
      x: originX + col * colWidth,
      y: originY + row * rowHeight,
      w: size.w,
      h: size.h,
    });
    for (const next of outgoing.get(id) || []) {
      if (!visited.has(next)) queue.push({ id: next, col: col + 1 });
    }
  }

  for (const node of nodes) {
    if (placed.has(node.id)) continue;
    const size = nodeSize(node.local);
    const col = Math.max(0, ...colCount.keys(), 0);
    const row = colCount.get(col) || 0;
    colCount.set(col, row + 1);
    placed.set(node.id, {
      x: originX + col * colWidth,
      y: originY + row * rowHeight,
      w: size.w,
      h: size.h,
    });
  }
  return placed;
}

function edgeWaypoints(src, tgt) {
  const sx = src.x + src.w;
  const sy = Math.round(src.y + src.h / 2);
  const tx = tgt.x;
  const ty = Math.round(tgt.y + tgt.h / 2);
  if (Math.abs(sy - ty) < 4) {
    return [[sx, sy], [tx, ty]];
  }
  const mx = Math.round((sx + tx) / 2);
  return [[sx, sy], [mx, sy], [mx, ty], [tx, ty]];
}
