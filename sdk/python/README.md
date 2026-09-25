# BotConnector Python SDK boundary

This unpublished, dependency-free boundary calls the existing local BotConnector HTTP API. It does not contain an inference engine and is not available on PyPI.

```python
from botconnector import BotConnector
client = BotConnector()
print(client.models.list())
print(client.chat.create({"model": "local-model", "messages": [{"role": "user", "content": "Hello"}]}))
```
