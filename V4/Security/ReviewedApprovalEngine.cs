using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace BotConnector.Desktop.V4.Security;

public sealed class ReviewedApprovalEngine
{
    private readonly RiskClassifier _classifier;
    private readonly SessionApprovalStore _sessions;
    private readonly IApprovalPrompt _prompt;

    public ReviewedApprovalEngine(
        RiskClassifier classifier,
        SessionApprovalStore sessions,
        IApprovalPrompt prompt)
    {
        _classifier = classifier;
        _sessions = sessions;
        _prompt = prompt;
    }

    public RiskClassifier Classifier =>
        _classifier;

    public async Task<bool> AuthorizeToolAsync(
        string toolName,
        IReadOnlyDictionary<string,string> arguments,
        CancellationToken cancellationToken)
    {
        var risk =
            _classifier.ClassifyTool(
                toolName,
                arguments);

        if (risk.Decision == RiskDecision.Deny)
            return false;

        if (risk.Decision == RiskDecision.Allow)
            return true;

        if (_sessions.IsApproved(
            risk.Category))
            return true;

        arguments.TryGetValue(
            "command",
            out var command);

        arguments.TryGetValue(
            "path",
            out var path);

        arguments.TryGetValue(
            "destination",
            out var destination);

        var target =
            destination ??
            path;

        var approval =
            await _prompt.AskAsync(
                new ApprovalRequest(
                    Guid.NewGuid().ToString("N"),
                    "BotConnector membutuhkan izin",
                    risk.Summary,
                    risk.NormalizedCommand ??
                    command,
                    target,
                    risk.Category),
                cancellationToken);

        if (approval ==
            UserApproval.AllowSession)
        {
            _sessions.ApproveForSession(
                risk.Category);

            return true;
        }

        return approval ==
            UserApproval.AllowOnce;
    }
}