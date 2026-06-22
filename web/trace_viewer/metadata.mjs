const TOOL_NODE_TYPES = new Set(["tool", "tool_use"]);
const LLM_DISPLAY_SCALE_DIVISOR = 5;

export function normalizeNodeType(nodeType) {
  const normalized = String(nodeType || "").trim().toLowerCase();
  if (TOOL_NODE_TYPES.has(normalized)) {
    return "tool";
  }
  return normalized || "unknown";
}

export function isToolNode(node) {
  return normalizeNodeType(node?.type) === "tool";
}

function displayDurationMs(node) {
  const duration = Number(node?.time || 0);
  if (normalizeNodeType(node?.type) === "llm") {
    return duration / LLM_DISPLAY_SCALE_DIVISOR;
  }
  return duration;
}

function normalizeToolModeById(rawModes = {}) {
  const normalized = {};
  Object.entries(rawModes || {}).forEach(([nodeId, mode]) => {
    normalized[nodeId] = mode === "stateful" ? "stateful" : "stateless";
  });
  return normalized;
}

function normalizeStartTimeById(rawStartTimes = {}) {
  const normalized = {};
  Object.entries(rawStartTimes || {}).forEach(([nodeId, value]) => {
    normalized[nodeId] = Number(value || 0);
  });
  return normalized;
}

function buildNodeById(trace) {
  const nodes = Array.isArray(trace?.nodes) ? trace.nodes : [];
  const nodeById = new Map();
  nodes.forEach((node) => {
    nodeById.set(node.id, node);
  });
  return nodeById;
}

function buildIncomingById(trace) {
  const incomingById = new Map();
  const nodes = Array.isArray(trace?.nodes) ? trace.nodes : [];
  nodes.forEach((node) => {
    if (!incomingById.has(node.id)) {
      incomingById.set(node.id, []);
    }
  });
  nodes.forEach((node) => {
    (node.edge_to || []).forEach((edge) => {
      if (!incomingById.has(edge.id)) {
        incomingById.set(edge.id, []);
      }
      incomingById.get(edge.id).push({
        from: node.id,
        edge,
      });
    });
  });
  return incomingById;
}

function sortByScheduleThenId(nodeIds, startTimeById) {
  return [...nodeIds].sort((left, right) => {
    const leftStart = Number(startTimeById[left] || 0);
    const rightStart = Number(startTimeById[right] || 0);
    if (leftStart !== rightStart) {
      return leftStart - rightStart;
    }
    return left - right;
  });
}

function chooseDisplayAnchorId(incomingEdges, nodeById, startTimeById) {
  const nonToolIncoming = incomingEdges.filter(({ from }) => !isToolNode(nodeById.get(from)));
  if (nonToolIncoming.length === 0) {
    return null;
  }
  nonToolIncoming.sort((left, right) => {
    const leftStart = Number(startTimeById[left.from] || 0);
    const rightStart = Number(startTimeById[right.from] || 0);
    if (leftStart !== rightStart) {
      return rightStart - leftStart;
    }
    return right.from - left.from;
  });
  return nonToolIncoming[0].from;
}

