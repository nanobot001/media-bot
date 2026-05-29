const { spawn } = require('child_process');
const path = require('path');

const scriptPath = path.resolve(__dirname, 'run_idm_bridge.ps1');

console.log(`Starting IDM Bridge listener via powershell script: ${scriptPath}`);

const child = spawn('powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', scriptPath], {
  cwd: path.resolve(__dirname, '..'),
  shell: true,
  stdio: 'inherit',
  windowsHide: true
});

child.on('error', (err) => {
  console.error('Failed to start bridge process:', err);
  process.exit(1);
});

child.on('close', (code) => {
  console.log(`Bridge process exited with code ${code}`);
  process.exit(code);
});

// Propagate termination signals cleanly to child process
const handleSignal = (signal) => {
  console.log(`Received ${signal}. Gracefully terminating bridge...`);
  if (child) {
    child.kill(signal);
  }
};

process.on('SIGINT', () => handleSignal('SIGINT'));
process.on('SIGTERM', () => handleSignal('SIGTERM'));
