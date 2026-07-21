import { defineConfig } from "@vscode/test-cli";

// Config for the @vscode/test-electron smoke suite (npm run test:integration).
// The extension is compiled to out/ and the tests to out-integration/ BEFORE this
// runs (see the test:integration script). @vscode/test-cli downloads a real VS Code
// (into .vscode-test/) and runs the compiled Mocha tests inside its Extension Host.
export default defineConfig({
  files: "out-integration/**/*.test.js",
  version: "stable",
  // Open a throwaway fixture folder so the extension has a workspace to resolve its cwd.
  workspaceFolder: "./integration/fixture-workspace",
  mocha: {
    ui: "tdd",
    timeout: 60000,
  },
});
