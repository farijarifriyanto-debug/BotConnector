# BotConnector TypeScript SDK boundary

This is a local-source SDK boundary for the existing BotConnector HTTP API. It is not published to npm and does not add a second inference engine.

```js
const { BotConnectorClient } = require('./sdk/typescript');
const client = new BotConnectorClient();
const models = await client.models.list();
const completion = await client.chat.create({model: 'local-model', messages: [{role: 'user', content: 'Hello'}]});
for await (const event of client.chat.stream({model: 'local-model', messages: [{role: 'user', content: 'Stream this'}]})) console.log(event);
```
