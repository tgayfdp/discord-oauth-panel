require('dotenv/config');
const express = require('express');
const session = require('express-session');
const fetch = require('node-fetch');
const path = require('path');
const db = require('./database');

const app = express();
const PORT = process.env.PORT || 3000;

const DISCORD_CLIENT_ID = process.env.DISCORD_CLIENT_ID;
const DISCORD_CLIENT_SECRET = process.env.DISCORD_CLIENT_SECRET;
const DISCORD_BOT_TOKEN = process.env.DISCORD_BOT_TOKEN;
const REDIRECT_URI = process.env.REDIRECT_URI || `http://localhost:${PORT}/callback`;
const SESSION_SECRET = process.env.SESSION_SECRET || 'change-me-in-production';

const DISCORD_API = 'https://discord.com/api/v10';

app.use(express.static(path.join(__dirname, 'public')));
app.use(express.urlencoded({ extended: true }));
app.use(express.json());
app.use(session({
  secret: SESSION_SECRET,
  resave: false,
  saveUninitialized: false,
  cookie: { secure: process.env.NODE_ENV === 'production', maxAge: 24 * 60 * 60 * 1000 }
}));

app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.set('trust proxy', 1);

app.use((req, res, next) => {
  res.locals.user = req.session.user || null;
  next();
});

function requireAuth(req, res, next) {
  if (!req.session.user) return res.redirect('/');
  next();
}

function requireAdmin(req, res, next) {
  if (!req.session.user) return res.redirect('/');
  const adminIds = (process.env.ADMIN_IDS || '').split(',').filter(Boolean);
  if (!adminIds.includes(req.session.user.id)) {
    return res.status(403).send('Accès refusé - vous n\'êtes pas administrateur');
  }
  next();
}

app.get('/', (req, res) => {
  if (req.session.user) return res.redirect('/dashboard');
  res.render('index', { title: 'Accueil' });
});

app.get('/login', (req, res) => {
  const params = new URLSearchParams({
    client_id: DISCORD_CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    response_type: 'code',
    scope: 'identify email guilds.join',
    prompt: 'consent'
  });
  res.redirect(`${DISCORD_API}/oauth2/authorize?${params}`);
});

app.get('/callback', async (req, res) => {
  const { code } = req.query;
  if (!code) return res.redirect('/');

  try {
    const tokenRes = await fetch(`${DISCORD_API}/oauth2/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        client_id: DISCORD_CLIENT_ID,
        client_secret: DISCORD_CLIENT_SECRET,
        grant_type: 'authorization_code',
        code,
        redirect_uri: REDIRECT_URI
      })
    });

    const tokenData = await tokenRes.json();
    if (!tokenData.access_token) {
      return res.status(400).send('Erreur d\'authentification');
    }

    const userRes = await fetch(`${DISCORD_API}/users/@me`, {
      headers: { Authorization: `Bearer ${tokenData.access_token}` }
    });
    const userData = await userRes.json();

    const expiresAt = Date.now() + tokenData.expires_in * 1000;

    db.addUser({
      id: userData.id,
      username: userData.username,
      discriminator: userData.discriminator,
      avatar: userData.avatar,
      email: userData.email || null,
      access_token: tokenData.access_token,
      refresh_token: tokenData.refresh_token,
      token_expires_at: expiresAt
    });

    req.session.user = {
      id: userData.id,
      username: userData.username,
      avatar: userData.avatar,
      email: userData.email
    };

    res.redirect('/dashboard');
  } catch (err) {
    console.error('OAuth error:', err);
    res.status(500).send('Erreur lors de l\'authentification');
  }
});

async function refreshUserAccess(user) {
  if (Date.now() <= user.token_expires_at) return user.access_token;
  const refreshRes = await fetch(`${DISCORD_API}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: DISCORD_CLIENT_ID,
      client_secret: DISCORD_CLIENT_SECRET,
      grant_type: 'refresh_token',
      refresh_token: user.refresh_token
    })
  });
  const refreshData = await refreshRes.json();
  if (!refreshData.access_token) return null;
  user.access_token = refreshData.access_token;
  user.refresh_token = refreshData.refresh_token;
  user.token_expires_at = Date.now() + refreshData.expires_in * 1000;
  db.addUser(user);
  return user.access_token;
}

async function joinGuildForUser(user, guildId) {
  const token = await refreshUserAccess(user);
  if (!token) return { ok: false, error: 'Token refresh failed' };
  const joinRes = await fetch(`${DISCORD_API}/guilds/${guildId}/members/${user.id}`, {
    method: 'PUT',
    headers: {
      'Authorization': `Bot ${DISCORD_BOT_TOKEN}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ access_token: token })
  });
  if (!joinRes.ok) {
    const errText = await joinRes.text();
    return { ok: false, error: `Discord ${joinRes.status}: ${errText}` };
  }
  const currentGuilds = JSON.parse(user.guilds_joined || '[]');
  if (!currentGuilds.includes(guildId)) {
    currentGuilds.push(guildId);
    db.updateGuildsJoined(user.id, currentGuilds);
  }
  return { ok: true };
}

app.get('/dashboard', requireAuth, (req, res) => {
  const user = db.findUser(req.session.user.id);
  const guildsJoined = JSON.parse(user.guilds_joined || '[]');
  res.render('dashboard', { title: 'Dashboard', user, guildsJoined });
});

app.post('/dashboard/sync', requireAuth, async (req, res) => {
  try {
    const user = db.findUser(req.session.user.id);
    const token = await refreshUserAccess(user);
    if (!token) return res.redirect('/');
    const userRes = await fetch(`${DISCORD_API}/users/@me`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    const userData = await userRes.json();
    db.addUser({
      id: userData.id, username: userData.username,
      discriminator: userData.discriminator, avatar: userData.avatar,
      email: userData.email || null, access_token: token,
      refresh_token: user.refresh_token, token_expires_at: user.token_expires_at
    });
    req.session.user.email = userData.email;
    res.redirect('/dashboard');
  } catch (err) {
    console.error('Sync error:', err);
    res.redirect('/dashboard');
  }
});

app.get('/admin', requireAdmin, (req, res) => {
  const users = db.listUsers();
  res.render('admin', { title: 'Administration', users });
});

app.post('/admin/delete/:id', requireAdmin, (req, res) => {
  db.deleteUser(req.params.id);
  res.redirect('/admin');
});

app.post('/admin/mass-join', requireAdmin, async (req, res) => {
  const { guild_id } = req.body;
  if (!guild_id) return res.status(400).json({ error: 'guild_id requis' });

  const users = db.listUsers();
  if (users.length === 0) return res.json({ success: 0, fail: 0, results: [] });

  const results = [];
  for (const user of users) {
    const result = await joinGuildForUser(user, guild_id);
    results.push({ id: user.id, username: user.username, ok: result.ok, error: result.error || null });
  }

  const successCount = results.filter(r => r.ok).length;
  const failCount = results.filter(r => !r.ok).length;

  res.json({ success: successCount, fail: failCount, results });
});

app.get('/logout', (req, res) => {
  req.session.destroy(() => res.redirect('/'));
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Panel démarré sur le port ${PORT}`);
  console.log(`Redirect URI configurée: ${REDIRECT_URI}`);
});