function buildSyntheticRootToolEdges(trace, viewerMetadata) {
  const nodeById = buildNodeById(trace);
  const incomingById = buildIncomingById(trace);
  const toolModeById = viewerMetadata?.toolModeById || {};
  const startTimeById = viewerMetadata?.startTimeById || {};
  const rootToolIds = [];

  nodeById.forEach((node, nodeId) => {
    if (!isToolNode(node)) {
      return;
    }
    const incomingEdges = incomingById.get(nodeId) || [];
    const hasToolPredecessor = incomingEdges.some(({ from }) => isToolNode(nodeById.get(from)));
    if (!hasToolPredecessor) {
      rootToolIds.push(nodeId);
    }
  });

  const groupedRoots = new Map();
  rootToolIds.forEach((nodeId) => {
    const incomingEdges = incomingById.get(nodeId) || [];
    const anchorId = chooseDisplayAnchorId(incomingEdges, nodeById, startTimeById);
    const groupKey = anchorId === null ? `none:${nodeId}` : String(anchorId);
    if (!groupedRoots.has(groupKey)) {
      groupedRoots.set(groupKey, {
        anchorId,
        stateful: [],
        stateless: [],
        rootToolIds: new Set(),
        downstreamNonToolTargetIds: new Set(),
      });
    }
    const group = groupedRoots.get(groupKey);
    group.rootToolIds.add(nodeId);
    const node = nodeById.get(nodeId);
    (node?.edge_to || []).forEach((edge) => {
      const targetNode = nodeById.get(edge.id);
      if (targetNode && !isToolNode(targetNode)) {
        group.downstreamNonToolTargetIds.add(edge.id);
      }
    });
    if ((toolModeById[nodeId] || "stateless") === "stateful") {
      group.stateful.push(nodeId);
    } else {
      group.stateless.push(nodeId);
    }
  });

  const syntheticEdges = [];
  const suppressedRawEdgeIds = new Set();
  groupedRoots.forEach((group) => {
    const statefulIds = sortByScheduleThenId(group.stateful, startTimeById);
    const statelessIds = sortByScheduleThenId(group.stateless, startTimeById);
    const downstreamNonToolTargetIds = [...group.downstreamNonToolTargetIds].sort((a, b) => a - b);
    const terminalToolIds =
      statelessIds.length > 0
        ? statelessIds
        : statefulIds.length > 0
          ? [statefulIds[statefulIds.length - 1]]
          : [];
    group.rootToolIds.forEach((rootToolId) => {
      downstreamNonToolTargetIds.forEach((targetId) => {
        suppressedRawEdgeIds.add(`${rootToolId}->${targetId}`);
      });
    });

    if (statefulIds.length > 0) {
      if (group.anchorId !== null) {
        syntheticEdges.push({
          id: `display:${group.anchorId}->${statefulIds[0]}`,
          from: group.anchorId,
          to: statefulIds[0],
          synthetic: true,
          displayKind: "stateful-entry",
          label: "",
          fullLabel: "Serialized stateful tool chain",
          params: {},
          interval: 0,
        });
      }
      for (let index = 1; index < statefulIds.length; index += 1) {
        syntheticEdges.push({
          id: `display:${statefulIds[index - 1]}->${statefulIds[index]}`,
          from: statefulIds[index - 1],
          to: statefulIds[index],
          synthetic: true,
          displayKind: "stateful-chain",
          label: "",
          fullLabel: "Serialized stateful tool chain",
          params: {},
          interval: 0,
        });
      }
      const fanoutSource = statefulIds[statefulIds.length - 1];
      statelessIds.forEach((nodeId) => {
        syntheticEdges.push({
          id: `display:${fanoutSource}->${nodeId}`,
          from: fanoutSource,
          to: nodeId,
          synthetic: true,
          displayKind: "stateless-fanout",
          label: "",
          fullLabel: "Stateless fan-out after stateful tool chain",
          params: {},
          interval: 0,
        });
      });
    } else if (group.anchorId !== null) {
      statelessIds.forEach((nodeId) => {
        syntheticEdges.push({
          id: `display:${group.anchorId}->${nodeId}`,
          from: group.anchorId,
          to: nodeId,
          synthetic: true,
          displayKind: "stateless-entry",
          label: "",
          fullLabel: "Direct stateless tool fan-out",
          params: {},
          interval: 0,
        });
      });
    }

    terminalToolIds.forEach((toolId) => {
      downstreamNonToolTargetIds.forEach((targetId) => {
        syntheticEdges.push({
          id: `display:${toolId}->${targetId}`,
          from: toolId,
          to: targetId,
          synthetic: true,
          displayKind: "batch-exit",
          label: "",
          fullLabel: "Continue after displayed tool batch",
          params: {},
          interval: 0,
        });
      });
    });
  });

  return {
    rootToolIds: new Set(rootToolIds),
    syntheticEdges,
    suppressedRawEdgeIds,
  };
}

