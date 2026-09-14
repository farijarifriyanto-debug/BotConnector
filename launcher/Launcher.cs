// BotConnector.exe — the whole Portable Web App launcher. Deliberately tiny:
// its only job is to hidden-launch botconnector-core.exe (the Node SEA) with
// the "ui" command and exit. All real logic (HTTP server, security, browser
// auto-open, single-instance handling) lives in the Core, which already
// works and is already tested; duplicating any of that here would be exactly
// the kind of second, divergent implementation this project avoids.
//
// Compiled with /target:winexe, which sets the PE header's Subsystem to
// Windows GUI (not Console) — Windows never allocates a console window for
// a winexe process, so this launcher is silent by construction, with no
// FreeConsole()/AllocConsole() trickery needed.
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

static class Launcher {
    [STAThread]
    static void Main() {
        string exeDir = Path.GetDirectoryName(Application.ExecutablePath);
        string corePath = Path.Combine(exeDir, "botconnector-core.exe");
        if (!File.Exists(corePath)) {
            MessageBox.Show(
                "botconnector-core.exe was not found next to BotConnector.exe.\n\nRe-extract the portable BotConnector folder and keep both files together.",
                "BotConnector", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        var psi = new ProcessStartInfo {
            FileName = corePath,
            Arguments = "ui",
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            WorkingDirectory = exeDir,
        };
        try {
            Process.Start(psi);
        } catch (Exception ex) {
            MessageBox.Show(
                "Failed to start BotConnector:\n\n" + ex.Message,
                "BotConnector", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
