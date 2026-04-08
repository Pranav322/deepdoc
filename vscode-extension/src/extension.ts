import * as vscode from 'vscode';

const START_MARKER = 'AI_DOC_START: deepdoc';
const END_MARKER = 'AI_DOC_END: deepdoc';
const API_KEY_SECRET = 'deepdoc.apiKey';

type ExplainMode = 'fast' | 'deep';
type ProviderKind = 'openaiCompatible' | 'azureOpenAI';

interface ExtensionConfig {
  provider: ProviderKind;
  baseUrl: string;
  azureApiVersion: string;
  azureDeploymentName: string;
  fastModel: string;
  deepModel: string;
  maxSelectedLines: number;
  includeContextLines: number;
  timeoutMs: number;
  fastMaxTokens: number;
  deepMaxTokens: number;
  includeMetadataHeader: boolean;
  includeMarkers: boolean;
  replaceExistingBlock: boolean;
}

interface PreparedRequest {
  endpoint: string;
  headers: Record<string, string>;
  body: Record<string, unknown>;
}

interface SelectionPayload {
  selectedText: string;
  contextBefore: string;
  contextAfter: string;
  selectionStartLine: number;
  selectionEndLine: number;
  totalSelectedLines: number;
  effectiveSelectedLines: number;
  truncated: boolean;
  indent: string;
}

interface ChatCompletionResponse {
  choices?: Array<{
    message?: {
      content?: unknown;
    };
  }>;
  error?: {
    message?: string;
  };
}

interface PostJsonResult {
  status: number;
  responseBody: ChatCompletionResponse;
}

type CommentStyle =
  | { kind: 'line'; prefix: string }
  | { kind: 'block'; start: string; end: string };

export function activate(context: vscode.ExtensionContext): void {
  const hoverSelector: vscode.DocumentSelector = [
    { scheme: 'file', language: '*' },
    { scheme: 'untitled', language: '*' }
  ];

  const hoverProvider = vscode.languages.registerHoverProvider(hoverSelector, {
    provideHover(document, position) {
      const editor = vscode.window.activeTextEditor;
      if (!editor) {
        return undefined;
      }

      if (editor.document.uri.toString() !== document.uri.toString()) {
        return undefined;
      }

      const selection = editor.selection;
      if (selection.isEmpty) {
        return undefined;
      }

      const selectedRange = new vscode.Range(selection.start, selection.end);
      if (!selectedRange.contains(position)) {
        return undefined;
      }

      const markdown = new vscode.MarkdownString(
        '$(sparkle) **DeepDoc** · [Fast](command:deepdoc.explainFast) | [Deep](command:deepdoc.explainDeep)'
      );
      markdown.isTrusted = true;

      return new vscode.Hover(markdown, selectedRange);
    }
  });

  context.subscriptions.push(hoverProvider);

  context.subscriptions.push(
    vscode.commands.registerCommand('deepdoc.explainFast', () => runExplain('fast', context)),
    vscode.commands.registerCommand('deepdoc.explainDeep', () => runExplain('deep', context)),
    vscode.commands.registerCommand('deepdoc.testConnection', () => testConnection(context)),
    vscode.commands.registerCommand('deepdoc.configureApiKey', () => configureApiKey(context)),
    vscode.commands.registerCommand('deepdoc.clearApiKey', () => clearApiKey(context))
  );
}

export function deactivate(): void {
  // No-op
}

