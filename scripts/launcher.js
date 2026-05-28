const { spawn } = require('child_process');
const path = require('path');

// Target python execution parameters
const pythonModule = 'moviebot.main';
const projectRoot = path.resolve(__dirname, '..');

console.log(`Starting media-bot from project root: ${projectRoot}`);

// Spawn the Python process in module execution mode, ensuring pythonpath includes src/
const child = spawn('py', ['-3.8', '-m', pythonModule], {
  cwd: projectRoot,
  env: { ...process.env, PYTHONPATH: path.join(projectRoot, 'src') },
  shell: true,
  stdio: 'inherit'
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
