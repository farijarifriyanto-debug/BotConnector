using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace BotConnector.Desktop.V4.Mcp;

public sealed record McpToolDescriptor(
    string Name,
    string? Description);

public interface IMcpTransport
{
    Task<IReadOnlyList<McpToolDescriptor>> ListToolsAsync(
        McpServerDefinition server,
        CancellationToken cancellationToken);

    Task<string> CallToolAsync(
        McpServerDefinition server,
        string toolName,
        IReadOnlyDictionary<string,object?> arguments,
        CancellationToken cancellationToken);
}