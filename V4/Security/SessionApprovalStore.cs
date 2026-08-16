using System;
using System.Collections.Generic;

namespace BotConnector.Desktop.V4.Security;

public sealed class SessionApprovalStore
{
    private readonly HashSet<RiskCategory> _approved =
        new();

    private readonly object _sync =
        new();

    public bool IsApproved(
        RiskCategory category)
    {
        lock (_sync)
            return _approved.Contains(category);
    }

    public void ApproveForSession(
        RiskCategory category)
    {
        lock (_sync)
            _approved.Add(category);
    }

    public void Clear()
    {
        lock (_sync)
            _approved.Clear();
    }
}