export function computeDisplayEdges(trace, viewerMetadata = {}) {
  const nodes = Array.isArray(trace?.nodes) ? trace.nodes : [];
  const nodeById = buildNodeById(trace);
  const { rootToolIds, syntheticEdges, suppressedRawEdgeIds } = buildSyntheticRootToolEdges(trace, viewerMetadata);
  const edges = [];

  nodes.forEach((node) => {
    const sourceType = normalizeNodeType(node.type);
    (node.edge_to || []).forEach((edge) => {
      if (suppressedRawEdgeIds.has(`${node.id}->${edge.id}`)) {
        return;
      }
      const targetNode = nodeById.get(edge.id);
      if (targetNode && isToolNode(targetNode) && rootToolIds.has(edge.id)) {
        return;
      }
      const targetType = normalizeNodeType(targetNode?.type);
      const fullLabel = getEdgeLabelForDisplay(edge);
      edges.push({
        id: `${node.id}->${edge.id}`,
        from: node.id,
        to: edge.id,
        label: targetType === "llm" ? "" : truncateDisplayLabel(fullLabel),
        fullLabel,
        params: edge.params || {},
        interval: Number(edge.interval || 0),
        length: sourceType === "llm" && targetType === "sandbox" ? 420 : 260,
        synthetic: false,
        displayKind: "raw",
      });
    });
  });

  syntheticEdges.forEach((edge) => {
    const sourceType = normalizeNodeType(nodeById.get(edge.from)?.type);
    const targetType = normalizeNodeType(nodeById.get(edge.to)?.type);
    edges.push({
      ...edge,
      length: sourceType === "llm" && targetType === "sandbox" ? 420 : 260,
    });
  });

  return edges;
}

