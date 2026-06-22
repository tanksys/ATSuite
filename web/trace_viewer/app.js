import { computeDisplayEdges, getViewerMetadata, normalizeNodeType } from "./metadata.mjs";

const graphContainer = document.getElementById("graph");
const detailsContainer = document.getElementById("details");
const summaryContainer = document.getElementById("summary");
const calculatorOutput = document.getElementById("calculator-output");
const fileInput = document.getElementById("file-input");
const urlInput = document.getElementById("url-input");
const loadUrlButton = document.getElementById("load-url");
const coldStartInput = document.getElementById("cold-start-ms");
const overheadInput = document.getElementById("overhead-percent");
const recalcButton = document.getElementById("recalc");
const llmModelSelect = document.getElementById("llm-model");
const sandboxProviderSelect = document.getElementById("sandbox-provider");
const calcCostButton = document.getElementById("calc-cost");
const costOutput = document.getElementById("cost-output");

let currentTrace = null;
let currentViewerMetadata = null;
let network = null;
let graphData = null;

// LLM Pricing (USD per 1M tokens)
const LLM_PRICING = {
  "gpt5-nano": {
    name: "GPT-5 Nano",
    prefill: 0.05,   // $0.05/1M input tokens
    decode: 0.40,    // $0.40/1M output tokens
  },
  "gpt-4o-mini": {
    name: "GPT-4o Mini",
    prefill: 0.15,   // $0.15/1M input tokens
    decode: 0.60,    // $0.60/1M output tokens
  },
  "claude-4.5-sonnet": {
    name: "Claude 4.5 Sonnet",
    prefill: 3.0,   // $3/1M input tokens
    decode: 15.0,   // $15/1M output tokens
  },
  "qwen-plus": {
    name: "Qwen3-max",
    prefill: 0.36,   // ~$0.8/1M input tokens (Aliyun pricing in CNY converted)
    decode: 1.4,    // ~$2/1M output tokens
  },
};

// Sandbox/Compute Pricing (USD per second for 4GB memory config)
const SANDBOX_PRICING = {
  "aws-agentcore": {
    name: "AWS AgentCore (2vCPU/4GB)",
    perSecond: 0.0002,  // Estimated: ~$0.72/hour for 2vCPU 4GB
  },
  "aws-lambda": {
    name: "AWS Lambda (4GB)",
    perSecond: 0.0000666668,  // $0.0000166667 per GB-second * 4GB
  },
  "aliyun-fc": {
    name: "Aliyun FC (4GB)",
    perSecond: 0.00005,  // ~0.000110592 CNY/GB-second * 4GB, converted
  },
};

const NODE_STYLES = {
  logic: { shape: "box", color: "#4F81BD", icon: "⚙" },
  llm: { shape: "box", color: "#9BBB59", icon: "🧠" },
  tool: { shape: "box", color: "#C0504D", icon: "🛠" },
  sandbox: { shape: "box", color: "#8064A2", icon: "🧪" },
  unknown: { shape: "box", color: "#808080", icon: "❓" },
};

