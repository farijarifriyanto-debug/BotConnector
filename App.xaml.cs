using System;
using System.IO;
using System.Windows;
using System.Windows.Threading;

namespace BotConnector.Desktop;

public partial class App : System.Windows.Application
{
    public App()
    {
        // Resilience: log unexpected errors and keep the window alive instead
        // of hard-crashing to the desktop ("sudden shutdown").
        DispatcherUnhandledException += OnDispatcherUnhandledException;
        AppDomain.CurrentDomain.UnhandledException += OnDomainUnhandledException;
    }

    private void OnDispatcherUnhandledException(
        object sender,
        DispatcherUnhandledExceptionEventArgs e)
    {
        LogCrash("Dispatcher", e.Exception);
        e.Handled = true;
    }

    private void OnDomainUnhandledException(
        object sender,
        UnhandledExceptionEventArgs e)
    {
        if (e.ExceptionObject is Exception ex)
            LogCrash("Domain", ex);
    }

    private static void LogCrash(string source, Exception ex)
    {
        try
        {
            string dir = Path.Combine(
                Environment.GetFolderPath(
                    Environment.SpecialFolder.LocalApplicationData),
                "BotConnector",
                "Logs");

            Directory.CreateDirectory(dir);

            File.AppendAllText(
                Path.Combine(dir, "crash.log"),
                DateTime.Now.ToString("o") +
                " [" + source + "] " +
                ex + Environment.NewLine + Environment.NewLine);
        }
        catch
        {
        }
    }
}