function truncateDisplayLabel(text, maxLength = 30) {
  if (!text) return "";
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}…`;
}

function getEdgeLabelForDisplay(edge) {
  const params = edge.params || {};
  if (typeof params.input === "string") {
    return params.input;
  }
  if (Object.keys(params).length > 0) {
    try {
      return JSON.stringify(params, null, 2);
    } catch {
      return String(params);
    }
  }
  return "";
}

export function computeToolGraphMetrics(trace, viewerMetadata = {}) {
  const nodes = Array.isArray(trace?.nodes) ? trace.nodes : [];
  const nodeTypes = new Map();
  const adjacency = new Map();
  const indegree = new Map();
  const displayEdges = computeDisplayEdges(trace, viewerMetadata);

  nodes.forEach((node) => {
    nodeTypes.set(node.id, node.type || "");
    adjacency.set(node.id, []);
    indegree.set(node.id, 0);
  });

  displayEdges.forEach((edge) => {
    if (!adjacency.has(edge.from) || !adjacency.has(edge.to)) {
      return;
    }
    adjacency.get(edge.from).push(edge.to);
    indegree.set(edge.to, (indegree.get(edge.to) || 0) + 1);
  });

  const queue = [...indegree.entries()]
    .filter(([, degree]) => degree === 0)
    .map(([nodeId]) => nodeId)
    .sort((a, b) => a - b);
  const toolLevels = new Map();

  queue.forEach((nodeId) => {
    toolLevels.set(nodeId, normalizeNodeType(nodeTypes.get(nodeId)) === "tool" ? 1 : 0);
  });

  while (queue.length > 0) {
    const nodeId = queue.shift();
    const currentLevel = toolLevels.get(nodeId) || 0;
    (adjacency.get(nodeId) || []).forEach((neighborId) => {
      if (!indegree.has(neighborId)) {
        return;
      }
      const nextLevel =
        currentLevel + (normalizeNodeType(nodeTypes.get(neighborId)) === "tool" ? 1 : 0);
      toolLevels.set(neighborId, Math.max(toolLevels.get(neighborId) || 0, nextLevel));
      indegree.set(neighborId, (indegree.get(neighborId) || 0) - 1);
      if (indegree.get(neighborId) === 0) {
        queue.push(neighborId);
      }
    });
  }

  const levelById = {};
  const widthByLevel = new Map();
  toolLevels.forEach((level, nodeId) => {
    if (normalizeNodeType(nodeTypes.get(nodeId)) !== "tool") {
      return;
    }
    levelById[nodeId] = level;
    widthByLevel.set(level, (widthByLevel.get(level) || 0) + 1);
  });

  return {
    depth: Math.max(0, ...widthByLevel.keys()),
    width: Math.max(0, ...widthByLevel.values()),
    levelById,
  };
}

export function computeScheduledStartTimes(trace, toolModeById = {}) {
  const nodes = Array.isArray(trace?.nodes) ? trace.nodes : [];
  const nodeById = new Map();
  const indegree = new Map();
  const readyNodes = new Set();
  const pending = [];
  const submitted = new Set();
  const startTimes = {};
  const normalizedModes = normalizeToolModeById(toolModeById);
  let currentTime = 0;
  let activeStatefulNode = null;
  let submissionOrder = 0;

  nodes.forEach((node) => {
    nodeById.set(node.id, node);
    indegree.set(node.id, 0);
  });

  nodes.forEach((node) => {
    (node.edge_to || []).forEach((edge) => {
      if (indegree.has(edge.id)) {
        indegree.set(edge.id, (indegree.get(edge.id) || 0) + 1);
      }
    });
  });

  indegree.forEach((degree, nodeId) => {
    if (degree === 0) {
      readyNodes.add(nodeId);
    }
  });

  const isStatefulToolNode = (nodeId) => {
    const node = nodeById.get(nodeId);
    return isToolNode(node) && normalizedModes[nodeId] === "stateful";
  };

  const submitNode = (nodeId) => {
    if (submitted.has(nodeId) || !nodeById.has(nodeId)) {
      return;
    }
    submitted.add(nodeId);
    startTimes[nodeId] = currentTime;
    pending.push({
      endTime: currentTime + displayDurationMs(nodeById.get(nodeId)),
      order: submissionOrder,
      nodeId,
    });
    submissionOrder += 1;
  };

  const popNextPending = () => {
    pending.sort((left, right) => {
      if (left.endTime !== right.endTime) {
        return left.endTime - right.endTime;
      }
      return left.order - right.order;
    });
    return pending.shift();
  };

  const scheduleReadyNodes = () => {
    const nonToolReady = [...readyNodes]
      .filter((nodeId) => !isToolNode(nodeById.get(nodeId)))
      .sort((a, b) => a - b);
    nonToolReady.forEach((nodeId) => {
      readyNodes.delete(nodeId);
      submitNode(nodeId);
    });

    if (activeStatefulNode === null) {
      const statefulReady = [...readyNodes]
        .filter((nodeId) => isStatefulToolNode(nodeId))
        .sort((a, b) => a - b);
      if (statefulReady.length > 0) {
        const chosen = statefulReady[0];
        readyNodes.delete(chosen);
        activeStatefulNode = chosen;
        submitNode(chosen);
        return;
      }
    }

    if (activeStatefulNode === null) {
      [...readyNodes]
        .sort((a, b) => a - b)
        .forEach((nodeId) => {
          readyNodes.delete(nodeId);
          submitNode(nodeId);
        });
    }
  };

  scheduleReadyNodes();

  while (pending.length > 0 || readyNodes.size > 0) {
    if (pending.length === 0) {
      scheduleReadyNodes();
      if (pending.length === 0) {
        break;
      }
    }

    const next = popNextPending();
    currentTime = next.endTime;
    const completed = [next];

    while (pending.length > 0) {
      pending.sort((left, right) => {
        if (left.endTime !== right.endTime) {
          return left.endTime - right.endTime;
        }
        return left.order - right.order;
      });
      if (pending[0].endTime !== currentTime) {
        break;
      }
      completed.push(pending.shift());
    }

    completed.forEach(({ nodeId }) => {
      if (nodeId === activeStatefulNode) {
        activeStatefulNode = null;
      }
      const node = nodeById.get(nodeId);
      (node?.edge_to || []).forEach((edge) => {
        if (!indegree.has(edge.id)) {
          return;
        }
        indegree.set(edge.id, (indegree.get(edge.id) || 0) - 1);
        if (indegree.get(edge.id) === 0) {
          readyNodes.add(edge.id);
        }
      });
    });

    scheduleReadyNodes();
  }

  return startTimes;
}

export function getViewerMetadata(trace) {
  const viewerMetadata = trace?.viewer_metadata || {};
  const toolModeById = normalizeToolModeById(viewerMetadata.tool_mode_by_id || {});
  const startTimeById =
    viewerMetadata.start_time_ms_by_id
      ? normalizeStartTimeById(viewerMetadata.start_time_ms_by_id)
      : computeScheduledStartTimes(trace, toolModeById);
  const normalizedViewerMetadata = {
    toolModeById,
    startTimeById,
  };
  const toolGraph = computeToolGraphMetrics(trace, normalizedViewerMetadata);

  return {
    startTimeById,
    toolModeById,
    toolGraph,
    statefulToolNames: Array.isArray(viewerMetadata.stateful_tool_names)
      ? viewerMetadata.stateful_tool_names
      : [],
  };
}
