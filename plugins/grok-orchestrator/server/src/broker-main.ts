import { BrokerService } from "./broker-service.js";
import { createRpcHandler } from "./rpc-router.js";
import { runtimePaths } from "./runtime-paths.js";
import { SocketServer } from "./socket-transport.js";

const paths = runtimePaths();
const service = new BrokerService({
  stateRoot: paths.stateRoot,
  grokBinary: process.env.GROK_BINARY ?? "/home/haonguyen/.local/bin/grok",
  expectedVersion: process.env.GROK_EXPECTED_VERSION ?? "0.2.101",
});
await service.verifyGrokBinary();
const server = new SocketServer(paths.socketPath, paths.stateRoot, createRpcHandler(service));
await server.start();
const stop = async (): Promise<void> => { await server.stop(); process.exit(0); };
process.on("SIGINT", () => { void stop(); });
process.on("SIGTERM", () => { void stop(); });
