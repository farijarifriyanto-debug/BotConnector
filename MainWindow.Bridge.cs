using System;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;

namespace BotConnector.Desktop;

// V5.4 Hermes local bridge manager.
// The Hermes brain lives on the VPS; the desktop reaches it via a local
// forward tunnel  ssh -L 127.0.0.1:<localPort>:<remote>  botadmin@vps.
// This class starts that tunnel on demand, avoids duplicates, and tears it
// down on exit. It never modifies the VPS and never touches SSH keys.
public partial class MainWindow
{
    private Process? _hermesBridgeProcess;
    private bool _hermesBridgeStarting;

    private string HermesSshTarget =>
        Environment.GetEnvironmentVariable("BOTCONNECTOR_HERMES_SSH_TARGET")
        ?? "botadmin@103.58.101.207";

    private string HermesRemoteEndpoint =>
        Environment.GetEnvironmentVariable("BOTCONNECTOR_HERMES_REMOTE")
        ?? "127.0.0.1:18270";

    private string HermesSshKeyPath =>
        Environment.GetEnvironmentVariable("BOTCONNECTOR_HERMES_SSH_KEY")
        ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".ssh",
            "botconnector_llm_ed25519");

    private int HermesLocalPort()
    {
        try { return new Uri(_v4Hermes.BaseUrl).Port; }
        catch { return 18642; }
    }

    // Idempotent: no-op if the port already listens (ours OR an externally
    // started tunnel) or if our tunnel process is already alive.
    private async Task<bool> V5EnsureHermesBridgeAsync()
    {
        if (await V4HermesListenerUpAsync())
            return true;

        if (_hermesBridgeStarting)
            return false;

        if (_hermesBridgeProcess is { HasExited: false })
            return false;

        _hermesBridgeStarting = true;

        try
        {
            int localPort = HermesLocalPort();
            string keyPath = HermesSshKeyPath;

            if (!File.Exists(keyPath))
            {
                AppendTerminal(
                    "[Bridge] SSH key not found: " + keyPath);
                return false;
            }

            string sshExe = ResolveSshExe();

            AppendTerminal(
                "[Bridge] Starting Hermes tunnel 127.0.0.1:" +
                localPort + " -> " + HermesRemoteEndpoint +
                " via " + HermesSshTarget + " (" + sshExe + ")");

            // Up to 3 attempts: a fresh listener port can briefly be in
            // TIME_WAIT which makes ExitOnForwardFailure drop the tunnel.
            for (int attempt = 1; attempt <= 3; attempt++)
            {
                var psi = new ProcessStartInfo
                {
                    FileName = sshExe,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    // Do NOT redirect: an unread pipe can stall ssh, and we
                    // detect success by the listener coming up, not stdout.
                    RedirectStandardOutput = false,
                    RedirectStandardError = false
                };

                foreach (var a in new[]
                {
                    "-N",
                    "-L", "127.0.0.1:" + localPort + ":" + HermesRemoteEndpoint,
                    "-i", keyPath,
                    "-o", "BatchMode=yes",
                    "-o", "ExitOnForwardFailure=yes",
                    "-o", "ServerAliveInterval=30",
                    "-o", "ServerAliveCountMax=3",
                    "-o", "ConnectTimeout=12",
                    "-o", "StrictHostKeyChecking=accept-new",
                    HermesSshTarget
                })
                {
                    psi.ArgumentList.Add(a);
                }

                var proc = new Process
                {
                    StartInfo = psi,
                    EnableRaisingEvents = true
                };

                proc.Start();
                _hermesBridgeProcess = proc;

                bool up = false;
                for (int i = 0; i < 16; i++)
                {
                    await Task.Delay(500);

                    if (proc.HasExited)
                        break;

                    if (await V4HermesListenerUpAsync())
                    {
                        up = true;
                        break;
                    }
                }

                if (up)
                {
                    AppendTerminal("[Bridge] Hermes tunnel is up.");
                    return true;
                }

                AppendTerminal(
                    "[Bridge] attempt " + attempt +
                    " did not bring the tunnel up" +
                    (proc.HasExited ? " (ssh exited)" : "") + ".");

                try { if (!proc.HasExited) proc.Kill(true); } catch { }

                if (attempt < 3)
                    await Task.Delay(1500);
            }

            return false;
        }
        catch (Exception ex)
        {
            AppendTerminal("[Bridge] error: " + ex.Message);
            return false;
        }
        finally
        {
            _hermesBridgeStarting = false;
        }
    }

    private string ResolveSshExe()
    {
        try
        {
            string sys = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.System),
                "OpenSSH",
                "ssh.exe");

            if (File.Exists(sys))
                return sys;
        }
        catch
        {
        }

        return "ssh.exe";
    }

    private void V5StopHermesBridge()
    {
        try
        {
            if (_hermesBridgeProcess is { HasExited: false })
                _hermesBridgeProcess.Kill(entireProcessTree: true);
        }
        catch
        {
        }
        _hermesBridgeProcess = null;
    }
}
