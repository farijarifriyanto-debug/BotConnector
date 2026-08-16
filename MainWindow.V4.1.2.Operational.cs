using System;
using System.Linq;
using System.Threading;
using System.Windows;

namespace BotConnector.Desktop;

public partial class MainWindow
{
    private static Mutex? _v412ProductionMutex;
    private static bool _v412OwnsProductionMutex;

    private static bool V412SmokeMode =>
        Environment.GetCommandLineArgs()
            .Skip(1)
            .Any(
                arg =>
                    string.Equals(
                        arg,
                        "--smoke-test",
                        StringComparison.OrdinalIgnoreCase))
        ||
        string.Equals(
            Environment.GetEnvironmentVariable(
                "BOTCONNECTOR_SMOKE_TEST"),
            "1",
            StringComparison.Ordinal);

    private bool V412InitializeOperationalMode()
    {
        if (V412SmokeMode)
        {
            return true;
        }

        if (_v412ProductionMutex is not null)
        {
            return _v412OwnsProductionMutex;
        }

        bool createdNew;

        _v412ProductionMutex =
            new Mutex(
                initiallyOwned: true,
                name:
                    "Local\\BotConnector.Desktop.Production." +
                    Environment.UserName,
                createdNew: out createdNew);

        _v412OwnsProductionMutex =
            createdNew;

        if (!createdNew)
        {
            // Do not show a modal dialog here.
            // A modal MessageBox keeps the second process alive and makes
            // automated single-instance acceptance look like a failure.
            return false;
        }

        return true;
    }

    private bool V412ShouldRunDesktopBridge =>
        !V412SmokeMode;

    private void V412SetBridgeSessionState(
        bool signedIn,
        string text)
    {
        Dispatcher.BeginInvoke(
            new Action(
                () =>
                {
                    AuthStatusText.Text =
                        text;

                    SignInButton.Visibility =
                        signedIn
                            ? Visibility.Collapsed
                            : Visibility.Visible;

                    SignInButton.IsEnabled =
                        true;
                }));
    }
}