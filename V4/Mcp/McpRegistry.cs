using System;
using System.Collections.Generic;
using System.Linq;

namespace BotConnector.Desktop.V4.Mcp;

public sealed record McpServerDefinition(
    string Id,
    string Transport,
    string Endpoint,
    bool Enabled);

public sealed class McpRegistry
{
    private readonly Dictionary<string,McpServerDefinition> _servers =
        new(StringComparer.OrdinalIgnoreCase);

    public void Register(McpServerDefinition server)
    {
        if (string.IsNullOrWhiteSpace(server.Id))
            throw new ArgumentException("MCP server id required.");

        _servers[server.Id] = server;
    }

    public bool Remove(string id) =>
        _servers.Remove(id);

    public IReadOnlyList<McpServerDefinition> List() =>
        _servers.Values
            .OrderBy(x => x.Id)
            .ToArray();
}