function truncateLabel(text, maxLength = 30) {
  if (!text) return "";
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}…`;
}

function stringifyValue(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch (error) {
    return String(value);
  }
}

function getEdgeLabel(edge) {
  const params = edge.params || {};
  if (typeof params.input === "string") {
    return params.input;
  }
  if (Object.keys(params).length > 0) {
    return stringifyValue(params);
  }
  return "";
}

const ROW_LAYOUT = {
  logic: -220,
  llm: 0,
  "tool-stateful": 220,
  "tool-stateless": 440,
  sandbox: 660,
  other: 660,
};

function getNodeRowKey(node, viewerMetadata) {
  const normalizedType = normalizeNodeType(node.type);
  if (normalizedType === "tool") {
    return viewerMetadata.toolModeById[node.id] === "stateful"
      ? "tool-stateful"
      : "tool-stateless";
  }
  if (normalizedType === "logic" || normalizedType === "llm" || normalizedType === "sandbox") {
    return normalizedType;
  }
  return "other";
}

function buildNodeLabel(node, normalizedType, viewerMetadata) {
  const style = NODE_STYLES[normalizedType] || NODE_STYLES.unknown;
  const toolMode =
    normalizedType === "tool" ? (viewerMetadata.toolModeById[node.id] || "stateless") : "";
  const scheduleStart = viewerMetadata.startTimeById[node.id] ?? 0;
  const toolLevel = viewerMetadata.toolGraph.levelById[node.id] ?? "";
  const typeBits = [normalizedType];
  if (toolMode) {
    typeBits.push(toolMode);
  }
  if (toolLevel !== "") {
    typeBits.push(`depth ${toolLevel}`);
  }
  return `${style.icon} ${node.name || "node"}\n────────\nID: ${node.id} | ${typeBits.join(" · ")}\nStart: ${scheduleStart.toFixed(2)} ms | Time: ${(node.time || 0).toFixed(2)} ms`;
}

function buildGraph(trace, viewerMetadata) {
  const nodes = [];
  const nodeTypeById = new Map();
  const nodeWidth = 150;
  const nodeMinGap = 60;
  const startTimes = viewerMetadata.startTimeById;
  const scale = nodeWidth / 100;
  const layoutNodes = [];

  trace.nodes.forEach((node) => {
    nodeTypeById.set(node.id, normalizeNodeType(node.type));
  });

  trace.nodes.forEach((node) => {
    const normalizedType = nodeTypeById.get(node.id) || "unknown";
    const style = NODE_STYLES[normalizedType] || NODE_STYLES.unknown;
    const start = startTimes[node.id] || 0;
    const x = start * scale;
    const rowKey = getNodeRowKey(node, viewerMetadata);
    const y = ROW_LAYOUT[rowKey] ?? ROW_LAYOUT.other;
    const toolMode = viewerMetadata.toolModeById[node.id] || "";
    const toolLevel = viewerMetadata.toolGraph.levelById[node.id] ?? null;
    layoutNodes.push({ id: node.id, x, y, rowKey });
    nodes.push({
      id: node.id,
      label: buildNodeLabel(node, normalizedType, viewerMetadata),
      shape: style.shape,
      color: style.color,
      font: { color: "#ffffff", align: "left", size: 12 },
      widthConstraint: { minimum: nodeWidth, maximum: nodeWidth },
      heightConstraint: { minimum: 82 },
      x,
      y,
      fixed: { x: true, y: true },
      type: normalizedType,
      rowKey,
      toolMode,
      toolLevel,
      scheduledStartMs: start,
      time: node.time || 0,
      output: node.output,
      rawNode: node,
    });
  });

  const adjustRow = (rowKey) => {
    const rowNodes = layoutNodes
      .filter((node) => node.rowKey === rowKey)
      .sort((a, b) => a.x - b.x);
    let cursor = null;
    rowNodes.forEach((node) => {
      if (cursor === null) {
        cursor = node.x;
      } else if (node.x < cursor + nodeWidth + nodeMinGap) {
        node.x = cursor + nodeWidth + nodeMinGap;
      }
      cursor = node.x;
      graphData?.nodes?.update?.({ id: node.id, x: node.x });
    });
  };

  const edges = computeDisplayEdges(trace, viewerMetadata);
  graphData = {
    nodes: new window.vis.DataSet(nodes),
    edges: new window.vis.DataSet(edges),
  };
  Object.keys(ROW_LAYOUT).forEach((rowKey) => {
    adjustRow(rowKey);
  });

  return graphData;
}

function renderDetails(contentHtml) {
  detailsContainer.innerHTML = contentHtml;
}

function renderNodeDetails(node) {
  const outputText = stringifyValue(node.output);
  const displayEdges = graphData?.edges?.get?.().filter((edge) => edge.from === node.id) || [];
  const edgeSummary = displayEdges
    .map((edge) => {
      const label = edge.fullLabel || getEdgeLabel(edge);
      const paramsText = stringifyValue(edge.params || {});
      return `
        <li>
          <div><strong>→ ${edge.id}</strong></div>
          <div><strong>Kind:</strong> ${edge.displayKind || "raw"}</div>
          <div><strong>Synthetic:</strong> ${edge.synthetic ? "yes" : "no"}</div>
          <div><strong>Interval (ms):</strong> ${edge.interval || 0}</div>
          <div><strong>Input:</strong></div>
          <pre>${label || "No input"}</pre>
          <div><strong>Params:</strong></div>
          <pre>${paramsText || "No params"}</pre>
        </li>
      `;
    })
    .join("");

  renderDetails(`
    <div class="detail-group">
      <h3>Node</h3>
      <p><strong>ID:</strong> ${node.id}</p>
      <p><strong>Name:</strong> ${node.rawNode.name || ""}</p>
      <p><strong>Type:</strong> ${node.type}</p>
      <p><strong>Mode:</strong> ${node.toolMode || "n/a"}</p>
      <p><strong>Scheduled start (ms):</strong> ${Number(node.scheduledStartMs || 0).toFixed(2)}</p>
      <p><strong>Tool depth level:</strong> ${node.toolLevel ?? "n/a"}</p>
      <p><strong>Time (ms):</strong> ${node.time}</p>
      <div class="detail-output">
        <strong>Output:</strong>
        <pre>${outputText || "No output"}</pre>
      </div>
    </div>
    <div class="detail-group">
      <h3>Edges</h3>
      <ul>${edgeSummary || "<li>No outgoing edges</li>"}</ul>
    </div>
  `);
}

function renderEdgeDetails(edge) {
  const paramsText = stringifyValue(edge.params);
  renderDetails(`
    <div class="detail-group">
      <h3>Edge</h3>
      <p><strong>Kind:</strong> ${edge.displayKind || "raw"}</p>
      <p><strong>Synthetic:</strong> ${edge.synthetic ? "yes" : "no"}</p>
      <p><strong>From:</strong> ${edge.from}</p>
      <p><strong>To:</strong> ${edge.to}</p>
      <p><strong>Interval (ms):</strong> ${edge.interval}</p>
      <div class="detail-output">
        <strong>Full label:</strong>
        <pre>${edge.fullLabel || "No label"}</pre>
      </div>
      <div class="detail-output">
        <strong>Params:</strong>
        <pre>${paramsText || "No params"}</pre>
      </div>
    </div>
  `);
}

function computeSummary(trace, viewerMetadata) {
  const totals = {};
  let totalTime = 0;

  trace.nodes.forEach((node) => {
    const type = normalizeNodeType(node.type);
    const time = Number(node.time || 0);
    totalTime += time;
    if (!totals[type]) {
      totals[type] = { count: 0, time: 0 };
    }
    totals[type].count += 1;
    totals[type].time += time;
  });

  ["llm", "tool", "sandbox"].forEach((type) => {
    if (!totals[type]) {
      totals[type] = { count: 0, time: 0 };
    }
  });

  return {
    totals,
    totalTime,
    toolGraph: viewerMetadata.toolGraph,
    statefulToolCount: viewerMetadata.statefulToolNames.length,
  };
}

function renderSummary(summary) {
  const totalTime = summary.totalTime || 0;
  const rows = Object.entries(summary.totals)
    .map(
      ([type, info]) =>
        `<tr>
          <td>${type}</td>
          <td>${info.count}</td>
          <td>${info.time.toFixed(2)}</td>
          <td>${totalTime === 0 ? "0.00" : ((info.time / totalTime) * 100).toFixed(2)}%</td>
        </tr>`
    )
    .join("");

  summaryContainer.innerHTML = `
    <table>
      <thead>
        <tr><th>Type</th><th>Count</th><th>Total time (ms)</th><th>Percent</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    <p><strong>Total time:</strong> ${summary.totalTime.toFixed(2)} ms</p>
    <p><strong>Tool graph depth:</strong> ${summary.toolGraph.depth}</p>
    <p><strong>Tool graph width:</strong> ${summary.toolGraph.width}</p>
    <p><strong>Resolved stateful tools:</strong> ${summary.statefulToolCount}</p>
  `;
}

function renderCalculator(summary) {
  if (!summary) {
    calculatorOutput.innerHTML = "<p>Load a trace to run the calculator.</p>";
    return;
  }
  const coldStartMs = Number(coldStartInput.value || 0);
  const overheadPercent = Number(overheadInput.value || 0);
  const sandboxInfo = summary.totals.sandbox || { count: 0 };
  const toolInfo = summary.totals.tool || { count: 0 };
  const llmInfo = summary.totals.llm || { time: 0 };
  const nonLlmTime = summary.totalTime - llmInfo.time;
  const totalTime = summary.totalTime;
  const multiplier = 1 + overheadPercent / 100;
  const adjustedNonLlm = nonLlmTime * multiplier;
  const adjustedLlm = llmInfo.time * multiplier;
  let utilization = 0;
  if (coldStartMs > 0) {
    const coldStartTotal =
      coldStartMs * (toolInfo.count + sandboxInfo.count);
    utilization =
      adjustedNonLlm === 0
        ? 0
        : (adjustedNonLlm + coldStartTotal) / adjustedNonLlm;
  } else {
    utilization =
      adjustedNonLlm + adjustedLlm === 0
        ? 0
        : adjustedNonLlm / (adjustedNonLlm + adjustedLlm);
  }

  calculatorOutput.innerHTML = `
    <p><strong>Sandbox count:</strong> ${sandboxInfo.count}</p>
    <p><strong>Tool count:</strong> ${toolInfo.count}</p>
    <p><strong>Non-LLM time:</strong> ${adjustedNonLlm.toFixed(2)} ms</p>
    <p><strong>LLM time:</strong> ${adjustedLlm.toFixed(2)} ms</p>
    <p><strong>Utilization:</strong> ${(utilization * 100).toFixed(2)}%</p>
  `;
}

function updateView(trace) {
  currentTrace = trace;
  currentViewerMetadata = getViewerMetadata(trace);
  graphData = buildGraph(trace, currentViewerMetadata);

  if (network) {
    network.setData(graphData);
  } else {
    network = new window.vis.Network(
      graphContainer,
      graphData,
      {
        layout: { improvedLayout: false },
        edges: {
          arrows: { to: { enabled: true, scaleFactor: 0.6 } },
          font: { align: "top" },
          smooth: false,
        },
        interaction: { hover: true },
        physics: { enabled: false },
      }
    );

    network.on("click", (params) => {
      if (params.nodes.length > 0) {
        const node = graphData.nodes.get(params.nodes[0]);
        renderNodeDetails(node);
      } else if (params.edges.length > 0) {
        const edge = graphData.edges.get(params.edges[0]);
        renderEdgeDetails(edge);
      }
    });
  }

  const summary = computeSummary(trace, currentViewerMetadata);
  renderSummary(summary);
  renderCalculator(summary);
  renderCostEstimation(trace);
}

function parseTrace(rawText) {
  const data = JSON.parse(rawText);
  if (!data.nodes || !Array.isArray(data.nodes)) {
    throw new Error("Trace JSON missing nodes array.");
  }
  return data;
}

fileInput.addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const trace = parseTrace(reader.result);
      updateView(trace);
    } catch (error) {
      renderDetails(`<p class="error">${error.message}</p>`);
    }
  };
  reader.readAsText(file);
});

loadUrlButton.addEventListener("click", () => {
  const url = urlInput.value.trim();
  if (!url) return;
  fetch(url)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`Failed to load trace: ${response.status}`);
      }
      return response.text();
    })
    .then((text) => {
      const trace = parseTrace(text);
      updateView(trace);
    })
    .catch((error) => {
      renderDetails(`<p class="error">${error.message}</p>`);
    });
});

recalcButton.addEventListener("click", () => {
  if (!currentTrace) return;
  const summary = computeSummary(currentTrace, currentViewerMetadata || getViewerMetadata(currentTrace));
  renderCalculator(summary);
});

// Estimate tokens from LLM node data
function estimateLLMTokens(node) {
  // Try to get token counts from node data
  let inputTokens = 0;
  let outputTokens = 0;

  // Check common token count fields
  if (node.input_tokens !== undefined) {
    inputTokens = Number(node.input_tokens);
  } else if (node.prompt_tokens !== undefined) {
    inputTokens = Number(node.prompt_tokens);
  } else if (node.usage?.prompt_tokens !== undefined) {
    inputTokens = Number(node.usage.prompt_tokens);
  }

  if (node.output_tokens !== undefined) {
    outputTokens = Number(node.output_tokens);
  } else if (node.completion_tokens !== undefined) {
    outputTokens = Number(node.completion_tokens);
  } else if (node.usage?.completion_tokens !== undefined) {
    outputTokens = Number(node.usage.completion_tokens);
  }

  // If no token data, estimate from time (rough heuristic)
  // Assume ~50 tokens/second for output, input is typically 10x output
  if (inputTokens === 0 && outputTokens === 0 && node.time > 0) {
    const timeSeconds = node.time / 1000;
    outputTokens = Math.round(timeSeconds * 50);
    inputTokens = Math.round(outputTokens * 10);
  }

  return { inputTokens, outputTokens };
}

// Calculate LLM costs
function calculateLLMCost(trace, modelKey) {
  const pricing = LLM_PRICING[modelKey];
  if (!pricing) {
    console.error(`Unknown LLM model: ${modelKey}`);
    return {
      model: "Unknown",
      nodeCount: 0,
      inputTokens: 0,
      outputTokens: 0,
      prefillCost: 0,
      decodeCost: 0,
      totalCost: 0,
    };
  }
  
  let totalInputTokens = 0;
  let totalOutputTokens = 0;
  let nodeCount = 0;

  trace.nodes.forEach((node) => {
    if (node.type === "llm") {
      const { inputTokens, outputTokens } = estimateLLMTokens(node);
      totalInputTokens += inputTokens;
      totalOutputTokens += outputTokens;
      nodeCount++;
    }
  });

  const prefillCost = (totalInputTokens / 1_000_000) * pricing.prefill;
  const decodeCost = (totalOutputTokens / 1_000_000) * pricing.decode;

  return {
    model: pricing.name,
    nodeCount,
    inputTokens: totalInputTokens,
    outputTokens: totalOutputTokens,
    prefillCost,
    decodeCost,
    totalCost: prefillCost + decodeCost,
  };
}

// Calculate Sandbox costs (using end-to-end time)
// End-to-end time = total trace time, because sandbox resources cannot be released while LLM is thinking
function calculateSandboxCost(trace, providerKey) {
  const pricing = SANDBOX_PRICING[providerKey];
  if (!pricing) {
    console.error(`Unknown sandbox provider: ${providerKey}`);
    return {
      provider: "Unknown",
      nodeCount: 0,
      executionTimeMs: 0,
      endToEndTimeMs: 0,
      totalCost: 0,
    };
  }
  
  let executionTimeMs = 0;
  let nodeCount = 0;

  // Count sandbox nodes and their execution time
  trace.nodes.forEach((node) => {
    if (node.type === "sandbox") {
      executionTimeMs += Number(node.time || 0);
      nodeCount++;
    }
  });

  // If no sandbox nodes, no cost
  if (nodeCount === 0) {
    return {
      provider: pricing.name,
      nodeCount: 0,
      executionTimeMs: 0,
      endToEndTimeMs: 0,
      totalCost: 0,
    };
  }

  // End-to-end time is the TOTAL trace time (including LLM time)
  // because sandbox resources remain allocated while LLM is thinking
  let totalTraceTimeMs = 0;
  trace.nodes.forEach((node) => {
    totalTraceTimeMs += Number(node.time || 0);
  });

  // Apply cold start and overhead
  const coldStartMs = Number(coldStartInput.value || 0);
  const overheadPercent = Number(overheadInput.value || 0);
  const endToEndTimeMs = totalTraceTimeMs * (1 + overheadPercent / 100) + coldStartMs;

  const totalTimeSeconds = endToEndTimeMs / 1000;
  const totalCost = totalTimeSeconds * pricing.perSecond;

  return {
    provider: pricing.name,
    nodeCount,
    executionTimeMs,
    endToEndTimeMs,
    totalCost,
  };
}

// Render cost estimation
function renderCostEstimation(trace) {
  if (!trace) {
    if (costOutput) {
      costOutput.innerHTML = "<p>Load a trace to estimate costs.</p>";
    }
    return;
  }

  if (!costOutput) {
    return;
  }

  const llmModel = (llmModelSelect?.value) || "gpt5-nano";
  const sandboxProvider = (sandboxProviderSelect?.value) || "aws-agentcore";

  const llmCost = calculateLLMCost(trace, llmModel);
  const sandboxCost = calculateSandboxCost(trace, sandboxProvider);
  const totalCost = llmCost.totalCost + sandboxCost.totalCost;

  const llmPricing = LLM_PRICING[llmModel] || LLM_PRICING["gpt5-nano"];
  const sandboxPricing = SANDBOX_PRICING[sandboxProvider] || SANDBOX_PRICING["aws-agentcore"];

  costOutput.innerHTML = `
    <div class="cost-card">
      <h4>
        <span class="cost-icon">🧠</span> LLM Cost (${llmCost.model})
        <span class="tooltip-trigger" data-tooltip="llm-tooltip">?</span>
        <span class="tooltip" id="llm-tooltip">Pricing for ${llmPricing.name}:
