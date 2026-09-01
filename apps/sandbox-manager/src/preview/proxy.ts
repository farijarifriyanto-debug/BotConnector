import http from 'node:http';
import type { Socket } from 'node:net';
import type { PreviewManager, Preview } from './manager.js';

export interface PreviewProxyConfig {
  port: number;
  host: string;
  secret: string;
}

export class PreviewProxy {
  private readonly server: http.Server;
  private readonly previewManager: PreviewManager;
  private readonly config: PreviewProxyConfig;
  private readonly sockets = new Set<Socket>();
  private readonly upstreamRequests = new Set<http.ClientRequest>();
  private readonly upstreamResponses = new Set<http.IncomingMessage>();

  constructor(previewManager: PreviewManager, config: PreviewProxyConfig) {
    this.previewManager = previewManager;
    this.config = config;
    this.server = http.createServer((req, res) => this.handleRequest(req, res));
    this.server.on('connection', (socket) => {
      this.sockets.add(socket);
      socket.once('close', () => this.sockets.delete(socket));
    });
  }

  private authenticate(req: http.IncomingMessage): boolean {
    const authHeader = req.headers.authorization;
    if (!authHeader || authHeader !== `Bearer ${this.config.secret}`) {
      return false;
    }
    return true;
  }

  private async handleRequest(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    // Auth check
    if (!this.authenticate(req)) {
      res.writeHead(401, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: { code: 'UNAUTHORIZED', message: 'Invalid or missing authorization' } }));
      return;
    }

    const url = req.url ?? '/';

    // Extract preview ID from URL: /preview/:previewId/...
    const match = url.match(/^\/preview\/([^/]+)(\/.*)?$/);
    if (!match) {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: { code: 'NOT_FOUND', message: 'Preview not found. Use /preview/:previewId/...' } }));
      return;
    }

    const [, previewId, pathSuffix] = match;
    const targetPath = pathSuffix || '/';

    const preview = await this.previewManager.getPreview(previewId);
    if (!preview) {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: { code: 'NOT_FOUND', message: `Preview ${previewId} not found` } }));
      return;
    }

    if (preview.state !== 'running') {
      res.writeHead(503, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        error: { code: 'PREVIEW_NOT_RUNNING', message: `Preview is in state: ${preview.state}` },
      }));
      return;
    }

    if (!preview.containerIp) {
      res.writeHead(503, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        error: { code: 'NO_CONTAINER_IP', message: 'Preview container has no IP address' },
      }));
      return;
    }

    // Strip sensitive headers before forwarding
    const forwardedHeaders: Record<string, string | string[] | undefined> = {};
    const SENSITIVE_HEADERS = new Set([
      'authorization', 'cookie', 'x-forwarded-for', 'x-forwarded-proto',
      'x-real-ip', 'x-forwarded-host', 'x-forwarded-port',
      'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
      'te', 'trailer', 'transfer-encoding', 'upgrade',
    ]);
    for (const [key, value] of Object.entries(req.headers)) {
      if (!SENSITIVE_HEADERS.has(key.toLowerCase())) {
        forwardedHeaders[key] = value;
      }
    }

    // Proxy the request to the container using the preview's actual dev port
    const targetPort = preview.devPort;
    const proxyReq = http.request({
      hostname: preview.containerIp,
      port: targetPort,
      path: targetPath,
      method: req.method,
      headers: {
        ...forwardedHeaders,
        host: `${preview.containerIp}:${targetPort}`,
      },
    }, (proxyRes) => {
      this.upstreamResponses.add(proxyRes);
      proxyRes.once('close', () => this.upstreamResponses.delete(proxyRes));
       // Do not let an untrusted preview set cookies or hop-by-hop headers.
       const filteredHeaders = Object.fromEntries(
         Object.entries(proxyRes.headers).filter(([key]) => !new Set([
           'set-cookie', 'connection', 'keep-alive', 'proxy-authenticate',
           'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade',
           'x-powered-by',
         ]).has(key.toLowerCase())),
       );
      res.writeHead(proxyRes.statusCode ?? 502, filteredHeaders);
      proxyRes.pipe(res);
     });
    this.upstreamRequests.add(proxyReq);
    proxyReq.once('close', () => this.upstreamRequests.delete(proxyReq));

    proxyReq.on('error', (err) => {
      console.error(`[PreviewProxy] Error proxying to ${previewId}:`, err.message);
      if (!res.headersSent) {
        res.writeHead(502, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          error: { code: 'PROXY_ERROR', message: `Failed to connect to preview: ${err.message}` },
        }));
      }
    });

    // I7: Add timeout to prevent hung connections
    proxyReq.setTimeout(30000, () => {
      proxyReq.destroy();
      if (!res.headersSent) {
        res.writeHead(504, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          error: { code: 'PROXY_TIMEOUT', message: 'Preview request timed out' },
        }));
      }
    });

    req.pipe(proxyReq);
  }

  async start(): Promise<void> {
    return new Promise((resolve, reject) => {
      const onListening = () => {
        this.server.off('error', onError);
        console.log(`[PreviewProxy] Listening on ${this.config.host}:${this.config.port}`);
        resolve();
      };
      const onError = (err: Error) => {
        this.server.off('listening', onListening);
        reject(err);
      };
      this.server.once('error', onError);
      this.server.once('listening', onListening);
      this.server.listen(this.config.port, this.config.host);
    });
  }

  async stop(): Promise<void> {
    for (const request of this.upstreamRequests) {
      request.destroy();
    }
    for (const response of this.upstreamResponses) {
      response.destroy();
    }
    for (const socket of this.sockets) {
      socket.destroy();
    }
    return new Promise((resolve, reject) => {
      this.server.close((err) => err ? reject(err) : resolve());
    });
  }

  getPort(): number {
    const addr = this.server.address();
    if (addr && typeof addr === 'object') {
      return addr.port;
    }
    return this.config.port;
  }
}
