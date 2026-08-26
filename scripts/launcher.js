const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// Target python execution parameters
const pythonModule = 'moviebot.main';
const projectRoot = path.resolve(__dirname, '..');

function hasPythonStandardLibrary(pythonHome) {
  return Boolean(pythonHome)
    && fs.existsSync(path.join(pythonHome, 'Lib', 'os.py'))
    && fs.existsSync(path.join(pythonHome, 'Lib', 'encodings', '__init__.py'));
}

function canRunProject(candidate) {
  const env = { ...process.env };
  if (candidate.pythonHome) {
    env.PYTHONHOME = candidate.pythonHome;
  } else {
    delete env.PYTHONHOME;
  }

  const probe = spawnSync(
    candidate.command,
    [...candidate.args, '-c', [
      'import sys',
      'assert sys.version_info[:2] == (3, 12), sys.version',
      'import discord, fastapi, httpx, mcp, pydantic_settings, rapidfuzz, uvicorn, yaml',
    ].join('; ')],
    {
      cwd: projectRoot,
      env,
      windowsHide: true,
      encoding: 'utf8',
      timeout: 15000,
    }
  );

  return probe.status === 0;
}

function resolvePythonRuntime() {
  const localAppData = process.env.LOCALAPPDATA || '';
  const repairedUserHome = localAppData
    ? path.join(localAppData, 'Programs', 'Python', 'Python312')
    : '';
  const configuredPython = process.env.MEDIABOT_PYTHON;
  const configuredHome = process.env.MEDIABOT_PYTHONHOME;
  const candidates = [
    configuredPython && { executable: configuredPython, pythonHome: configuredHome },
    { executable: path.join(projectRoot, '.venv', 'Scripts', 'python.exe'), useRepairedHome: false },
    localAppData && { executable: path.join(repairedUserHome, 'python.exe') },
    { executable: 'C:\\Python312\\python.exe' },
  ].filter(Boolean);

  for (const candidate of candidates) {
    if (!path.isAbsolute(candidate.executable) || !fs.existsSync(candidate.executable)) {
      continue;
    }

    const executableHome = path.dirname(candidate.executable);
    const pythonHome = candidate.pythonHome
      || (candidate.useRepairedHome === false
        ? undefined
        : (hasPythonStandardLibrary(executableHome)
          ? undefined
          : (hasPythonStandardLibrary(repairedUserHome) ? repairedUserHome : undefined)));

    const resolved = {
      command: candidate.executable,
      args: [],
      pythonHome,
      description: `${candidate.executable}${pythonHome ? ` (PYTHONHOME=${pythonHome})` : ''}`
    };

    if (!canRunProject(resolved)) {
      console.warn(`Skipping unusable Python runtime: ${resolved.description}`);
      continue;
    }

    return resolved;
  }

  const launcherFallback = {
    command: 'py',
    args: ['-3.12'],
    pythonHome: configuredHome,
    description: 'py -3.12'
  };
  if (canRunProject(launcherFallback)) return launcherFallback;

  throw new Error(
    'No usable Python 3.12 project runtime was found. ' +
    'Create .venv with Python 3.12 and install the project dependencies.'
  );
}

const pythonRuntime = resolvePythonRuntime();

console.log(`Starting media-bot from project root: ${projectRoot}`);
console.log(`Using Python runtime: ${pythonRuntime.description}`);

// Spawn the Python process in module execution mode, ensuring pythonpath includes src/
const runtimeEnv = {
  ...process.env,
  PYTHONPATH: path.join(projectRoot, 'src'),
  PYTHONUNBUFFERED: '1'
};
if (pythonRuntime.pythonHome) {
  runtimeEnv.PYTHONHOME = pythonRuntime.pythonHome;
} else {
  delete runtimeEnv.PYTHONHOME;
}

const child = spawn(pythonRuntime.command, [...pythonRuntime.args, '-u', '-m', pythonModule], {
  cwd: projectRoot,
  env: runtimeEnv,
  shell: false,
  stdio: 'inherit',
  windowsHide: true
});

child.on('error', (err) => {
  console.error('Failed to start python process:', err);
  process.exit(1);
});

child.on('close', (code) => {
  console.log(`Python process exited with code ${code}`);
  process.exit(code);
});

// Propagate termination signals cleanly to child process
const handleSignal = (signal) => {
  console.log(`Received ${signal}. Gracefully terminating child process...`);
  if (child) {
    child.kill(signal);
  }
};

process.on('SIGINT', () => handleSignal('SIGINT'));
process.on('SIGTERM', () => handleSignal('SIGTERM'));
