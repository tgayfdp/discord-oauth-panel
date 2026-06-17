const { spawn } = require('child_process');
const path = require('path');

const ROOT = __dirname;

function start(name, command, args) {
  const proc = spawn(command, args, {
    cwd: ROOT,
    stdio: 'pipe',
    shell: true,
    env: { ...process.env }
  });
  proc.stdout.on('data', (data) => {
    console.log(`[${name}] ${data.toString().trimEnd()}`);
  });
  proc.stderr.on('data', (data) => {
    console.error(`[${name}] ${data.toString().trimEnd()}`);
  });
  proc.on('close', (code) => {
    console.log(`[${name}] Arrêté (code ${code})`);
  });
  return proc;
}

console.log('Démarrage de tous les services...');

const server = start('PANEL', 'node', ['server.js']);
const bot = start('BOT', 'node', ['bot.js']);
const protect = start('PROTECT', 'python', ['protect.py']);

process.on('SIGTERM', () => {
  server.kill(); bot.kill(); protect.kill();
  process.exit();
});

process.on('SIGINT', () => {
  server.kill(); bot.kill(); protect.kill();
  process.exit();
});
