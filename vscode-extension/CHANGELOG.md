# Changelog

All notable changes to the DeepDoc VS Code extension are documented here.

## [0.0.2] - 2026-04-08

### Added

- Added automated VS Code Marketplace publishing workflow scoped to `vscode-extension/`.
- Added auto-tagging and GitHub release creation for extension versions.

### Changed

- Moved extension into `vscode-extension/` for clear separation from Python package release flow.

## [0.0.1] - 2026-04-08

### Added

- Initial DeepDoc extension release.
- Fast and Deep snippet explanation commands.
- Hover actions for selected code with clickable Fast/Deep.
- Automatic comment insertion above selected lines.
- Replace behavior for previously generated comment block above selection.
- Provider support for OpenAI-compatible endpoints and Azure OpenAI.
- API key handling via VS Code SecretStorage.
- Connection test command.
- Keyboard shortcuts: `Cmd/Ctrl+Alt+E` (Fast), `Cmd/Ctrl+Alt+D` (Deep).
