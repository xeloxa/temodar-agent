import fs from 'node:fs/promises';
import process from 'node:process';

import { z } from 'zod';
import {
  Agent,
  AgentPool,
  OpenMultiAgent,
  ToolExecutor,
  ToolRegistry,
} from '@jackchen_me/open-multi-agent';
import type {
  AgentConfig,
  AgentRunResult,
  OrchestratorEvent,
  Task,
  TeamRunResult,
  ToolDefinition,
  ToolResult,
  TokenUsage,
  TraceEvent,
} from '@jackchen_me/open-multi-agent';

import type {
  BridgeAgentResult,
  BridgeRunResult,
  BridgeTaskResult,
  RunnerAgentInput,
  RunnerEvent,
  RunnerInput,
  ToolEventHandlers,
} from './types.js';
import { runnerInputSchema } from './types.js';
import { buildTools } from './tools.js';

const ZERO_USAGE: TokenUsage = { input_tokens: 0, output_tokens: 0 };
const DEFAULT_AGENT_NAME = 'source_agent';
const DEFAULT_TEAM_NAME = 'open-multi-agent-team';
const DEFAULT_SYNTHESIZER_NAME = 'synthesizer';

type InputStream = AsyncIterable<string | Buffer>;

export function parseRunnerInput(rawInput: string): RunnerInput {
  const parsed = JSON.parse(rawInput) as unknown;
  return runnerInputSchema.parse(parsed);
}

export function makeJsonOutputWriter(stream: { write: (chunk: string) => unknown }) {
  return (event: RunnerEvent): void => {
    stream.write(`${JSON.stringify(event)}\n`);
  };
}

function envKeyForProvider(provider: RunnerInput['provider']): { key?: string; baseUrl?: string } {
  switch (provider) {
    case 'openai':
      return { key: 'OPENAI_API_KEY', baseUrl: 'OPENAI_BASE_URL' };
    case 'anthropic':
      return { key: 'ANTHROPIC_API_KEY', baseUrl: 'ANTHROPIC_BASE_URL' };
    case 'copilot':
      return { key: 'GITHUB_TOKEN' };
    case 'gemini':
      return { key: 'GEMINI_API_KEY' };
    case 'grok':
      return { key: 'XAI_API_KEY' };
    default:
      return {};
  }
}

export function applyProviderEnvironment(payload: RunnerInput): void {
  const envKeys = envKeyForProvider(payload.provider);
  const resolvedApiKey = payload.apiKey || process.env.TEMODAR_AI_API_KEY || '';
  if (envKeys.key && resolvedApiKey) {
    process.env[envKeys.key] = resolvedApiKey;
  }
  if (envKeys.baseUrl && payload.baseUrl) {
    process.env[envKeys.baseUrl] = payload.baseUrl;
  }
}

function wrapToolWithEvents(
  tool: { name: string; execute: ToolDefinition['execute'] } & ToolDefinition,
  handlers: ToolEventHandlers,
  approvalGate?: (toolName: string, input: Record<string, unknown>) => Promise<void>,
): ToolDefinition {
  return {
    ...tool,
    execute: async (input, context) => {
      const normalizedInput = input && typeof input === 'object' && !Array.isArray(input)
        ? input as Record<string, unknown>
        : {};
      if (approvalGate) {
        await approvalGate(tool.name, normalizedInput);
      }
      handlers.onToolCall?.(tool.name, normalizedInput);
      const result = await tool.execute(input, context);
      handlers.onToolResult?.(tool.name, result as ToolResult);
      return result;
    },
  };
}

function emitOrchestratorEvent(
  handlers: ToolEventHandlers,
  event: Exclude<RunnerEvent, { type: 'run_started' | 'run_completed' | 'run_failed' | 'tool_call' | 'tool_result' }>,
): void {
  handlers.onEvent?.(event);
}

function createRegistry(
  workspaceRoot: string,
  handlers: ToolEventHandlers,
  approvalGate?: (toolName: string, input: Record<string, unknown>) => Promise<void>,
): ToolRegistry {
  const registry = new ToolRegistry();
  for (const tool of buildTools(workspaceRoot)) {
    registry.register(wrapToolWithEvents(tool, handlers, approvalGate));
  }
  return registry;
}

function createAgentInstance(
  config: AgentConfig,
  workspaceRoot: string,
  handlers: ToolEventHandlers,
  approvalGate?: (toolName: string, input: Record<string, unknown>) => Promise<void>,
): Agent {
  const registry = createRegistry(workspaceRoot, handlers, approvalGate);
  const executor = new ToolExecutor(registry);
  return new Agent(config, registry, executor);
}

