# integration fixture workspace

An empty folder opened as the workspace when the `@vscode/test-electron` smoke suite
boots VS Code, so the extension has a `workspaceFolders[0]` to resolve its cwd from.
Nothing here matters to the tests — it just needs to exist.