async function runExplain(mode: ExplainMode, context: vscode.ExtensionContext): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    void vscode.window.showWarningMessage('DeepDoc: open a file and select text first.');
    return;
  }

  if (editor.selection.isEmpty) {
    void vscode.window.showWarningMessage('DeepDoc: select a snippet first.');
    return;
  }

  const config = getConfig();
  const payload = buildSelectionPayload(editor, config);
  if (!payload) {
    void vscode.window.showWarningMessage('DeepDoc: unable to read selected text.');
    return;
  }

  const model = mode === 'fast' ? config.fastModel : config.deepModel;
  const displayPath = vscode.workspace.asRelativePath(editor.document.uri, false);

  try {
    const explanation = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: `DeepDoc: ${mode === 'fast' ? 'Fast' : 'Deep'} explanation`,
        cancellable: false
      },
      async () => requestExplanation({
        mode,
        model,
        config,
        context,
        document: editor.document,
        payload,
        displayPath
      })
    );

    const blockText = buildCommentBlock({
      mode,
      model,
      document: editor.document,
      displayPath,
      payload,
      explanation,
      maxSelectedLines: config.maxSelectedLines,
      includeMetadataHeader: config.includeMetadataHeader,
      includeMarkers: config.includeMarkers
    });

    const workspaceEdit = new vscode.WorkspaceEdit();
    const existingBlock = config.replaceExistingBlock
      ? findExistingGeneratedBlockAbove(editor.document, payload.selectionStartLine, editor.document.languageId, payload.indent, config)
      : undefined;

    if (existingBlock) {
      workspaceEdit.replace(
        editor.document.uri,
        fullLineRange(editor.document, existingBlock.startLine, existingBlock.endLine),
        blockText
      );
    } else {
      workspaceEdit.insert(editor.document.uri, new vscode.Position(payload.selectionStartLine, 0), blockText);
    }

    const applied = await vscode.workspace.applyEdit(workspaceEdit);
    if (!applied) {
      throw new Error('Failed to apply editor changes.');
    }

    void vscode.window.setStatusBarMessage('DeepDoc: docs inserted above selection.', 2500);
  } catch (error) {
    void vscode.window.showErrorMessage(`DeepDoc failed: ${formatError(error)}`);
  }
}

async function configureApiKey(context: vscode.ExtensionContext): Promise<void> {
  const value = await vscode.window.showInputBox({
    title: 'DeepDoc API Key',
    prompt: 'Enter API key for LiteLLM/OpenAI-compatible endpoint (leave blank for local Ollama).',
    password: true,
    ignoreFocusOut: true
  });

  if (value === undefined) {
    return;
  }

  const trimmed = value.trim();
  if (!trimmed) {
    await context.secrets.delete(API_KEY_SECRET);
    void vscode.window.showInformationMessage('DeepDoc: API key cleared.');
    return;
  }

  await context.secrets.store(API_KEY_SECRET, trimmed);
  void vscode.window.showInformationMessage('DeepDoc: API key saved securely.');
}

async function clearApiKey(context: vscode.ExtensionContext): Promise<void> {
  await context.secrets.delete(API_KEY_SECRET);
  void vscode.window.showInformationMessage('DeepDoc: API key cleared.');
}

async function testConnection(context: vscode.ExtensionContext): Promise<void> {
  const config = getConfig();
  const model = config.fastModel || config.deepModel;

  if (!model) {
    void vscode.window.showErrorMessage('DeepDoc: configure fastModel or deepModel first.');
    return;
  }

  try {
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: 'DeepDoc: testing model connection',
        cancellable: false
      },
      async () => {
        const apiKey = await resolveApiKey(context, config.provider);
        const prepared = prepareRequest({
          config,
          mode: 'fast',
          model,
          apiKey,
          systemPrompt: 'You are a connectivity test assistant. Reply with one short line: OK.',
          userPrompt: 'Reply with OK only.'
        });

        const { responseBody, status } = await postJson(prepared.endpoint, prepared.headers, prepared.body, config.timeoutMs);
        if (status < 200 || status >= 300) {
          const message = responseBody.error?.message || `HTTP ${status}`;
          throw new Error(message);
        }

        const content = extractContent(responseBody.choices?.[0]?.message?.content);
        if (!content?.trim()) {
          throw new Error('Endpoint responded but returned empty content.');
        }
      }
    );

    void vscode.window.showInformationMessage('DeepDoc: connection OK.');
  } catch (error) {
    void vscode.window.showErrorMessage(`DeepDoc connection failed: ${formatError(error)}`);
  }
}

