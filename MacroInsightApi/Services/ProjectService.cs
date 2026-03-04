using System.Diagnostics;

namespace MacroInsightApi.Services;

public class ProjectService
{
    private readonly EnvService _envService;

    public ProjectService(EnvService envService)
    {
        _envService = envService;
    }

    public bool CheckCProject(string targetDirectory)
    {
        if (string.IsNullOrWhiteSpace(targetDirectory)) return false;
        var cprojPath = Path.Combine(targetDirectory, ".cproject");
        return File.Exists(cprojPath);
    }

    public List<string> ListConfigs(string targetDirectory)
    {
        var cprojPath = Path.Combine(targetDirectory, ".cproject");
        if (!File.Exists(cprojPath)) return new List<string>();

        var cprojectToCmakePath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", "..", "..", "..", "cproject_to_cmake.py");
        if (!File.Exists(cprojectToCmakePath))
        {
            cprojectToCmakePath = Path.GetFullPath(Path.Combine(Environment.CurrentDirectory, "..", "cproject_to_cmake.py"));
        }

        var pyStatus = _envService.CheckPython();
        if (!pyStatus.Available) throw new Exception("Python is not available.");

        string fileName;
        string argsPrefix;

        if (pyStatus.Executable == "uv")
        {
            fileName = "uv";
            argsPrefix = $"run python \"{cprojectToCmakePath}\"";
        }
        else
        {
            fileName = "python";
            argsPrefix = $"\"{cprojectToCmakePath}\"";
        }

        var arguments = $"{argsPrefix} --cproject \"{cprojPath}\" --list-configs";

        var (exitCode, stdout, stderr) = RunCommandWithOutput(fileName, arguments, targetDirectory);
        
        if (exitCode != 0) throw new Exception($"Failed to list configs: {stderr}");

        var lines = stdout.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
        var configs = new List<string>();
        foreach (var line in lines)
        {
            if (line.Trim().StartsWith("- "))
            {
                configs.Add(line.Trim().Substring(2).Trim());
            }
        }

        return configs;
    }

    public string GenerateConditions(string targetDirectory, string configName)
    {
        var cprojPath = Path.Combine(targetDirectory, ".cproject");
        var cmakeListsPath = Path.Combine(targetDirectory, "CMakeLists.txt");
        
        var cprojectToCmakePath = Path.GetFullPath(Path.Combine(Environment.CurrentDirectory, "..", "cproject_to_cmake.py"));
        var templatePath = Path.GetFullPath(Path.Combine(Environment.CurrentDirectory, "..", "cmake_template.txt"));
        var mainPyPath = Path.GetFullPath(Path.Combine(Environment.CurrentDirectory, "..", "main.py"));

        var pyStatus = _envService.CheckPython();
        if (!pyStatus.Available) throw new Exception("Python is not available.");

        string fileName = pyStatus.Executable == "uv" ? "uv" : "python";
        string argsPrefix = pyStatus.Executable == "uv" ? "run python" : "";

        // 1. Generate CMakeLists.txt if not exists
        if (!File.Exists(cmakeListsPath) && File.Exists(cprojPath))
        {
            var args = $"{argsPrefix} \"{cprojectToCmakePath}\" --cproject \"{cprojPath}\" --template \"{templatePath}\" --output \"{cmakeListsPath}\" --config \"{configName}\"";
            var (genExit, genOut, genErr) = RunCommandWithOutput(fileName, args.Trim(), targetDirectory);
            if (genExit != 0) throw new Exception($"cproject_to_cmake.py failed: {genErr}");
        }

        // 2. Run MacroInsight main.py
        var outXmlName = $"{configName}.conditions.xml";
        var outXmlPath = Path.Combine(targetDirectory, outXmlName);

        var runArgs = $"{argsPrefix} \"{mainPyPath}\" --repo-dir \"{targetDirectory}\" --output \"{outXmlPath}\" --output-format xml --clang clang".Trim();
        var (runExit, runOut, runErr) = RunCommandWithOutput(fileName, runArgs, targetDirectory);

        if (runExit != 0) throw new Exception($"MacroInsight execution failed: {runErr}\n{runOut}");

        if (!File.Exists(outXmlPath)) throw new Exception($"Expected output file not found: {outXmlPath}");

        return outXmlPath;
    }

    public void Cleanup(string targetDirectory, string configName)
    {
        var filesToDelete = new[]
        {
            Path.Combine(targetDirectory, "CMakeLists.txt"),
            Path.Combine(targetDirectory, "compile_commands.json"),
            Path.Combine(targetDirectory, $"{configName}.conditions.xml")
        };

        foreach (var file in filesToDelete)
        {
            if (File.Exists(file)) File.Delete(file);
        }

        var foldersToDelete = new[]
        {
            Path.Combine(targetDirectory, ".cmake"),
            Path.Combine(targetDirectory, "build"),
            Path.Combine(targetDirectory, "cmake-build-debug")
        };

        foreach (var folder in foldersToDelete)
        {
            if (Directory.Exists(folder)) Directory.Delete(folder, true);
        }
    }

    private (int exitCode, string stdout, string stderr) RunCommandWithOutput(string fileName, string arguments, string workingDir)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = fileName,
            Arguments = arguments,
            WorkingDirectory = workingDir,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true
        };

        using var process = Process.Start(startInfo);
        if (process == null) return (-1, "", "Failed to start process.");

        process.WaitForExit();
        return (process.ExitCode, process.StandardOutput.ReadToEnd(), process.StandardError.ReadToEnd());
    }
}
