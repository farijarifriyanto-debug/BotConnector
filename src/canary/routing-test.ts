export interface ProviderTestResult {
  provider: string;
  model: string;
  success: boolean;
  latencyMs: number;
  error?: string;
}

export interface TestSuiteResult {
  timestamp: string;
  primary: ProviderTestResult;
  hotStandby: ProviderTestResult | null;
  freeFallback: ProviderTestResult;
  overallSuccess: boolean;
  totalDurationMs: number;
}

export class RoutingTester {
  private readonly primaryProvider = 'bc-mistral/mistral-medium-latest';
  private readonly freeFallbackProvider = 'opencode/nemotron-3-ultra-free';
  private readonly testPrompt = 'Reply with exactly: OK';

  // HTTP route through the running OpenCode server (the production path).
  // Mirrors MainWindow.OpenCodeDirect.cs: create session -> send message.
  async testHttpRoute(
    baseUrl: string,
    providerID: string,
    modelID: string,
    username?: string,
    password?: string,
  ): Promise<ProviderTestResult> {
    const startTime = Date.now();
    const base = baseUrl.replace(/\/+$/, '');
    const auth =
      username && password
        ? 'Basic ' + Buffer.from(`${username}:${password}`).toString('base64')
        : undefined;

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (auth) headers['Authorization'] = auth;

    try {
      const createRes = await fetch(`${base}/session`, {
        method: 'POST',
        headers,
        body: '{}',
      });
      if (!createRes.ok) {
        throw new Error(`create session HTTP ${createRes.status}`);
      }
      const session = (await createRes.json()) as { id?: string };
      if (!session.id) throw new Error('no session id');

      const msgRes = await fetch(
        `${base}/session/${encodeURIComponent(session.id)}/message`,
        {
          method: 'POST',
          headers,
          body: JSON.stringify({
            model: { providerID, modelID },
            parts: [{ type: 'text', text: this.testPrompt }],
          }),
        },
      );
      if (!msgRes.ok) {
        throw new Error(`message HTTP ${msgRes.status}`);
      }
      const body = (await msgRes.json()) as {
        info?: { finish?: string; providerID?: string; modelID?: string };
        parts?: { type?: string; text?: string }[];
      };

      const text = (body.parts ?? [])
        .filter((p) => p.type === 'text')
        .map((p) => p.text ?? '')
        .join('\n')
        .trim();

      if (body.info?.finish !== 'stop') {
        throw new Error(`finish=${body.info?.finish ?? 'unknown'}`);
      }
      if (!/OK/.test(text)) {
        throw new Error(`unexpected reply: ${text}`);
      }

      return {
        provider: providerID,
        model: modelID,
        success: true,
        latencyMs: Date.now() - startTime,
      };
    } catch (error) {
      return {
        provider: providerID,
        model: modelID,
        success: false,
        latencyMs: Date.now() - startTime,
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }

  async testProvider(provider: string): Promise<ProviderTestResult> {
    const startTime = Date.now();
    try {
      const { execSync } = await import('node:child_process');
      const env = {
        ...process.env,
        MISTRAL_API_KEY: process.env.MISTRAL_API_KEY || '',
        GROQ_API_KEY: process.env.GROQ_API_KEY || '',
      };
      
      execSync(`opencode run -m ${provider} "${this.testPrompt}"`, {
        encoding: 'utf-8',
        timeout: 60000,
        env,
      });

      return {
        provider: provider.split('/')[0],
        model: provider.split('/')[1],
        success: true,
        latencyMs: Date.now() - startTime,
      };
    } catch (error) {
      return {
        provider: provider.split('/')[0],
        model: provider.split('/')[1],
        success: false,
        latencyMs: Date.now() - startTime,
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }

  async runFullTestSuite(): Promise<TestSuiteResult> {
    const startTime = Date.now();
    const timestamp = new Date().toISOString();

    const primary = await this.testProvider(this.primaryProvider);
    const freeFallback = await this.testProvider(this.freeFallbackProvider);

    const hotStandby: ProviderTestResult | null = null;

    const overallSuccess = primary.success && freeFallback.success;

    return {
      timestamp,
      primary,
      hotStandby,
      freeFallback,
      overallSuccess,
      totalDurationMs: Date.now() - startTime,
    };
  }
}