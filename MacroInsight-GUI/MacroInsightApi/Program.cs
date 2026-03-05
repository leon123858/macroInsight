using MacroInsightApi.Services;
using Microsoft.AspNetCore.Mvc;
using Swashbuckle.AspNetCore;

var builder = WebApplication.CreateBuilder(args);

// Add services to the container.
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();
builder.Services.AddSingleton<EnvService>();
builder.Services.AddScoped<ProjectService>();

var app = builder.Build();

// Configure the HTTP request pipeline.
if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();

    Console.WriteLine("swagger run on:  {url}/swagger");
}

// Initialize Python Engine Async during startup
using (var scope = app.Services.CreateScope())
{
    var envService = scope.ServiceProvider.GetRequiredService<EnvService>();
}

app.MapGet("/api/env/cmake", (EnvService env) => Results.Ok(env.CheckCmake()));

app.MapGet("/api/env/compiler/list", (EnvService env) => Results.Ok(env.ScanCompilers()));

app.MapPost("/api/env/compiler/select", ([FromBody] SelectCompilerRequest req, EnvService env) => 
{
    var success = env.SelectCompiler(req.BinPath);
    return Results.Ok(new { success });
});

app.MapPost("/api/project/check-cproject", ([FromBody] ProjectRequest req, ProjectService proj) => 
{
    var exists = proj.CheckCProject(req.TargetDirectory);
    return Results.Ok(new { exists });
});

app.MapPost("/api/project/list-configs", ([FromBody] ProjectRequest req, ProjectService proj) => 
{
    try 
    {
        var configs = proj.ListConfigs(req.TargetDirectory);
        return Results.Ok(configs);
    }
    catch (Exception ex) 
    {
        return Results.BadRequest(new { error = ex.Message });
    }
});

app.MapPost("/api/project/generate", ([FromBody] GenerateRequest req, ProjectService proj) => 
{
    try 
    {
        var outPath = proj.GenerateConditions(req.TargetDirectory, req.ConfigName);
        return Results.Ok(new { filePath = outPath });
    }
    catch (Exception ex) 
    {
        return Results.BadRequest(new { error = ex.Message });
    }
});

app.MapGet("/api/project/download", (string filePath) => 
{
    // Make sure it doesn't allow random file downloads.
    if (!System.IO.File.Exists(filePath)) return Results.NotFound();
    
    var fileName = Path.GetFileName(filePath);
    if (!fileName.EndsWith(".conditions.xml")) return Results.BadRequest("Only conditions.xml files can be downloaded.");

    return Results.File(filePath, "application/xml", fileName);
});

app.MapPost("/api/project/cleanup", ([FromBody] GenerateRequest req, ProjectService proj) => 
{
    proj.Cleanup(req.TargetDirectory, req.ConfigName);
    return Results.Ok(new { success = true });
});

app.Run();

public record SelectCompilerRequest(string BinPath);
public record ProjectRequest(string TargetDirectory);
public record GenerateRequest(string TargetDirectory, string ConfigName);
