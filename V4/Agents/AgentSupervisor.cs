using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace BotConnector.Desktop.V4.Agents;

public sealed record AgentTask(
    string Id,
    Func<CancellationToken,Task<string>> Execute);

public sealed record AgentTaskResult(
    string Id,
    bool Success,
    string Output,
    string? Error);

public sealed class AgentSupervisor
{
    public async Task<IReadOnlyList<AgentTaskResult>> RunParallelAsync(
        IEnumerable<AgentTask> jobs,
        int maxParallelism,
        CancellationToken cancellationToken)
    {
        if (maxParallelism < 1)
            throw new ArgumentOutOfRangeException(nameof(maxParallelism));

        using var gate = new SemaphoreSlim(maxParallelism);

        var tasks = jobs.Select(async job =>
        {
            await gate.WaitAsync(cancellationToken);

            try
            {
                try
                {
                    var output = await job.Execute(cancellationToken);

                    return new AgentTaskResult(
                        job.Id,
                        true,
                        output,
                        null);
                }
                catch (Exception ex)
                {
                    return new AgentTaskResult(
                        job.Id,
                        false,
                        string.Empty,
                        ex.Message);
                }
            }
            finally
            {
                gate.Release();
            }
        });

        return await Task.WhenAll(tasks);
    }
}