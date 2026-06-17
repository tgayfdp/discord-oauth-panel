const Database = require('better-sqlite3');
const path = require('path');

const dbPath = path.join(__dirname, 'users.db');
const db = new Database(dbPath);

db.pragma('journal_mode = WAL');

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    discriminator TEXT,
    avatar TEXT,
    email TEXT,
    access_token TEXT,
    refresh_token TEXT,
    token_expires_at INTEGER,
    guilds_joined TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
  )
`);

const insertUser = db.prepare(`
  INSERT INTO users (id, username, discriminator, avatar, email, access_token, refresh_token, token_expires_at)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?)
  ON CONFLICT(id) DO UPDATE SET
    username = excluded.username,
    discriminator = excluded.discriminator,
    avatar = excluded.avatar,
    email = excluded.email,
    access_token = excluded.access_token,
    refresh_token = excluded.refresh_token,
    token_expires_at = excluded.token_expires_at,
    updated_at = datetime('now')
`);

const getUser = db.prepare('SELECT * FROM users WHERE id = ?');
const getAllUsers = db.prepare('SELECT * FROM users ORDER BY created_at DESC');

function addUser(user) {
  insertUser.run(
    user.id,
    user.username,
    user.discriminator || null,
    user.avatar || null,
    user.email || null,
    user.access_token,
    user.refresh_token,
    user.token_expires_at
  );
}

function findUser(id) {
  return getUser.get(id);
}

function listUsers() {
  return getAllUsers.all();
}

function updateGuildsJoined(userId, guilds) {
  db.prepare('UPDATE users SET guilds_joined = ?, updated_at = datetime(\'now\') WHERE id = ?')
    .run(JSON.stringify(guilds), userId);
}

function deleteUser(id) {
  db.prepare('DELETE FROM users WHERE id = ?').run(id);
}

module.exports = { addUser, findUser, listUsers, updateGuildsJoined, deleteUser };
