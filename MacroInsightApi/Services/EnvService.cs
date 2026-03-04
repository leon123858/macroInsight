using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Serialization;
using Python.Runtime;

namespace MacroInsightApi.Services;

public class EnvService
{
    private bool _pythonInitialized = false;

    public async Task InitializePythonEngineAsync()
    {
        if (_pythonInitialized) return;

        // Python.Included Setup
        await Python.Included.Installer.SetupPython();
        
        PythonEngine.Initialize();
        
        _pythonInitialized = true;
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

        var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        var programFilesX86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
        
        // Scan for LLVM
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

        // Scan for DS-5
        var ds5Dirs = new List<string>();
        if (Directory.Exists(programFiles))
        {
            ds5Dirs.AddRange(Directory.GetDirectories(programFiles, "DS-5*"));
        }
        if (Directory.Exists(programFilesX86))
        {
            ds5Dirs.AddRange(Directory.GetDirectories(programFilesX86, "DS-5*"));
        }

        foreach (var dsDir in ds5Dirs)
        {
            var binDir = Path.Combine(dsDir, "bin");
            if (Directory.Exists(binDir))
            {
                var ds5Name = new DirectoryInfo(dsDir).Name;
                if (File.Exists(Path.Combine(binDir, "armclang.exe")))
                {
                    results.Add(new CompilerInfo(ds5Name, $"{ds5Name} (armclang)", binDir));
                }
                else if (File.Exists(Path.Combine(binDir, "armcc.exe")))
                {
                    results.Add(new CompilerInfo(ds5Name, $"{ds5Name} (armcc)", binDir));
                }
            }
        }

        // If 'clang' is just in PATH, we add it too, checking if it differs.
        var systemClang = RunCommand("clang", "--version");
        if (systemClang != null)
        {
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

            // Dynamically set ARM_PRODUCT_PATH for DS-5 installations
            if (binPath.Contains("DS-5", StringComparison.OrdinalIgnoreCase))
            {
                var ds5Home = Directory.GetParent(binPath)?.FullName;
                if (!string.IsNullOrEmpty(ds5Home))
                {
                    var mappingsPath = Path.Combine(ds5Home, "sw", "mappings");
                    Environment.SetEnvironmentVariable("ARM_PRODUCT_PATH", mappingsPath, EnvironmentVariableTarget.Process);
                }
            }
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


public record CmakeStatus(bool Available, string? Version);
public record CompilerInfo(string Name, string VersionInfo, string BinPath);