function getConfig(): ExtensionConfig {
  const config = vscode.workspace.getConfiguration('deepdoc');

  const providerValue = String(config.get<string>('provider', 'openaiCompatible')).trim();
  const provider: ProviderKind = providerValue === 'azureOpenAI' ? 'azureOpenAI' : 'openaiCompatible';
  const maxSelectedLines = Number(config.get<number>('maxSelectedLines', 1000));
  const includeContextLines = Number(config.get<number>('includeContextLines', 3));
  const timeoutMs = Number(config.get<number>('timeoutMs', 120000));
  const fastMaxTokens = Number(config.get<number>('fastMaxTokens', 0));
  const deepMaxTokens = Number(config.get<number>('deepMaxTokens', 0));

  return {
    provider,
    baseUrl: String(config.get<string>('baseUrl', 'http://localhost:4000/v1')).trim(),
    azureApiVersion: String(config.get<string>('azureApiVersion', '2024-02-15-preview')).trim(),
    azureDeploymentName: String(config.get<string>('azureDeploymentName', '')).trim(),
    fastModel: String(config.get<string>('fastModel', 'fast-local')).trim(),
    deepModel: String(config.get<string>('deepModel', 'deep-local')).trim(),
    maxSelectedLines: Number.isFinite(maxSelectedLines) && maxSelectedLines > 0 ? Math.floor(maxSelectedLines) : 1000,
    includeContextLines:
      Number.isFinite(includeContextLines) && includeContextLines >= 0 ? Math.floor(includeContextLines) : 3,
    timeoutMs: Number.isFinite(timeoutMs) && timeoutMs >= 1000 ? Math.floor(timeoutMs) : 120000,
    fastMaxTokens: Number.isFinite(fastMaxTokens) ? Math.max(0, Math.floor(fastMaxTokens)) : 0,
    deepMaxTokens: Number.isFinite(deepMaxTokens) ? Math.max(0, Math.floor(deepMaxTokens)) : 0,
    includeMetadataHeader: Boolean(config.get<boolean>('includeMetadataHeader', false)),
    includeMarkers: Boolean(config.get<boolean>('includeMarkers', false)),
    replaceExistingBlock: Boolean(config.get<boolean>('replaceExistingBlock', true))
  };
}

function buildSelectionPayload(editor: vscode.TextEditor, config: ExtensionConfig): SelectionPayload | undefined {
  const document = editor.document;
  const selection = editor.selection;

  let selectionEndLine = selection.end.line;
  if (selection.end.character === 0 && selection.end.line > selection.start.line) {
    selectionEndLine -= 1;
  }

  if (selectionEndLine < selection.start.line) {
    selectionEndLine = selection.start.line;
  }

  const totalSelectedLines = selectionEndLine - selection.start.line + 1;
  const effectiveEndLine = Math.min(selection.start.line + config.maxSelectedLines - 1, selectionEndLine);
  const effectiveSelectedLines = effectiveEndLine - selection.start.line + 1;
  const truncated = totalSelectedLines > config.maxSelectedLines;

  const endPosition = truncated ? document.lineAt(effectiveEndLine).range.end : selection.end;
  const effectiveRange = new vscode.Range(selection.start, endPosition);
  const selectedText = document.getText(effectiveRange);
  if (!selectedText.trim()) {
    return undefined;
  }

  const contextBefore = readContextBefore(document, selection.start.line, config.includeContextLines);
  const contextAfter = readContextAfter(document, effectiveEndLine, config.includeContextLines);
  const indent = document.lineAt(selection.start.line).text.match(/^\s*/)?.[0] ?? '';

  return {
    selectedText,
    contextBefore,
    contextAfter,
    selectionStartLine: selection.start.line,
    selectionEndLine: effectiveEndLine,
    totalSelectedLines,
    effectiveSelectedLines,
    truncated,
    indent
  };
}

function readContextBefore(document: vscode.TextDocument, selectionStartLine: number, contextLines: number): string {
  if (contextLines <= 0 || selectionStartLine === 0) {
    return '';
  }

  const startLine = Math.max(0, selectionStartLine - contextLines);
  const range = new vscode.Range(startLine, 0, selectionStartLine, 0);
  return document.getText(range).trimEnd();
}

