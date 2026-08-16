using System.Threading;
using System.Threading.Tasks;

namespace BotConnector.Desktop.V4.Security;

public interface IApprovalPrompt
{
    Task<UserApproval> AskAsync(
        ApprovalRequest request,
        CancellationToken cancellationToken);
}