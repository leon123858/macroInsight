const form = document.getElementById('config-form');
const progressContainer = document.getElementById('progress-container');
const resultContainer = document.getElementById('result-container');
const progressBar = document.getElementById('progress-bar');
const statusText = document.getElementById('status-text');
const logView = document.getElementById('log-view');
const startBtn = document.getElementById('start-btn');
const resetBtn = document.getElementById('reset-btn');

function logInfo(msg, type = 'info') {
    const el = document.createElement('div');
    el.className = `log-entry ${type}`;
    el.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    logView.appendChild(el);
    logView.scrollTop = logView.scrollHeight;
}

async function runWorkerPool(commands, repoDir, clangExec, limit) {
    let activeWorkers = 0;
    let index = 0;
    let total = commands.length;
    let completed = 0;
    let hasError = false;

    // Aggregated state
    const allMacros = {};

    return new Promise((resolve, reject) => {
        function next() {
            if (hasError) return;
            while (activeWorkers < limit && index < total) {
                const cmd = commands[index++];
                activeWorkers++;
                logInfo(`Processing ${cmd.file}...`);

                fetch('/api/process', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        command: cmd,
                        repo_dir: repoDir,
                        clang_exec: clangExec
                    })
                })
                    .then(res => res.json())
                    .then(data => {
                        if (data.macros) {
                            Object.assign(allMacros, data.macros);
                        } else if (data.error) {
                            logInfo(`Error in ${cmd.file}: ${data.error}`, 'error');
                            hasError = true;
                            reject(new Error(`Error in ${cmd.file}: ${data.error}`));
                        }
                    })
                    .catch(err => {
                        if (hasError) return;
                        logInfo(`Failed to process ${cmd.file}: ${err.message}`, 'error');
                        hasError = true;
                        reject(new Error(`Failed to process ${cmd.file}: ${err.message}`));
                    })
                    .finally(() => {
                        activeWorkers--;
                        if (hasError) return;
                        completed++;
                        let pct = Math.floor((completed / total) * 100);
                        progressBar.style.width = `${pct}%`;
                        statusText.textContent = `Processed ${completed} / ${total} files`;

                        if (completed === total) {
                            resolve(allMacros);
                        } else {
                            next();
                        }
                    });
            }
        }
        next();
    });
}

form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const repoDir = document.getElementById('repo-dir').value;
    const clangExec = document.getElementById('clang-exec').value;
    const outputFormat = document.getElementById('output-format').value;
    const compileFallback = document.getElementById('compile-fallback').checked;
    const conditionalMacro = document.getElementById('conditional-macro').checked;
    const outputFile = document.getElementById('output-file').value;
    const jobs = parseInt(document.getElementById('jobs').value) || 4;

    // UI Update
    form.style.display = 'none';
    progressContainer.style.display = 'block';
    resultContainer.style.display = 'none';
    progressBar.style.width = '0%';
    statusText.textContent = 'Configuring run and fetching commands...';
    logView.innerHTML = '';

    try {
        logInfo('Calling /api/config...');
        const configRes = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repo_dir: repoDir,
                clang: clangExec,
                output_format: outputFormat,
                compile_fallback: compileFallback
            })
        });

        const configData = await configRes.json();
        if (configData.error) {
            throw new Error(configData.error);
        }

        const commands = configData.commands;
        if (!commands || commands.length === 0) {
            throw new Error('No files to process or compile_commands.json is empty.');
        }

        logInfo(`Found ${commands.length} target files. Starting parallel extraction...`, 'success');

        // Execute pool
        const macros = await runWorkerPool(commands, configData.repo_dir, configData.clang_exec, jobs);

        logInfo('Extraction complete. Calling /api/cleanup for final saving...');
        statusText.textContent = 'Finalizing and saving...';

        const cleanupRes = await fetch('/api/cleanup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                macros: macros,
                repo_dir: configData.repo_dir,
                output_file: outputFile,
                output_format: outputFormat,
                conditional_macro: conditionalMacro
            })
        });

        if (!cleanupRes.ok) {
            throw new Error(`Failed to cleanup: ${cleanupRes.statusText}`);
        }
        const cleanupData = await cleanupRes.json();

        progressContainer.style.display = 'none';
        resultContainer.style.display = 'block';
        document.getElementById('result-text').innerText =
            `Successfully extracted ${cleanupData.total_extracted} macros (${cleanupData.evaluable} static values).\n\nSaved to: ${cleanupData.output_file}`;

    } catch (err) {
        logInfo(`Fatal error: ${err.message}`, 'error');
        statusText.textContent = 'Run failed.';
        // enable returning to form
        setTimeout(() => {
            resetBtn.style.display = 'block';
            resultContainer.style.display = 'block';
            document.getElementById('result-text').innerText = `Error: ${err.message}`;
        }, 1000);
    }
});

resetBtn.addEventListener('click', () => {
    form.style.display = 'block';
    progressContainer.style.display = 'none';
    resultContainer.style.display = 'none';
});