function readContextAfter(document: vscode.TextDocument, selectionEndLine: number, contextLines: number): string {
  if (contextLines <= 0 || selectionEndLine >= document.lineCount - 1) {
    return '';
  }

  const afterStartLine = selectionEndLine + 1;
  const afterEndLine = Math.min(document.lineCount - 1, afterStartLine + contextLines - 1);
  const range = new vscode.Range(afterStartLine, 0, afterEndLine, document.lineAt(afterEndLine).range.end.character);
  return document.getText(range).trimEnd();
}

async function requestExplanation(args: {
  mode: ExplainMode;
  model: string;
  config: ExtensionConfig;
  context: vscode.ExtensionContext;
  document: vscode.TextDocument;
  payload: SelectionPayload;
  displayPath: string;
}): Promise<string> {
  const { mode, model, config, context, document, payload, displayPath } = args;

  if (!config.baseUrl) {
    throw new Error('`deepdoc.baseUrl` is empty.');
  }

  if (!model && !(config.provider === 'azureOpenAI' && config.azureDeploymentName)) {
    throw new Error(
      mode === 'fast'
        ? '`deepdoc.fastModel` is empty.'
        : '`deepdoc.deepModel` is empty.'
    );
  }

  const apiKey = await resolveApiKey(context, config.provider);
  const systemPrompt = mode === 'fast' ? fastSystemPrompt() : deepSystemPrompt();
  const userPrompt = buildUserPrompt({ mode, payload, document, displayPath, maxSelectedLines: config.maxSelectedLines });

  const prepared = prepareRequest({
    config,
    mode,
    model,
    apiKey,
    systemPrompt,
    userPrompt
  });

  try {
    const { responseBody, status } = await postJson(
      prepared.endpoint,
      prepared.headers,
      prepared.body,
      config.timeoutMs
    );

    if (status < 200 || status >= 300) {
      throw new Error(responseBody.error?.message || `HTTP ${status}`);
    }

    const content = extractContent(responseBody.choices?.[0]?.message?.content);
    if (!content?.trim()) {
      throw new Error('Model returned an empty response.');
    }

    return content.trim();
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error(`Request timed out after ${config.timeoutMs}ms.`);
    }

    if (error instanceof TypeError) {
      throw new Error(
        `Could not reach model endpoint at ${prepared.endpoint}. Check deepdoc.baseUrl and confirm Ollama/LiteLLM is running.`
      );
    }

    throw error;
  }
}

async function resolveApiKey(context: vscode.ExtensionContext, provider: ProviderKind): Promise<string | undefined> {
  const secret = await context.secrets.get(API_KEY_SECRET);
  if (secret?.trim()) {
    return secret.trim();
  }

  if (provider === 'azureOpenAI') {
    const envKey = process.env.AZURE_OPENAI_API_KEY;
    if (envKey?.trim()) {
      return envKey.trim();
    }
    throw new Error('Azure API key missing. Use `DeepDoc: Set API Key` or set AZURE_OPENAI_API_KEY.');
  }

  return undefined;
}

function prepareRequest(args: {
  config: ExtensionConfig;
  mode: ExplainMode;
  model: string;
  apiKey?: string;
  systemPrompt: string;
  userPrompt: string;
}): PreparedRequest {
  const { config, mode, model, apiKey, systemPrompt, userPrompt } = args;
  const maxTokens = mode === 'fast' ? config.fastMaxTokens : config.deepMaxTokens;
  const temperature = mode === 'fast' ? 0.2 : 0.1;

  const shouldUseMaxTokens = Number.isFinite(maxTokens) && maxTokens > 0;

  if (config.provider === 'azureOpenAI') {
    const deployment = config.azureDeploymentName || model;
    if (!deployment) {
      throw new Error('Azure deployment missing. Set `deepdoc.azureDeploymentName` or model setting.');
    }

    const endpointRoot = config.baseUrl.replace(/\/+$/, '');
    const apiVersion = config.azureApiVersion || '2024-02-15-preview';

    return {
      endpoint: `${endpointRoot}/openai/deployments/${encodeURIComponent(deployment)}/chat/completions?api-version=${encodeURIComponent(apiVersion)}`,
      headers: {
        'Content-Type': 'application/json',
        'api-key': apiKey ?? ''
      },
      body: {
        temperature,
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: userPrompt }
        ],
        ...(shouldUseMaxTokens ? { max_tokens: maxTokens } : {})
      }
    };
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json'
  };

  if (apiKey) {
    headers.Authorization = `Bearer ${apiKey}`;
  }

  return {
    endpoint: `${config.baseUrl.replace(/\/+$/, '')}/chat/completions`,
    headers,
    body: {
      model,
      temperature,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: userPrompt }
      ],
      ...(shouldUseMaxTokens ? { max_tokens: maxTokens } : {})
    }
  };
}

