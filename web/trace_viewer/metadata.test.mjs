import test from "node:test";
import assert from "node:assert/strict";

import {
  computeDisplayEdges,
  computeScheduledStartTimes,
  computeToolGraphMetrics,
} from "./metadata.mjs";

test("computeScheduledStartTimes serializes stateful tools before ready stateless tools", () => {
  const trace = {
    nodes: [
      {
        id: 0,
        name: "llm",
        type: "llm",
        time: 20,
        edge_to: [
          { id: 1, interval: 0 },
          { id: 2, interval: 0 },
          { id: 3, interval: 0 },
          { id: 4, interval: 0 },
        ],
      },
      { id: 1, name: "omega_stateful", type: "tool_use", time: 50, edge_to: [] },
      { id: 2, name: "beta_stateless", type: "tool_use", time: 50, edge_to: [] },
      {
        id: 3,
        name: "alpha_stateful",
        type: "tool_use",
        time: 50,
        edge_to: [{ id: 5, interval: 0 }],
      },
      {
        id: 4,
        name: "gamma_stateless",
        type: "tool_use",
        time: 50,
        edge_to: [{ id: 5, interval: 0 }],
      },
      { id: 5, name: "delta_join", type: "tool_use", time: 10, edge_to: [] },
    ],
  };

  const startTimes = computeScheduledStartTimes(trace, {
    1: "stateful",
    2: "stateless",
    3: "stateful",
    4: "stateless",
    5: "stateless",
  });

  assert.deepEqual(startTimes, {
    0: 0,
    1: 4,
    2: 104,
    3: 54,
    4: 104,
    5: 154,
  });
});

test("computeDisplayEdges rewires root tool edges into stateful chain then stateless fan-out", () => {
  const trace = {
    nodes: [
      {
        id: 0,
        name: "llm",
        type: "llm",
        time: 20,
        edge_to: [
          { id: 1, interval: 0 },
          { id: 2, interval: 0 },
          { id: 3, interval: 0 },
          { id: 4, interval: 0 },
        ],
      },
      { id: 1, name: "omega_stateful", type: "tool_use", time: 50, edge_to: [] },
      { id: 2, name: "beta_stateless", type: "tool_use", time: 50, edge_to: [] },
      {
        id: 3,
        name: "alpha_stateful",
        type: "tool_use",
        time: 50,
        edge_to: [{ id: 5, interval: 0 }],
      },
      {
        id: 4,
        name: "gamma_stateless",
        type: "tool_use",
        time: 50,
        edge_to: [{ id: 5, interval: 0 }],
      },
      { id: 5, name: "delta_join", type: "tool_use", time: 10, edge_to: [] },
    ],
  };

  const viewerMetadata = {
    toolModeById: {
      1: "stateful",
      2: "stateless",
      3: "stateful",
      4: "stateless",
      5: "stateless",
    },
    startTimeById: {
      0: 0,
      1: 4,
      2: 104,
      3: 54,
      4: 104,
      5: 154,
    },
  };

  const edges = computeDisplayEdges(trace, viewerMetadata)
    .map((edge) => `${edge.from}->${edge.to}`)
    .sort();

  assert.deepEqual(edges, [
    "0->1",
    "1->3",
    "3->2",
    "3->4",
    "3->5",
    "4->5",
  ]);
});

test("computeDisplayEdges rewires root tool exits to the next llm from displayed batch terminals", () => {
  const trace = {
    nodes: [
      {
        id: 0,
        name: "llm",
        type: "llm",
        time: 20,
        edge_to: [
          { id: 1, interval: 0 },
          { id: 2, interval: 0 },
          { id: 3, interval: 0 },
        ],
      },
      {
        id: 1,
        name: "first_stateful",
        type: "tool_use",
        time: 50,
        edge_to: [{ id: 4, interval: 0 }],
      },
      {
        id: 2,
        name: "second_stateful",
        type: "tool_use",
        time: 50,
        edge_to: [{ id: 4, interval: 0 }],
      },
      {
        id: 3,
        name: "only_stateless",
        type: "tool_use",
        time: 50,
        edge_to: [{ id: 4, interval: 0 }],
      },
      { id: 4, name: "llm", type: "llm", time: 30, edge_to: [] },
    ],
  };

  const viewerMetadata = {
    toolModeById: {
      1: "stateful",
      2: "stateful",
      3: "stateless",
    },
    startTimeById: {
      0: 0,
      1: 4,
      2: 54,
      3: 104,
      4: 154,
    },
  };

  const edges = computeDisplayEdges(trace, viewerMetadata)
    .map((edge) => `${edge.from}->${edge.to}`)
    .sort();

  assert.deepEqual(edges, [
    "0->1",
    "1->2",
    "2->3",
    "3->4",
  ]);
});

test("computeToolGraphMetrics reports tool depth and width", () => {
  const trace = {
    nodes: [
      {
        id: 0,
        name: "llm",
        type: "llm",
        time: 20,
        edge_to: [
          { id: 1, interval: 0 },
          { id: 2, interval: 0 },
          { id: 3, interval: 0 },
          { id: 4, interval: 0 },
        ],
      },
      { id: 1, name: "omega_stateful", type: "tool_use", time: 50, edge_to: [] },
      { id: 2, name: "beta_stateless", type: "tool_use", time: 50, edge_to: [] },
      {
        id: 3,
        name: "alpha_stateful",
        type: "tool_use",
        time: 50,
        edge_to: [{ id: 5, interval: 0 }],
      },
      {
        id: 4,
        name: "gamma_stateless",
        type: "tool_use",
        time: 50,
        edge_to: [{ id: 5, interval: 0 }],
      },
      { id: 5, name: "delta_join", type: "tool_use", time: 10, edge_to: [] },
    ],
  };

  const viewerMetadata = {
    toolModeById: {
      1: "stateful",
      2: "stateless",
      3: "stateful",
      4: "stateless",
      5: "stateless",
    },
    startTimeById: {
      0: 0,
      1: 4,
      2: 104,
      3: 54,
      4: 104,
      5: 154,
    },
  };

  assert.deepEqual(computeToolGraphMetrics(trace, viewerMetadata), {
    depth: 4,
    width: 2,
    levelById: {
      1: 1,
      3: 2,
      2: 3,
      4: 3,
      5: 4,
    },
  });
});
