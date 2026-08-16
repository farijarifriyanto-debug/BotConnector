using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

namespace BotConnector.Auth;

public sealed class TokenStore
{
    private readonly string _path;

    public TokenStore()
    {
        var root = Path.Combine(
            Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData),
            "BotConnector",
            "DesktopAuth");

        Directory.CreateDirectory(root);

        _path = Path.Combine(
            root,
            "tokens.dat");
    }

    public bool Exists =>
        File.Exists(_path);

    public void Save(
        AuthTokenPair pair)
    {
        var json =
            JsonSerializer.Serialize(pair);

        var plain =
            Encoding.UTF8.GetBytes(json);

        var encrypted =
            Protect(plain);

        File.WriteAllBytes(
            _path,
            encrypted);
    }

    public AuthTokenPair? Load()
    {
        if (!File.Exists(_path))
            return null;

        var encrypted =
            File.ReadAllBytes(_path);

        var plain =
            Unprotect(encrypted);

        return JsonSerializer.Deserialize<AuthTokenPair>(
            Encoding.UTF8.GetString(plain));
    }

    public void Clear()
    {
        if (File.Exists(_path))
            File.Delete(_path);
    }

    private static byte[] Protect(
        byte[] input)
    {
        return Crypt(
            input,
            protect: true);
    }

    private static byte[] Unprotect(
        byte[] input)
    {
        return Crypt(
            input,
            protect: false);
    }

    private static byte[] Crypt(
        byte[] input,
        bool protect)
    {
        var inputBlob = default(DATA_BLOB);
        var outputBlob = default(DATA_BLOB);

        try
        {
            inputBlob.cbData =
                input.Length;

            inputBlob.pbData =
                Marshal.AllocHGlobal(
                    input.Length);

            Marshal.Copy(
                input,
                0,
                inputBlob.pbData,
                input.Length);

            bool ok;

            if (protect)
            {
                ok = CryptProtectData(
                    ref inputBlob,
                    "BotConnector Desktop Auth",
                    IntPtr.Zero,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    CRYPTPROTECT_UI_FORBIDDEN,
                    out outputBlob);
            }
            else
            {
                ok = CryptUnprotectData(
                    ref inputBlob,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    CRYPTPROTECT_UI_FORBIDDEN,
                    out outputBlob);
            }

            if (!ok)
            {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error());
            }

            var result =
                new byte[outputBlob.cbData];

            Marshal.Copy(
                outputBlob.pbData,
                result,
                0,
                outputBlob.cbData);

            return result;
        }
        finally
        {
            if (inputBlob.pbData != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(
                    inputBlob.pbData);
            }

            if (outputBlob.pbData != IntPtr.Zero)
            {
                LocalFree(
                    outputBlob.pbData);
            }
        }
    }

    private const int
        CRYPTPROTECT_UI_FORBIDDEN = 0x1;

    [StructLayout(
        LayoutKind.Sequential)]
    private struct DATA_BLOB
    {
        public int cbData;
        public IntPtr pbData;
    }

    [DllImport(
        "crypt32.dll",
        SetLastError = true,
        CharSet = CharSet.Unicode)]
    private static extern bool CryptProtectData(
        ref DATA_BLOB pDataIn,
        string? szDataDescr,
        IntPtr pOptionalEntropy,
        IntPtr pvReserved,
        IntPtr pPromptStruct,
        int dwFlags,
        out DATA_BLOB pDataOut);

    [DllImport(
        "crypt32.dll",
        SetLastError = true,
        CharSet = CharSet.Unicode)]
    private static extern bool CryptUnprotectData(
        ref DATA_BLOB pDataIn,
        IntPtr ppszDataDescr,
        IntPtr pOptionalEntropy,
        IntPtr pvReserved,
        IntPtr pPromptStruct,
        int dwFlags,
        out DATA_BLOB pDataOut);

    [DllImport(
        "kernel32.dll",
        SetLastError = true)]
    private static extern IntPtr LocalFree(
        IntPtr hMem);
}