async function postJson(
  endpoint: string,
  headers: Record<string, string>,
  body: Record<string, unknown>,
  timeoutMs: number
): Promise<PostJsonResult> {
  const controller = new AbortController();
  const timeoutHandle = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal: controller.signal
    });

    let responseBody: ChatCompletionResponse = {};
    try {
      responseBody = (await response.json()) as ChatCompletionResponse;
    } catch {
      responseBody = {};
    }

    return {
      status: response.status,
      responseBody
    };
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error(`Request timed out after ${timeoutMs}ms.`);
    }

    throw error;
  } finally {
    clearTimeout(timeoutHandle);
  }
}

function buildUserPrompt(args: {
  mode: ExplainMode;
  payload: SelectionPayload;
  document: vscode.TextDocument;
  displayPath: string;
  maxSelectedLines: number;
}): string {
  const { mode, payload, document, displayPath, maxSelectedLines } = args;
  const scopeLine = `Selected lines in file: ${payload.selectionStartLine + 1}-${payload.selectionEndLine + 1}`;
  const truncationLine = payload.truncated
    ? `Selection was longer than ${maxSelectedLines} lines. Only the first ${maxSelectedLines} selected lines are included.`
    : 'Selection is fully included.';

  return [
    `Mode: ${mode}`,
    `Language: ${document.languageId}`,
    `File: ${displayPath}`,
    scopeLine,
    truncationLine,
    payload.contextBefore
      ? `Context before selection (${payload.contextBefore.split(/\r?\n/).length} lines):\n---\n${payload.contextBefore}\n---`
      : 'Context before selection: <none>',
    `Selected snippet (${payload.effectiveSelectedLines} lines):\n---\n${payload.selectedText}\n---`,
    payload.contextAfter
      ? `Context after selection (${payload.contextAfter.split(/\r?\n/).length} lines):\n---\n${payload.contextAfter}\n---`
      : 'Context after selection: <none>',
    'Return plain text only. Do not use markdown code fences.'
  ].join('\n\n');
}

function fastSystemPrompt(): string {
  return [
    'You explain code snippets quickly for developers.',
    'Write concise practical output in plain text.',
    'Focus on: intent, key flow, important variables/functions, side effects, and main caveats.',
    'Keep it short and scannable (about 6-12 lines).',
    'Never include chain-of-thought, internal reasoning, or thinking traces.',
    'Avoid filler and avoid markdown code fences.'
  ].join(' ');
}

function deepSystemPrompt(): string {
  return [
    'You explain code snippets in depth for developers.',
    'Write detailed plain text output with strong structure.',
    'Break explanation into logical blocks and describe behavior step by step.',
    'Mention conditions, data flow, assumptions, edge cases, and likely failure points.',
    'When useful, refer to relative line ranges (within the selected snippet).',
    'Never include chain-of-thought, internal reasoning, or thinking traces.',
    'Avoid markdown code fences.'
  ].join(' ');
}

