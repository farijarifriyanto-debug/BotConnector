using System;

namespace BotConnector.Desktop.V4.Mcp;

public sealed class McpPolicy
{
    public bool IsTransportAllowed(string transport)
    {
        return transport.Equals(
                   "stdio",
                   StringComparison.OrdinalIgnoreCase)
               ||
               transport.Equals(
                   "streamable-http",
                   StringComparison.OrdinalIgnoreCase);
    }

    public bool IsEndpointAllowed(
        McpServerDefinition server)
    {
        if (!IsTransportAllowed(server.Transport))
            return false;

        if (server.Transport.Equals(
            "stdio",
            StringComparison.OrdinalIgnoreCase))
            return true;

        if (!Uri.TryCreate(
            server.Endpoint,
            UriKind.Absolute,
            out var uri))
            return false;

        if (uri.Scheme != Uri.UriSchemeHttp &&
            uri.Scheme != Uri.UriSchemeHttps)
            return false;

        return true;
    }
}