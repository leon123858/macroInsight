using System.Diagnostics;
using Python.Runtime;

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

    private string RunPythonScript(string scriptPath, string targetDirectory, string[] args)
    {
        using (Py.GIL())
        {
            dynamic sys = Py.Import("sys");
            dynamic io = Py.Import("io");
            dynamic os = Py.Import("os");
            
            var originalArgv = sys.argv;
            var oldStdout = sys.stdout;
            var oldStderr = sys.stderr;
            var oldDir = os.getcwd();

            dynamic stdoutString = io.StringIO();
            dynamic stderrString = io.StringIO();

            try
            {
                var scriptName = Path.GetFileName(scriptPath);
                var fullArgs = new List<string> { scriptName };
                fullArgs.AddRange(args);
                
                sys.argv = fullArgs.ToArray();
                sys.stdout = stdoutString; // Redirect stdout
                sys.stderr = stderrString; // Redirect stderr
                os.chdir(targetDirectory);

                using (var scope = Py.CreateScope())
                {
                    scope.Set("__name__", "__main__");
                    // Add the script's directory to sys.path so it can import local modules
                    var scriptDir = Path.GetDirectoryName(scriptPath);
                    if (scriptDir != null) sys.path.insert(0, scriptDir);
                    
                    try
                    {
                        scope.Exec(File.ReadAllText(scriptPath));
                    }
                    finally
                    {
                        if (scriptDir != null) sys.path.pop(0);
                    }
                }

                return (string)stdoutString.getvalue();
            }
            catch (PythonException ex)
            {
                dynamic excType = sys.exc_info()[0];
                if (excType != null && (string)excType.__name__ == "SystemExit")
                {
                    dynamic excValue = sys.exc_info()[1];
                    try 
                    {
                        PyObject codeObj = excValue.code;
                        if (codeObj.IsNone()) 
                        {
                            return (string)stdoutString.getvalue();
                        }
                        else if (codeObj.HasAttr("__int__") && codeObj.As<int>() == 0) 
                        {
                            return (string)stdoutString.getvalue();
                        }
                    } 
                    catch { }
                }

                var stderr = (string)stderrString.getvalue();
                var stdout = (string)stdoutString.getvalue();
                throw new Exception($"Python execution failed.\nError: {ex.Message}\nStdout: {stdout}\nStderr: {stderr}");
            }
            finally
            {
                sys.argv = originalArgv;
                sys.stdout = oldStdout;
                sys.stderr = oldStderr;
                os.chdir(oldDir);
            }
        }
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

        var stdout = RunPythonScript(cprojectToCmakePath, targetDirectory, new[] { "--cproject", cprojPath, "--list-configs" });

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

        // 1. Generate CMakeLists.txt if not exists
        if (!File.Exists(cmakeListsPath) && File.Exists(cprojPath))
        {
            var args = new[] { "--cproject", cprojPath, "--template", templatePath, "--output", cmakeListsPath, "--config", configName };
            RunPythonScript(cprojectToCmakePath, targetDirectory, args);
        }

        // 2. Run MacroInsight main.py
        var outXmlName = $"{configName}.conditions.xml";
        var outXmlPath = Path.Combine(targetDirectory, outXmlName);

        var runArgs = new[] { "--repo-dir", targetDirectory, "--output", outXmlPath, "--output-format", "xml", "--clang", "clang" };
        RunPythonScript(mainPyPath, targetDirectory, runArgs);

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
}