function buildCommentBlock(args: {
  mode: ExplainMode;
  model: string;
  document: vscode.TextDocument;
  displayPath: string;
  payload: SelectionPayload;
  explanation: string;
  maxSelectedLines: number;
  includeMetadataHeader?: boolean;
  includeMarkers?: boolean;
}): string {
  const {
    mode,
    model,
    document,
    displayPath,
    payload,
    explanation,
    maxSelectedLines,
    includeMetadataHeader,
    includeMarkers
  } = args;
  const normalizedExplanation = normalizeExplanation(explanation);

  const lines: string[] = [];

  if (includeMarkers) {
    lines.push(START_MARKER);
  }

  if (includeMetadataHeader) {
    lines.push(
      `Mode: ${mode}`,
      `Model: ${model || 'azure-deployment'}`,
      `File: ${displayPath}`,
      `Selected lines: ${payload.selectionStartLine + 1}-${payload.selectionEndLine + 1}`,
      payload.truncated
        ? `Note: original selection had ${payload.totalSelectedLines} lines; explained first ${maxSelectedLines} lines.`
        : `Note: explained full selection (${payload.totalSelectedLines} lines).`,
      ''
    );
  }

  lines.push(...normalizedExplanation);

  if (includeMarkers) {
    lines.push(END_MARKER);
  }

  return formatCommentLines(document.languageId, payload.indent, lines);
}

function normalizeExplanation(explanation: string): string[] {
  const cleaned = explanation
    .replace(/```[a-zA-Z0-9_-]*\n?/g, '')
    .replace(/```/g, '')
    .replace(/(^|\n)\s*(reasoning|thinking process|chain of thought)\s*:?[\s\S]*$/i, '')
    .trim();

  if (!cleaned) {
    return ['No explanation content returned.'];
  }

  const allLines = cleaned.split(/\r?\n/);
  const result: string[] = [];

  for (const line of allLines) {
    const sanitized = sanitizeExplanationLine(line)
      .replaceAll(START_MARKER, 'AI_DOC_START (sanitized)')
      .replaceAll(END_MARKER, 'AI_DOC_END (sanitized)')
      .trimEnd();

    if (!sanitized) {
      if (result[result.length - 1] !== '') {
        result.push('');
      }
      continue;
    }

    result.push(sanitized);
  }

  while (result[result.length - 1] === '') {
    result.pop();
  }

  return result.length > 0 ? result : ['No explanation content returned.'];
}

function sanitizeExplanationLine(line: string): string {
  const lowered = line.toLowerCase();

  if (
    lowered.includes('thinking process') ||
    lowered.startsWith('reasoning:') ||
    lowered.startsWith('chain of thought') ||
    lowered.includes('internal reasoning')
  ) {
    return '';
  }

  return line;
}

function formatCommentLines(languageId: string, indent: string, lines: string[]): string {
  const style = getCommentStyle(languageId);

  if (style.kind === 'line') {
    return `${lines
      .map((line) => {
        if (!line) {
          return `${indent}${style.prefix.trimEnd()}`;
        }

        return `${indent}${style.prefix}${line}`;
      })
      .join('\n')}\n`;
  }

  return `${lines
    .map((line) => {
      if (!line) {
        return `${indent}${style.start}${style.end}`;
      }

      return `${indent}${style.start}${line}${style.end}`;
    })
    .join('\n')}\n`;
}

function getCommentStyle(languageId: string): CommentStyle {
  const slashLine = new Set([
    'javascript',
    'javascriptreact',
    'typescript',
    'typescriptreact',
    'java',
    'c',
    'cpp',
    'csharp',
    'go',
    'rust',
    'kotlin',
    'swift',
    'scala',
    'groovy',
    'dart',
    'php',
    'jsonc',
    'objective-c',
    'objective-cpp'
  ]);

  if (slashLine.has(languageId)) {
    return { kind: 'line', prefix: '// ' };
  }

  const hashLine = new Set([
    'python',
    'shellscript',
    'yaml',
    'dockerfile',
    'ruby',
    'perl',
    'toml',
    'makefile',
    'powershell',
    'r',
    'julia',
    'elixir',
    'ini',
    'gitcommit',
    'properties'
  ]);

  if (hashLine.has(languageId)) {
    return { kind: 'line', prefix: '# ' };
  }

  if (languageId === 'lua') {
    return { kind: 'line', prefix: '-- ' };
  }

  if (languageId === 'sql' || languageId === 'haskell') {
    return { kind: 'line', prefix: '-- ' };
  }

  if (languageId === 'erlang' || languageId === 'latex') {
    return { kind: 'line', prefix: '% ' };
  }

  if (languageId === 'html' || languageId === 'xml' || languageId === 'markdown' || languageId === 'mdx') {
    return { kind: 'block', start: '<!-- ', end: ' -->' };
  }

  if (languageId === 'css' || languageId === 'scss' || languageId === 'less') {
    return { kind: 'block', start: '/* ', end: ' */' };
  }

  return { kind: 'line', prefix: '// ' };
}

