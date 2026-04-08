# DeepDoc VS Code Extension

Explain selected code in Fast or Deep mode and insert generated comments above the selected lines.

## Features

- Hover selected text to get `DeepDoc · Fast | Deep` actions.
- Fast and Deep command variants.
- Auto-insert explanation above selection in language-appropriate comments.
- Replace existing generated comment block above the same selection.
- Supports OpenAI-compatible and Azure OpenAI endpoints.
- Uses VS Code SecretStorage for API key.

## Commands

- `DeepDoc: Fast`
- `DeepDoc: Deep`
- `DeepDoc: Test Connection`
- `DeepDoc: Set API Key`
- `DeepDoc: Clear API Key`

## Keyboard shortcuts

- Fast: `Cmd+Alt+E` (macOS), `Ctrl+Alt+E` (Windows/Linux)
- Deep: `Cmd+Alt+D` (macOS), `Ctrl+Alt+D` (Windows/Linux)

## Settings

- `deepdoc.baseUrl`
- `deepdoc.provider`
- `deepdoc.azureApiVersion`
- `deepdoc.azureDeploymentName`
- `deepdoc.fastModel`
- `deepdoc.deepModel`
- `deepdoc.maxSelectedLines`
- `deepdoc.includeContextLines`
- `deepdoc.timeoutMs`
- `deepdoc.fastMaxTokens`
- `deepdoc.deepMaxTokens`
- `deepdoc.includeMetadataHeader`
- `deepdoc.includeMarkers`
- `deepdoc.replaceExistingBlock`

## Local development

```bash
npm install
npm run compile
```

Run extension host from VS Code with `F5` using `Run DeepDoc Extension`.

## Package VSIX

```bash
npm run compile
npx @vscode/vsce package
```

## Publish

```bash
npx @vscode/vsce publish
```
