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
  proc.on('error', (err) => {
    console.error(`[${name}] Erreur: ${err.message}`);
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

protect.on('error', () => {
  console.log('[PROTECT] Python pas trouvé, essai avec python3...');
  const p3 = spawn('python3', ['protect.py'], {
    cwd: ROOT, stdio: 'pipe', shell: true, env: { ...process.env }
  });
  p3.stdout.on('data', (d) => console.log(`[PROTECT] ${d.toString().trimEnd()}`));
  p3.stderr.on('data', (d) => console.error(`[PROTECT] ${d.toString().trimEnd()}`));
  p3.on('error', () => console.log('[PROTECT] Python 3 non disponible, ignoré'));
  p3.on('close', (c) => console.log(`[PROTECT] Arrêté (code ${c})`));
});

process.on('SIGTERM', () => {
  server.kill('SIGTERM'); bot.kill('SIGTERM'); protect.kill('SIGTERM');
  process.exit(0);
});

process.on('SIGINT', () => {
  server.kill('SIGINT'); bot.kill('SIGINT'); protect.kill('SIGINT');
  process.exit(0);
});