function findExistingGeneratedBlockAbove(
  document: vscode.TextDocument,
  selectionStartLine: number,
  languageId: string,
  indent: string,
  config: ExtensionConfig
): { startLine: number; endLine: number } | undefined {
  if (!config.includeMarkers) {
    return findContiguousCommentBlockAbove(document, selectionStartLine, languageId, indent);
  }

  let cursor = selectionStartLine - 1;

  while (cursor >= 0 && document.lineAt(cursor).text.trim() === '') {
    cursor -= 1;
  }

  if (cursor < 0) {
    return undefined;
  }

  if (!document.lineAt(cursor).text.includes(END_MARKER)) {
    return undefined;
  }

  const maxScanLines = 500;
  const floor = Math.max(0, cursor - maxScanLines);
  const endMarkerLine = cursor;
  let startMarkerLine = -1;

  for (let line = cursor; line >= floor; line -= 1) {
    const text = document.lineAt(line).text;

    if (text.includes(START_MARKER)) {
      startMarkerLine = line;
      break;
    }
  }

  if (startMarkerLine === -1 || endMarkerLine === -1 || startMarkerLine > endMarkerLine) {
    return undefined;
  }

  let endLine = endMarkerLine;
  while (endLine + 1 < selectionStartLine && document.lineAt(endLine + 1).text.trim() === '') {
    endLine += 1;
  }

  return {
    startLine: startMarkerLine,
    endLine
  };
}

function findContiguousCommentBlockAbove(
  document: vscode.TextDocument,
  selectionStartLine: number,
  languageId: string,
  indent: string
): { startLine: number; endLine: number } | undefined {
  let cursor = selectionStartLine - 1;
  while (cursor >= 0 && document.lineAt(cursor).text.trim() === '') {
    cursor -= 1;
  }

  if (cursor < 0) {
    return undefined;
  }

  const style = getCommentStyle(languageId);
  if (!isCommentLine(document.lineAt(cursor).text, style)) {
    return undefined;
  }

  const endLine = cursor;
  let startLine = cursor;

  while (startLine - 1 >= 0) {
    const previous = document.lineAt(startLine - 1).text;
    if (previous.trim() === '') {
      break;
    }

    if (!isCommentLine(previous, style)) {
      break;
    }

    startLine -= 1;
  }

  const firstLine = document.lineAt(startLine).text;
  const firstLineIndent = firstLine.match(/^\s*/)?.[0] ?? '';
  if (firstLineIndent !== indent) {
    return undefined;
  }

  return { startLine, endLine };
}

function isCommentLine(lineText: string, style: CommentStyle): boolean {
  const trimmed = lineText.trim();
  if (!trimmed) {
    return false;
  }

  if (style.kind === 'line') {
    const prefix = style.prefix.trim();
    return trimmed === prefix || trimmed.startsWith(`${prefix} `) || trimmed.startsWith(prefix);
  }

  const start = style.start.trim();
  const end = style.end.trim();
  return trimmed.startsWith(start) && trimmed.endsWith(end);
}

function fullLineRange(document: vscode.TextDocument, startLine: number, endLine: number): vscode.Range {
  const start = new vscode.Position(startLine, 0);

  if (endLine + 1 < document.lineCount) {
    return new vscode.Range(start, new vscode.Position(endLine + 1, 0));
  }

  return new vscode.Range(start, document.lineAt(endLine).range.end);
}

function extractContent(content: unknown): string | undefined {
  if (typeof content === 'string') {
    return content;
  }

  if (Array.isArray(content)) {
    const merged = content
      .map((item) => {
        if (typeof item === 'string') {
          return item;
        }

        if (item && typeof item === 'object' && 'text' in item) {
          const text = (item as { text?: unknown }).text;
          return typeof text === 'string' ? text : '';
        }

        return '';
      })
      .join('');

    return merged || undefined;
  }

  return undefined;
}

function formatError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return String(error);
}