function jsonSchemaToZod(schema: Record<string, unknown>): z.ZodTypeAny {
  const schemaType = String(schema.type || 'object');
  if (schema.enum && Array.isArray(schema.enum)) {
    const values = schema.enum.filter((v): v is string => typeof v === 'string');
    if (values.length > 0) {
      return z.enum(values as [string, ...string[]]);
    }
  }
  if (schemaType === 'string') return z.string();
  if (schemaType === 'number' || schemaType === 'integer') return z.number();
  if (schemaType === 'boolean') return z.boolean();
  if (schemaType === 'array') {
    const items = schema.items && typeof schema.items === 'object' && !Array.isArray(schema.items)
      ? jsonSchemaToZod(schema.items as Record<string, unknown>)
      : z.any();
    return z.array(items);
  }
  if (schemaType === 'object' || schema.properties) {
    const properties = (schema.properties && typeof schema.properties === 'object' && !Array.isArray(schema.properties)
      ? schema.properties
      : {}) as Record<string, Record<string, unknown>>;
    const required = new Set(Array.isArray(schema.required) ? schema.required.filter((item): item is string => typeof item === 'string') : []);
    const shape: Record<string, z.ZodTypeAny> = {};
    for (const [key, value] of Object.entries(properties)) {
      const propSchema = jsonSchemaToZod(value || {});
      shape[key] = required.has(key) ? propSchema : propSchema.optional();
    }
    return z.object(shape).passthrough();
  }
  return z.any();
}

function maybeBuildOutputSchema(payload: RunnerInput | RunnerAgentInput): z.ZodTypeAny | undefined {
  if (!payload.outputSchema || typeof payload.outputSchema !== 'object') {
    return undefined;
  }
  return jsonSchemaToZod(payload.outputSchema as Record<string, unknown>);
}

function defaultTools(payload: RunnerInput, isReviewer = false): string[] {
  if (payload.needsTools === false) {
    return [];
  }
  return isReviewer
    ? ['bash', 'read', 'file_read', 'grep', 'run_semgrep']
    : ['bash', 'read', 'file_read', 'write', 'file_write', 'edit', 'file_edit', 'grep', 'run_semgrep'];
}

function applyPromptHook(prompt: string, config?: RunnerInput['beforeRun']): string {
  if (!config) return prompt;
  const prefix = String(config.promptPrefix || '');
  const suffix = String(config.promptSuffix || '');
  return `${prefix}${prefix ? '\n\n' : ''}${prompt}${suffix ? `\n\n${suffix}` : ''}`;
}

function applyOutputHook(result: AgentRunResult, config?: RunnerInput['afterRun']): AgentRunResult {
  if (!config) return result;
  const prefix = String(config.outputPrefix || '');
  const suffix = String(config.outputSuffix || '');
  const output = `${prefix}${prefix ? '\n\n' : ''}${result.output}${suffix ? `\n\n${suffix}` : ''}`;
  return {
    ...result,
    output,
  };
}

function makeBeforeRunHook(config?: RunnerInput['beforeRun']): AgentConfig['beforeRun'] | undefined {
  if (!config) return undefined;
  return (context) => ({ ...context, prompt: applyPromptHook(context.prompt, config) });
}

function makeAfterRunHook(config?: RunnerInput['afterRun']): AgentConfig['afterRun'] | undefined {
  if (!config) return undefined;
  return (result) => applyOutputHook(result, config);
}

