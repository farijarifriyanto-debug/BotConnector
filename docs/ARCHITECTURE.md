# Architecture 0.4

```text
Hugging Face Hub
   │
   ├─ /api/models                 search / trending / metadata
   ├─ /api/models/:repo/tree      exact GGUF files and sizes
   └─ /resolve/...                file download
   │
   ▼
BotConnector desktop main process
   ├─ HF adapter
   ├─ capability classifier
   ├─ hardware fit estimator
   ├─ download manager (.part / Range / SHA256)
   ├─ installed-model scanner
   ├─ managed llama.cpp installer
   └─ runtime process manager
             │
             ▼
       llama-server
       127.0.0.1:11435
             │
      ┌──────┴────────┐
      ▼               ▼
 desktop chat     developer clients
 streaming        OpenAI-compatible
```

Cloud is a separate future path:

```text
Desktop / API client
       │
       ▼
BotConnector Cloud Gateway
 auth · credit · metering · rate limit · router · failover
       │
       ├─ direct flagship provider API
       └─ self-hosted GPU pools
```

The local model catalog is not a hard-coded list. A small offline fallback registry may remain for degraded/offline UX, but normal discovery is live Hugging Face.
