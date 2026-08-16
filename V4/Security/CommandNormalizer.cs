using System;
using System.Linq;
using System.Text.RegularExpressions;

namespace BotConnector.Desktop.V4.Security;

public static class CommandNormalizer
{
    public static string Normalize(string? command)
    {
        if (string.IsNullOrWhiteSpace(command))
            return string.Empty;

        var value = command
            .Replace("\r", " ")
            .Replace("\n", " ")
            .Trim();

        value = Regex.Replace(
            value,
            @"\s+",
            " ");

        return value;
    }

    public static string Lower(string? command) =>
        Normalize(command)
            .ToLowerInvariant();
}