async function waitForApprovalDecision(controlPath: string, timeoutMs = 30 * 60 * 1000): Promise<'approved' | 'rejected'> {
  const startedAt = Date.now();
  while ((Date.now() - startedAt) < timeoutMs) {
    try {
      const raw = await fs.readFile(controlPath, 'utf8');
      if (raw && raw.trim()) {
        const parsed = JSON.parse(raw) as { decision?: string };
        const decision = String(parsed?.decision || '').trim().toLowerCase();
        if (decision === 'approved' || decision === 'rejected') {
          return decision;
        }
      }
    } catch (_error) {
      // file not ready yet
    }
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
  throw new Error('Manual approval timed out.');
}

type ToolRiskLevel = 'safe' | 'review' | 'high';

function normalizeShellCommand(command: string): string {
  return String(command || '').trim().replace(/\s+/g, ' ').toLowerCase();
}

function classifyBashRisk(command: string): { level: ToolRiskLevel; reason: string } {
  const normalized = normalizeShellCommand(command);
  if (!normalized) {
    return { level: 'review', reason: 'empty_command' };
  }

  const safePrefixes = [
    'ls',
    'pwd',
    'find ',
    'wc ',
    'cat ',
    'head ',
    'tail ',
    'grep ',
    'rg ',
    'echo ',
    'stat ',
    'tree ',
  ];

  if (safePrefixes.some((prefix) => normalized === prefix.trim() || normalized.startsWith(prefix))) {
    return { level: 'safe', reason: 'read_only_shell_command' };
  }

  const highRiskPatterns: RegExp[] = [
    /(^|\s)rm\s+/,
    /(^|\s)mv\s+/,
    /(^|\s)chmod\s+/,
    /(^|\s)chown\s+/,
    /(^|\s)sudo\s+/,
    /git\s+reset\s+--hard/,
    /git\s+clean\b/,
    /(^|\s)(curl|wget)\b.*\|\s*(bash|sh)\b/,
    /(^|\s)(curl|wget|ssh|scp|rsync)\b/,
  ];

  if (highRiskPatterns.some((pattern) => pattern.test(normalized))) {
    return { level: 'high', reason: 'high_risk_shell_command' };
  }

  return { level: 'review', reason: 'shell_command_requires_review' };
}

function classifyToolRisk(toolName: string, input: Record<string, unknown>): { level: ToolRiskLevel; reason: string } {
  const name = String(toolName || '').trim().toLowerCase();

  if (name === 'read' || name === 'file_read' || name === 'grep') {
    return { level: 'safe', reason: 'read_only_tool' };
  }

  if (name === 'write' || name === 'file_write' || name === 'edit' || name === 'file_edit' || name === 'run_semgrep') {
    return { level: 'high', reason: 'state_changing_tool' };
  }

  if (name === 'bash') {
    const command = String(input.command || '').trim();
    return classifyBashRisk(command);
  }

  return { level: 'review', reason: 'unknown_tool_requires_review' };
}

function buildToolApprovalPayload(
  mode: string,
  toolName: string,
  input: Record<string, unknown>,
  risk: { level: ToolRiskLevel; reason: string },
): Extract<RunnerEvent, { type: 'approval_requested' }> {
  return {
    type: 'approval_requested',
    data: {
      mode,
      completedTasks: [],
      nextTasks: [
        {
          id: `tool:${toolName}`,
          title: `Tool approval required: ${toolName}`,
          status: 'pending',
          assignee: 'source_agent',
        },
      ],
      scope: 'tool_call',
      toolName,
      toolInput: input,
      riskLevel: risk.level,
      riskReason: risk.reason,
      summary: `Allow ${toolName} tool call (${risk.level} risk).`,
    },
  };
}

function buildToolApprovalGate(payload: RunnerInput, handlers: ToolEventHandlers): ((toolName: string, input: Record<string, unknown>) => Promise<void>) | undefined {
  const approvalMode = String(payload.approvalMode || 'off').trim().toLowerCase();
  if (approvalMode !== 'manual') {
    return undefined;
  }

  const controlPath = String(payload.approvalControlPath || '').trim();
  if (!controlPath) {
    throw new Error('Manual approval requested but approvalControlPath is missing.');
  }

  const gate = async (toolName: string, input: Record<string, unknown>): Promise<void> => {
    const risk = classifyToolRisk(toolName, input);
    if (risk.level === 'safe') {
      return;
    }

    await fs.writeFile(controlPath, JSON.stringify({ decision: 'pending' }), 'utf8');
    handlers.onEvent?.(buildToolApprovalPayload(approvalMode, toolName, input, risk));
    const decision = await waitForApprovalDecision(controlPath);
    if (decision !== 'approved') {
      throw new Error(`Manual approval rejected for tool: ${toolName}`);
    }
  };

  return gate;
}

function buildAgentConfigFromInput(
  payload: RunnerInput,
  agent: RunnerAgentInput | undefined,
  fallback: { name: string; role: string; systemPrompt: string; reviewer?: boolean },
): AgentConfig {
  const tools = agent?.tools ?? defaultTools(payload, Boolean(fallback.reviewer));
  return {
    name: agent?.name ?? fallback.name,
    model: agent?.model ?? payload.model,
    provider: agent?.provider ?? payload.provider,
    baseURL: agent?.baseURL ?? payload.baseUrl,
    apiKey: agent?.apiKey ?? payload.apiKey,
    systemPrompt: agent?.systemPrompt ?? payload.systemPrompt ?? fallback.systemPrompt,
    tools,
    maxTurns: agent?.maxTurns ?? payload.maxTurns ?? 10,
    maxTokens: agent?.maxTokens ?? payload.maxTokens,
    temperature: agent?.temperature ?? payload.temperature,
    timeoutMs: agent?.timeoutMs ?? payload.timeoutMs,
    loopDetection: agent?.loopDetection ?? payload.loopDetection,
    outputSchema: maybeBuildOutputSchema(agent ?? payload),
    beforeRun: makeBeforeRunHook(agent?.beforeRun ?? payload.beforeRun),
    afterRun: makeAfterRunHook(agent?.afterRun ?? payload.afterRun),
  };
}

function detectStrategy(payload: RunnerInput): 'agent' | 'team' | 'tasks' | 'fanout' {
  if (payload.strategy) {
    return payload.strategy;
  }
  if (payload.tasks?.length) {
    return 'tasks';
  }
  if (payload.fanout && ((payload.fanout.analysts?.length ?? 0) > 0)) {
    return 'fanout';
  }
  const teamMode = String(payload.teamMode || '').toLowerCase();
  if (teamMode.includes('team')) {
    return 'team';
  }
  const prompt = `${payload.prompt}\n${payload.contextSummary ?? ''}`.toLowerCase();
  if (['fan-out', 'fanout', 'parallel perspectives', 'multiple perspectives', 'aggregate'].some((m) => prompt.includes(m))) {
    return 'fanout';
  }
  if (['plan tasks', 'task pipeline', 'step by step tasks', 'dependency chain'].some((m) => prompt.includes(m))) {
    return 'tasks';
  }
  if (['team', 'collaborate', 'multiple agents', 'review together'].some((m) => prompt.includes(m))) {
    return 'team';
  }
  return 'agent';
}

function buildDecisionTrace(payload: RunnerInput, strategy: string): Record<string, unknown> {
  return {
    routing: 'vanilla_open_multi_agent',
    execution_mode: 'raw_open_multi_agent',
    team_mode: strategy === 'agent' ? 'single_agent' : strategy,
    strategy,
    needs_tools: Boolean(payload.needsTools ?? true),
    reason: `selected_${strategy}_strategy`,
  };
}

function buildBridgeAgentResult(name: string, role: string, result?: AgentRunResult): BridgeAgentResult {
  return {
    name,
    role,
    success: result?.success ?? false,
    output: result?.output ?? '',
    tokenUsage: result?.tokenUsage ?? ZERO_USAGE,
    toolCalls: result?.toolCalls ?? [],
    structured: result?.structured,
    loopDetected: result?.loopDetected,
  };
}

function aggregateTokenUsage(results: AgentRunResult[]): TokenUsage {
  return results.reduce(
    (acc, result) => ({
      input_tokens: acc.input_tokens + (result.tokenUsage?.input_tokens ?? 0),
      output_tokens: acc.output_tokens + (result.tokenUsage?.output_tokens ?? 0),
    }),
    { ...ZERO_USAGE },
  );
}

function aggregateToolCalls(results: AgentRunResult[]): any[] {
  return results.flatMap((result) => result.toolCalls ?? []);
}

function normalizeTaskResult(task: Task, retries = 0): BridgeTaskResult {
  return {
    id: String(task.id || task.title),
    title: String(task.title || ''),
    status: task.status,
    assignee: task.assignee,
    dependsOn: [...(task.dependsOn ?? [])],
    result: task.result,
    retries,
  };
}

function convertTeamRunToBridgeResult(
  strategy: string,
  result: TeamRunResult,
  options: { traces?: TraceEvent[]; tasks?: BridgeTaskResult[]; coordinatorOutput?: string },
): BridgeRunResult {
  const agentEntries = [...result.agentResults.entries()];
  const visibleAgentEntries = agentEntries.filter(([name]) => !name.endsWith(':decompose'));
  const agents = visibleAgentEntries.map(([name, agentResult]) =>
    buildBridgeAgentResult(name, name === 'coordinator' ? 'coordinator' : name, agentResult),
  );
  const outputs = visibleAgentEntries
    .map(([name, agentResult]) => `## ${name}\n${agentResult.output}`)
    .join('\n\n');
  const coordinator = result.agentResults.get('coordinator');
  const content = coordinator?.output || options.coordinatorOutput || outputs;
  return {
    success: result.success,
    output: content,
    content,
    messages: coordinator?.messages ?? [],
    tokenUsage: result.totalTokenUsage,
    toolCalls: aggregateToolCalls(visibleAgentEntries.map(([, r]) => r)),
    agents,
    tasks: options.tasks ?? [],
    structured: coordinator?.structured,
    traces: options.traces,
    strategy,
  };
}

function createOrchestrator(payload: RunnerInput, handlers: ToolEventHandlers, strategy: string, traces: TraceEvent[]): OpenMultiAgent {
  return new OpenMultiAgent({
    defaultModel: payload.model,
    defaultProvider: payload.provider,
    defaultBaseURL: payload.baseUrl,
    defaultApiKey: payload.apiKey,
    maxConcurrency: strategy === 'fanout' ? Math.max(payload.fanout?.analysts?.length ?? 3, 3) : 3,
    onProgress: (event: OrchestratorEvent) => {
      if (event.type === 'agent_start') {
        emitOrchestratorEvent(handlers, { type: 'agent_started', data: { name: String(event.agent || ''), role: String(event.agent || '') } });
      } else if (event.type === 'agent_complete') {
        emitOrchestratorEvent(handlers, { type: 'agent_completed', data: { name: String(event.agent || ''), role: String(event.agent || '') } });
      } else if (event.type === 'task_start') {
        const task = (event.data ?? {}) as Partial<Task>;
        emitOrchestratorEvent(handlers, {
          type: 'task_started',
          data: { id: String(task.id || event.task || ''), title: String(task.title || event.task || ''), assignee: task.assignee, dependsOn: task.dependsOn ? [...task.dependsOn] : undefined },
        });
      } else if (event.type === 'task_complete') {
        const task = (event.data ?? {}) as Partial<Task>;
        emitOrchestratorEvent(handlers, {
          type: 'task_completed',
          data: { id: String(task.id || event.task || ''), title: String(task.title || event.task || ''), assignee: task.assignee, result: task.result },
        });
      } else if (event.type === 'task_retry') {
        const data = (event.data ?? {}) as Record<string, unknown>;
        emitOrchestratorEvent(handlers, {
          type: 'task_retry',
          data: {
            id: String(event.task || ''),
            title: String(event.task || ''),
            attempt: Number(data.attempt || 0),
            maxAttempts: Number(data.maxAttempts || 0),
            error: String(data.error || ''),
            nextDelayMs: Number(data.nextDelayMs || 0),
          },
        });
      } else if (event.type === 'task_skipped') {
        const task = (event.data ?? {}) as Partial<Task>;
        emitOrchestratorEvent(handlers, {
          type: 'task_skipped',
          data: { id: String(task.id || event.task || ''), title: String(task.title || event.task || ''), assignee: task.assignee },
        });
      } else if (event.type === 'message') {
        const data = (event.data ?? {}) as Record<string, unknown>;
        emitOrchestratorEvent(handlers, {
          type: 'agent_message',
          data: {
            from: String(event.agent || data.from || ''),
            to: String(data.to || 'team'),
            content: String(data.content || ''),
          },
        });
      }
    },
    onTrace: payload.traceEnabled
      ? async (event: TraceEvent) => {
          traces.push(event);
          emitOrchestratorEvent(handlers, { type: 'trace', data: event });
        }
      : undefined,
  });
}

async function runSingleAgentStrategy(
  payload: RunnerInput,
  handlers: ToolEventHandlers,
  traces: TraceEvent[],
  toolApprovalGate?: (toolName: string, input: Record<string, unknown>) => Promise<void>,
): Promise<BridgeRunResult> {
  const config = buildAgentConfigFromInput(payload, payload.agents?.[0], {
    name: DEFAULT_AGENT_NAME,
    role: 'source_code_assistant',
    systemPrompt: 'You are a direct source-code assistant. Inspect the workspace, use tools when helpful, and answer concisely with evidence.',
  });
  const registry = createRegistry(payload.workspaceRoot, handlers, toolApprovalGate);
  const executor = new ToolExecutor(registry);
  const agent = new Agent(config, registry, executor);
  emitOrchestratorEvent(handlers, { type: 'agent_started', data: { name: config.name, role: 'source_code_assistant' } });
  const result = await agent.run(payload.prompt);
  emitOrchestratorEvent(handlers, { type: 'agent_completed', data: { name: config.name, role: 'source_code_assistant' } });
  return {
    success: result.success,
    output: result.output,
    content: result.output,
    messages: result.messages,
    tokenUsage: result.tokenUsage,
    toolCalls: result.toolCalls,
    agents: [buildBridgeAgentResult(config.name, 'source_code_assistant', result)],
    tasks: [{ id: 'direct-source-conversation', title: 'Direct source conversation', status: result.success ? 'completed' : 'failed', assignee: config.name, result: result.output }],
    structured: result.structured,
    traces,
    strategy: 'agent',
  };
}

async function runAutoTeamStrategy(
  payload: RunnerInput,
  handlers: ToolEventHandlers,
  traces: TraceEvent[],
): Promise<BridgeRunResult> {
  const orchestrator = createOrchestrator(payload, handlers, 'team', traces);
  const defaultAgents: AgentConfig[] = [
    buildAgentConfigFromInput(payload, payload.agents?.[0], {
      name: 'architect',
      role: 'architect',
      systemPrompt: 'You are a software architect and source-code analyst. Design the work, identify key code paths, and communicate clearly.',
    }),
    buildAgentConfigFromInput(payload, payload.agents?.[1], {
      name: 'developer',
      role: 'developer',
      systemPrompt: 'You are a practical code investigator. Read files, inspect implementations, and produce grounded technical findings.',
    }),
    buildAgentConfigFromInput(payload, payload.agents?.[2], {
      name: 'reviewer',
      role: 'reviewer',
      systemPrompt: 'You are a critical reviewer focused on correctness, security, and clarity. Challenge weak claims and sharpen findings.',
      reviewer: true,
    }),
  ];
  const agents = payload.agents?.length ? payload.agents.map((agent, index) => buildAgentConfigFromInput(payload, agent, {
    name: agent.name || `agent_${index + 1}`,
    role: agent.role || agent.name || `agent_${index + 1}`,
    systemPrompt: agent.systemPrompt || 'You are a collaborative multi-agent worker.',
    reviewer: /review/i.test(agent.name || agent.role || ''),
  })) : defaultAgents;
  const team = orchestrator.createTeam(payload.teamMode || DEFAULT_TEAM_NAME, {
    name: payload.teamMode || DEFAULT_TEAM_NAME,
    agents,
    sharedMemory: payload.sharedMemory ?? true,
    maxConcurrency: Math.min(Math.max(agents.length, 1), 3),
  });
  emitOrchestratorEvent(handlers, { type: 'team_started', data: { name: team.name, agents: agents.map((a) => a.name), strategy: 'team' } });
  const result = await orchestrator.runTeam(team, payload.prompt);
  return convertTeamRunToBridgeResult('team', result, { traces });
}

async function runTaskPipelineStrategy(payload: RunnerInput, handlers: ToolEventHandlers, traces: TraceEvent[]): Promise<BridgeRunResult> {
  const approvalMode = String(payload.approvalMode || 'off');
  const onProgress = (event: OrchestratorEvent) => {
    if (event.type === 'agent_start') {
      emitOrchestratorEvent(handlers, { type: 'agent_started', data: { name: String(event.agent || ''), role: String(event.agent || '') } });
    } else if (event.type === 'agent_complete') {
      emitOrchestratorEvent(handlers, { type: 'agent_completed', data: { name: String(event.agent || ''), role: String(event.agent || '') } });
    } else if (event.type === 'task_start') {
      const task = (event.data ?? {}) as Partial<Task>;
      emitOrchestratorEvent(handlers, { type: 'task_started', data: { id: String(task.id || event.task || ''), title: String(task.title || event.task || ''), assignee: task.assignee, dependsOn: task.dependsOn ? [...task.dependsOn] : undefined } });
    } else if (event.type === 'task_complete') {
      const task = (event.data ?? {}) as Partial<Task>;
      emitOrchestratorEvent(handlers, { type: 'task_completed', data: { id: String(task.id || event.task || ''), title: String(task.title || event.task || ''), assignee: task.assignee, result: task.result } });
    } else if (event.type === 'task_retry') {
      const data = (event.data ?? {}) as Record<string, unknown>;
      emitOrchestratorEvent(handlers, { type: 'task_retry', data: { id: String(event.task || ''), title: String(event.task || ''), attempt: Number(data.attempt || 0), maxAttempts: Number(data.maxAttempts || 0), error: String(data.error || ''), nextDelayMs: Number(data.nextDelayMs || 0) } });
    } else if (event.type === 'task_skipped') {
      const task = (event.data ?? {}) as Partial<Task>;
      emitOrchestratorEvent(handlers, { type: 'task_skipped', data: { id: String(task.id || event.task || ''), title: String(task.title || event.task || ''), assignee: task.assignee } });
    } else if (event.type === 'error') {
      const data = (event.data ?? {}) as Record<string, unknown>;
      emitOrchestratorEvent(handlers, { type: 'task_failed', data: { id: String(event.task || ''), title: String(event.task || ''), assignee: String(event.agent || ''), error: String(data.output || data.error || 'task_failed') } });
    } else if (event.type === 'message') {
      const data = (event.data ?? {}) as Record<string, unknown>;
      emitOrchestratorEvent(handlers, { type: 'agent_message', data: { from: String(event.agent || data.from || ''), to: String(data.to || 'team'), content: String(data.content || '') } });
    }
  };
  const orchestrator = new OpenMultiAgent({
    defaultModel: payload.model,
    defaultProvider: payload.provider,
    defaultBaseURL: payload.baseUrl,
    defaultApiKey: payload.apiKey,
    maxConcurrency: 3,
    onProgress,
    onTrace: payload.traceEnabled
      ? async (event: TraceEvent) => {
          traces.push(event);
          emitOrchestratorEvent(handlers, { type: 'trace', data: event });
        }
      : undefined,
    onApproval: approvalMode === 'off'
      ? undefined
      : async (completedTasks, nextTasks) => {
          emitOrchestratorEvent(handlers, {
            type: 'approval_requested',
            data: {
              mode: approvalMode,
              completedTasks: completedTasks.map((task) => ({ id: task.id, title: task.title, status: task.status, assignee: task.assignee })),
              nextTasks: nextTasks.map((task) => ({ id: task.id, title: task.title, status: task.status, assignee: task.assignee })),
            },
          });
          if (approvalMode === 'auto_approve') {
            return true;
          }
          if (approvalMode === 'manual') {
            const controlPath = String(payload.approvalControlPath || '').trim();
            if (!controlPath) {
              throw new Error('Manual approval requested but approvalControlPath is missing.');
            }
            const decision = await waitForApprovalDecision(controlPath);
            return decision === 'approved';
          }
          return false;
        },
  });
  const baseAgents = payload.agents?.length
    ? payload.agents.map((agent, index) => buildAgentConfigFromInput(payload, agent, {
        name: agent.name || `agent_${index + 1}`,
        role: agent.role || agent.name || `agent_${index + 1}`,
        systemPrompt: agent.systemPrompt || 'You are a task worker.',
      }))
    : [
        buildAgentConfigFromInput(payload, undefined, {
          name: 'researcher',
          role: 'researcher',
          systemPrompt: 'You research the workspace and gather relevant evidence.',
        }),
        buildAgentConfigFromInput(payload, { name: 'reviewer', role: 'reviewer', tools: defaultTools(payload, true) }, {
          name: 'reviewer',
          role: 'reviewer',
          systemPrompt: 'You review gathered evidence and summarize findings.',
          reviewer: true,
        }),
      ];
  const team = orchestrator.createTeam('task-pipeline-team', {
    name: 'task-pipeline-team',
    agents: baseAgents,
    sharedMemory: payload.sharedMemory ?? true,
    maxConcurrency: Math.min(Math.max(baseAgents.length, 1), 3),
  });
  emitOrchestratorEvent(handlers, { type: 'team_started', data: { name: team.name, agents: baseAgents.map((a) => a.name), strategy: 'tasks' } });
  const tasks = payload.tasks?.length
    ? payload.tasks
    : [
        { title: 'Inspect workspace', description: payload.prompt, assignee: baseAgents[0]?.name },
        { title: 'Summarize findings', description: 'Read the shared memory and summarize the workspace findings for the user.', assignee: baseAgents[1]?.name, dependsOn: ['Inspect workspace'] },
      ];
  const result = await orchestrator.runTasks(team, tasks);
  const bridgeTasks = tasks.map((task) => ({
    id: task.title,
    title: task.title,
    status: 'completed' as const,
    assignee: task.assignee,
    dependsOn: task.dependsOn,
  }));
  return convertTeamRunToBridgeResult('tasks', result, { traces, tasks: bridgeTasks });
}

async function runFanoutStrategy(
  payload: RunnerInput,
  handlers: ToolEventHandlers,
  traces: TraceEvent[],
): Promise<BridgeRunResult> {
  const analysts = payload.fanout?.analysts?.length
    ? payload.fanout.analysts
    : [
        { name: 'optimist', role: 'optimist', systemPrompt: 'You are an optimistic analyst. Focus on upside, opportunities, and strong signals.' },
        { name: 'skeptic', role: 'skeptic', systemPrompt: 'You are a skeptical analyst. Focus on risks, gaps, edge cases, and failure modes.' },
        { name: 'pragmatist', role: 'pragmatist', systemPrompt: 'You are a pragmatic analyst. Focus on feasibility, evidence, and realistic trade-offs.' },
      ];
  const synthesizerInput = payload.fanout?.synthesizer ?? {
    name: DEFAULT_SYNTHESIZER_NAME,
    role: 'synthesizer',
    systemPrompt: 'You synthesize multiple analyses into one balanced, actionable answer.',
  };
  const pool = new AgentPool(Math.max(analysts.length, 1));
  const allResults: AgentRunResult[] = [];
  for (const agent of [...analysts, synthesizerInput]) {
    const config = buildAgentConfigFromInput(payload, agent, {
      name: agent.name,
      role: agent.role || agent.name,
      systemPrompt: agent.systemPrompt || 'You are a collaborative analyst.',
      reviewer: /review/i.test(agent.name || agent.role || ''),
    });
    pool.add(createAgentInstance(config, payload.workspaceRoot, handlers));
  }
  emitOrchestratorEvent(handlers, {
    type: 'team_started',
    data: { name: 'fanout-team', agents: [...analysts.map((a) => a.name), synthesizerInput.name], strategy: 'fanout' },
  });
  const sharedPrompt = payload.fanout?.sharedPrompt || payload.prompt;
  const analystResults = await pool.runParallel(analysts.map((agent) => ({ agent: agent.name, prompt: sharedPrompt })));
  const bridgeAgents: BridgeAgentResult[] = [];
  for (const analyst of analysts) {
    const result = analystResults.get(analyst.name);
    if (result) {
      allResults.push(result);
      bridgeAgents.push(buildBridgeAgentResult(analyst.name, analyst.role || analyst.name, result));
    }
  }
  const synthesisPrompt = payload.fanout?.synthesisPrompt || [
    'Read the analyst outputs below and produce one balanced response.',
    ...analysts.map((analyst) => `--- ${analyst.name.toUpperCase()} ---\n${analystResults.get(analyst.name)?.output || ''}`),
  ].join('\n\n');
  const synthResult = await pool.run(synthesizerInput.name, synthesisPrompt);
  allResults.push(synthResult);
  bridgeAgents.push(buildBridgeAgentResult(synthesizerInput.name, synthesizerInput.role || synthesizerInput.name, synthResult));
  return {
    success: bridgeAgents.some((agent) => agent.success),
    output: synthResult.output,
    content: synthResult.output,
    messages: synthResult.messages,
    tokenUsage: aggregateTokenUsage(allResults),
    toolCalls: aggregateToolCalls(allResults),
    agents: bridgeAgents,
    tasks: [
      ...analysts.map((agent) => ({ id: `fanout-${agent.name}`, title: `Fan-out analysis: ${agent.name}`, status: analystResults.get(agent.name)?.success ? 'completed' as const : 'failed' as const, assignee: agent.name, result: analystResults.get(agent.name)?.output || '' })),
      { id: 'aggregate-synthesis', title: 'Aggregate synthesis', status: synthResult.success ? 'completed' : 'failed', assignee: synthesizerInput.name, result: synthResult.output },
    ],
    structured: synthResult.structured,
    traces,
    strategy: 'fanout',
  };
}

async function runPayload(payload: RunnerInput, handlers: ToolEventHandlers): Promise<BridgeRunResult> {
  applyProviderEnvironment(payload);
  const strategy = detectStrategy(payload);
  const traces: TraceEvent[] = [];
  const toolApprovalGate = strategy === 'agent' ? buildToolApprovalGate(payload, handlers) : undefined;
  handlers.onEvent?.({ type: 'decision_trace', data: buildDecisionTrace(payload, strategy) });
  switch (strategy) {
    case 'team':
      return runAutoTeamStrategy(payload, handlers, traces);
    case 'tasks':
      return runTaskPipelineStrategy(payload, handlers, traces);
    case 'fanout':
      return runFanoutStrategy(payload, handlers, traces);
    case 'agent':
    default:
      return runSingleAgentStrategy(payload, handlers, traces, toolApprovalGate);
  }
}

function createHandlers(writeEvent: (event: RunnerEvent) => void): ToolEventHandlers {
  return {
    onToolCall: (name, input) => writeEvent({ type: 'tool_call', data: { name, input } }),
    onToolResult: (name, result) => writeEvent({ type: 'tool_result', data: { name, result } }),
    onEvent: (event) => writeEvent(event),
  };
}

async function runOnce(rawInput: string, options: { writeEvent: (event: RunnerEvent) => void }): Promise<void> {
  const payload = parseRunnerInput(rawInput);
  const strategy = detectStrategy(payload);
  options.writeEvent({
    type: 'run_started',
    data: {
      workspaceRoot: payload.workspaceRoot,
      model: payload.model,
      provider: payload.provider,
      strategy,
    },
  });

  try {
    const handlers = createHandlers(options.writeEvent);
    const result = await runPayload(payload, handlers);
    options.writeEvent({ type: 'run_completed', data: result });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    options.writeEvent({ type: 'run_failed', data: { message } });
    process.exitCode = 1;
  }
}

async function readStdin(stream: InputStream = process.stdin): Promise<string> {
  let raw = '';
  for await (const chunk of stream) {
    raw += chunk.toString();
  }
  return raw.trim();
}

async function main(): Promise<void> {
  const rawInput = await readStdin();
  if (!rawInput) {
    throw new Error('Runner input is required.');
  }
  const writeEvent = makeJsonOutputWriter(process.stdout);
  await runOnce(rawInput, { writeEvent });
}

main().catch((error) => {
  const writeEvent = makeJsonOutputWriter(process.stdout);
  writeEvent({
    type: 'run_failed',
    data: { message: error instanceof Error ? error.message : String(error) },
  });
  process.exitCode = 1;
});