• Prefill (Input): $${llmPricing.prefill}/1M tokens
• Decode (Output): $${llmPricing.decode}/1M tokens</span>
      </h4>
      <table>
        <tr><td>LLM Calls</td><td>${llmCost.nodeCount}</td></tr>
        <tr><td>Input Tokens (Prefill)</td><td>${llmCost.inputTokens.toLocaleString()}</td></tr>
        <tr><td>Output Tokens (Decode)</td><td>${llmCost.outputTokens.toLocaleString()}</td></tr>
        <tr><td>Prefill Cost</td><td>$${llmCost.prefillCost.toFixed(6)}</td></tr>
        <tr><td>Decode Cost</td><td>$${llmCost.decodeCost.toFixed(6)}</td></tr>
        <tr><td><strong>LLM Total</strong></td><td><strong>$${llmCost.totalCost.toFixed(6)}</strong></td></tr>
      </table>
    </div>

    <div class="cost-card">
      <h4>
        <span class="cost-icon">🧪</span> Sandbox Cost (${sandboxCost.provider})
        <span class="tooltip-trigger" data-tooltip="sandbox-tooltip">?</span>
        <span class="tooltip" id="sandbox-tooltip">Pricing for ${sandboxPricing.name}:
• $${sandboxPricing.perSecond.toFixed(7)}/second
• $${(sandboxPricing.perSecond * 3600).toFixed(4)}/hour</span>
      </h4>
      <table>
        <tr><td>Sandbox Calls</td><td>${sandboxCost.nodeCount}</td></tr>
        <tr><td>Sandbox Execution</td><td>${sandboxCost.executionTimeMs.toFixed(2)} ms</td></tr>
        <tr><td>End-to-End Time*</td><td>${sandboxCost.endToEndTimeMs.toFixed(2)} ms</td></tr>
        <tr><td><strong>Sandbox Total</strong></td><td><strong>$${sandboxCost.totalCost.toFixed(6)}</strong></td></tr>
      </table>
      <p style="font-size: 11px; color: #6b7280; margin: 8px 0 0;">
        *Total trace time (incl. LLM) + cold start + overhead
      </p>
    </div>

    <div class="cost-card cost-total">
      <h4><span class="cost-icon">💰</span> Total Estimated Cost</h4>
      <div class="total-value">$${totalCost.toFixed(6)}</div>
      <p style="font-size: 12px; color: #6b7280; margin-top: 8px;">
        Per trace execution
      </p>
    </div>
  `;

  // Add click handlers for tooltip triggers
  costOutput.querySelectorAll(".tooltip-trigger").forEach((trigger) => {
    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      const tooltipId = trigger.getAttribute("data-tooltip");
      const tooltip = document.getElementById(tooltipId);
      
      // Close all other tooltips
      costOutput.querySelectorAll(".tooltip").forEach((t) => {
        if (t.id !== tooltipId) t.classList.remove("show");
      });
      
      // Toggle this tooltip
      tooltip.classList.toggle("show");
    });
  });
}

if (calcCostButton) {
  calcCostButton.addEventListener("click", () => {
    renderCostEstimation(currentTrace);
  });
}

if (llmModelSelect) {
  llmModelSelect.addEventListener("change", () => {
    if (currentTrace) renderCostEstimation(currentTrace);
  });
}

if (sandboxProviderSelect) {
  sandboxProviderSelect.addEventListener("change", () => {
    if (currentTrace) renderCostEstimation(currentTrace);
  });
}

// Close tooltips when clicking outside
document.addEventListener("click", () => {
  const tooltips = document.querySelectorAll(".cost-card .tooltip");
  tooltips.forEach((t) => t.classList.remove("show"));
});
