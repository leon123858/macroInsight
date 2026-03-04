using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace MacroInsightApi.Services;

public class EnvService
{
    public PythonStatus CheckPython()
    {
        // Check for uv first
        var uvVersion = RunCommand("uv", "run python --version");
        if (uvVersion != null)
        {
            return new PythonStatus(true, "uv", uvVersion.Trim(), null);
        }

        // Fallback to python
        var pythonVersion = RunCommand("python", "--version");
        if (pythonVersion != null)
        {
            return new PythonStatus(true, "python", pythonVersion.Trim(), null);
        }

        return new PythonStatus(false, null, null, 
            "Python is required but not found. We recommend installing 'uv' (https://github.com/astral-sh/uv) or standard Python 3.10+ from https://www.python.org/downloads/. Please ensure it is added to your system PATH.");
    }

    public CmakeStatus CheckCmake()
    {
        var cmakeOutput = RunCommand("cmake", "--version");
        if (cmakeOutput != null)
        {
            var firstLine = cmakeOutput.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries).FirstOrDefault() ?? "";
            return new CmakeStatus(true, firstLine);
        }
        return new CmakeStatus(false, null);
    }

    public List<CompilerInfo> ScanCompilers()
    {
        var results = new List<CompilerInfo>();

        // For now, specifically looking for LLVM on Windows.
        var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        var llvmDir = Path.Combine(programFiles, "LLVM");

        if (Directory.Exists(llvmDir))
        {
            var binDir = Path.Combine(llvmDir, "bin");
            if (Directory.Exists(binDir) && File.Exists(Path.Combine(binDir, "clang.exe")))
            {
                var versionOutput = RunCommand(Path.Combine(binDir, "clang.exe"), "--version");
                var firstLine = versionOutput?.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries).FirstOrDefault() ?? "LLVM Unknown Version";
                results.Add(new CompilerInfo("LLVM", firstLine, binDir));
            }
        }

        // If 'clang' is just in PATH, we add it too, checking if it differs.
        var systemClang = RunCommand("clang", "--version");
        if (systemClang != null)
        {
            // We just add a reference to "System PATH LLVM". If the user wants to use whatever is globally installed.
            var firstLine = systemClang.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries).FirstOrDefault() ?? "System Clang";
            results.Add(new CompilerInfo("System PATH Compiler", firstLine, ""));
        }

        return results;
    }

    public bool SelectCompiler(string binPath)
    {
        var pathEnv = Environment.GetEnvironmentVariable("PATH", EnvironmentVariableTarget.Process) ?? "";
        
        // Remove existing if we added it before, or just prepend. Prepending is simpler; it overrides later entries.
        if (!string.IsNullOrWhiteSpace(binPath))
        {
            var newPath = $"{binPath};{pathEnv}";
            Environment.SetEnvironmentVariable("PATH", newPath, EnvironmentVariableTarget.Process);
        }
        
        return true; // Simple success
    }

    private string? RunCommand(string fileName, string arguments)
    {
        try
        {
            var startInfo = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };

            using var process = Process.Start(startInfo);
            if (process == null) return null;

            process.WaitForExit(3000);
            if (process.ExitCode == 0)
            {
                var res = process.StandardOutput.ReadToEnd();
                if (string.IsNullOrWhiteSpace(res)) 
                    res = process.StandardError.ReadToEnd(); // python --version sometimes writes to stderr in older versions
                return res;
            }
            return null;
        }
        catch
        {
            return null;
        }
    }
}

public record PythonStatus(bool Available, string? Executable, string? Version, string? InstallationGuide);
public record CmakeStatus(bool Available, string? Version);
public record CompilerInfo(string Name, string VersionInfo, string BinPath);
