using System.Threading;
using System.Threading.Tasks;

namespace BotConnector.Desktop.V4.Security;

public sealed class WpfApprovalPrompt :
    IApprovalPrompt
{
    public Task<UserApproval> AskAsync(
        ApprovalRequest request,
        CancellationToken cancellationToken)
    {
        var tcs =
            new TaskCompletionSource<UserApproval>(
                TaskCreationOptions.RunContinuationsAsynchronously);

        var dispatcher =
            System.Windows.Application.Current?.Dispatcher;

        if (dispatcher is null)
        {
            tcs.SetResult(
                UserApproval.Deny);

            return tcs.Task;
        }

        dispatcher.Invoke(() =>
        {
            cancellationToken.ThrowIfCancellationRequested();

            var window =
                new System.Windows.Window
                {
                    Title =
                        "BotConnector — Izin diperlukan",

                    Width = 640,
                    Height = 460,

                    WindowStartupLocation =
                        System.Windows.WindowStartupLocation.CenterOwner,

                    ResizeMode =
                        System.Windows.ResizeMode.CanResize,

                    ShowInTaskbar = false
                };

            if (
                System.Windows.Application.Current?.MainWindow
                is System.Windows.Window owner
                &&
                owner != window
            )
            {
                window.Owner = owner;
            }

            var root =
                new System.Windows.Controls.DockPanel
                {
                    Margin =
                        new System.Windows.Thickness(22)
                };

            var buttons =
                new System.Windows.Controls.StackPanel
                {
                    Orientation =
                        System.Windows.Controls.Orientation.Horizontal,

                    HorizontalAlignment =
                        System.Windows.HorizontalAlignment.Right,

                    Margin =
                        new System.Windows.Thickness(
                            0,
                            18,
                            0,
                            0)
                };

            System.Windows.Controls.DockPanel.SetDock(
                buttons,
                System.Windows.Controls.Dock.Bottom);

            var content =
                new System.Windows.Controls.StackPanel();

            content.Children.Add(
                new System.Windows.Controls.TextBlock
                {
                    Text =
                        request.Title,

                    FontSize = 20,

                    FontWeight =
                        System.Windows.FontWeights.SemiBold,

                    TextWrapping =
                        System.Windows.TextWrapping.Wrap
                });

            content.Children.Add(
                new System.Windows.Controls.TextBlock
                {
                    Text =
                        request.Description,

                    Margin =
                        new System.Windows.Thickness(
                            0,
                            12,
                            0,
                            12),

                    TextWrapping =
                        System.Windows.TextWrapping.Wrap
                });

            content.Children.Add(
                new System.Windows.Controls.TextBlock
                {
                    Text =
                        $"Kategori: {request.Category}",

                    FontWeight =
                        System.Windows.FontWeights.SemiBold
                });

            if (!string.IsNullOrWhiteSpace(
                    request.Target))
            {
                content.Children.Add(
                    new System.Windows.Controls.TextBlock
                    {
                        Text =
                            $"Target: {request.Target}",

                        Margin =
                            new System.Windows.Thickness(
                                0,
                                6,
                                0,
                                0),

                        TextWrapping =
                            System.Windows.TextWrapping.Wrap
                    });
            }

            if (!string.IsNullOrWhiteSpace(
                    request.Command))
            {
                content.Children.Add(
                    new System.Windows.Controls.TextBlock
                    {
                        Text =
                            "Command:",

                        FontWeight =
                            System.Windows.FontWeights.SemiBold,

                        Margin =
                            new System.Windows.Thickness(
                                0,
                                14,
                                0,
                                4)
                    });

                content.Children.Add(
                    new System.Windows.Controls.TextBox
                    {
                        Text =
                            request.Command,

                        IsReadOnly =
                            true,

                        TextWrapping =
                            System.Windows.TextWrapping.Wrap,

                        AcceptsReturn =
                            true,

                        MaxHeight =
                            150,

                        VerticalScrollBarVisibility =
                            System.Windows.Controls.ScrollBarVisibility.Auto
                    });
            }

            var deny =
                new System.Windows.Controls.Button
                {
                    Content =
                        "Tolak",

                    MinWidth =
                        95,

                    Margin =
                        new System.Windows.Thickness(6)
                };

            var once =
                new System.Windows.Controls.Button
                {
                    Content =
                        "Izinkan sekali",

                    MinWidth =
                        120,

                    Margin =
                        new System.Windows.Thickness(6)
                };

            var session =
                new System.Windows.Controls.Button
                {
                    Content =
                        "Izinkan sesi ini",

                    MinWidth =
                        130,

                    Margin =
                        new System.Windows.Thickness(6)
                };

            deny.Click += (_,__) =>
            {
                tcs.TrySetResult(
                    UserApproval.Deny);

                window.Close();
            };

            once.Click += (_,__) =>
            {
                tcs.TrySetResult(
                    UserApproval.AllowOnce);

                window.Close();
            };

            session.Click += (_,__) =>
            {
                tcs.TrySetResult(
                    UserApproval.AllowSession);

                window.Close();
            };

            window.Closed += (_,__) =>
            {
                tcs.TrySetResult(
                    UserApproval.Deny);
            };

            buttons.Children.Add(
                deny);

            buttons.Children.Add(
                once);

            buttons.Children.Add(
                session);

            root.Children.Add(
                buttons);

            root.Children.Add(
                content);

            window.Content =
                root;

            window.ShowDialog();
        });

        return tcs.Task;
    }
}