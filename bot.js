require('dotenv/config');
const { Client, GatewayIntentBits, EmbedBuilder } = require('discord.js');
const db = require('./database');

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages
  ]
});

const JOIN_URL = process.env.JOIN_URL || 'https://discord.com/oauth2/authorize?client_id=1516809327627866182&permissions=8&integration_type=0&scope=bot';
const ADMIN_IDS = (process.env.ADMIN_IDS || '').split(',').filter(Boolean);

const EMOJIS = {
  join: '<:link:1>',
  profile: '<:user:1>',
  email: '<:mail:1>',
  servers: '<:server:1>',
  ping: '<:ping:1>',
  stats: '<:stats:1>',
  help: '<:help:1>',
  sync: '<:sync:1>'
};

client.once('ready', () => {
  console.log(`Connecté en tant que ${client.user.tag}`);
  console.log(`Invite: ${JOIN_URL}`);
  client.user.setActivity('/help', { type: 2 });
});

client.on('interactionCreate', async (interaction) => {
  if (!interaction.isChatInputCommand()) return;

  const { commandName, user } = interaction;

  try {
    switch (commandName) {
      case 'join': await handleJoin(interaction); break;
      case 'profile': await handleProfile(interaction); break;
      case 'email': await handleEmail(interaction); break;
      case 'servers': await handleServers(interaction); break;
      case 'sync': await handleSync(interaction); break;
      case 'ping': await handlePing(interaction); break;
      case 'stats': await handleStats(interaction); break;
      case 'help': await handleHelp(interaction); break;
      case 'whois': await handleWhois(interaction); break;
    }
  } catch (err) {
    console.error(`Erreur commande ${commandName}:`, err);
    const errorMsg = { content: 'Une erreur est survenue lors de l\'exécution de la commande.', ephemeral: true };
    if (interaction.replied || interaction.deferred) {
      await interaction.followUp(errorMsg);
    } else {
      await interaction.reply(errorMsg);
    }
  }
});

async function handleJoin(interaction) {
  const embed = new EmbedBuilder()
    .setColor(0x5865F2)
    .setTitle('Connexion au Panel')
    .setDescription(
      'Clique sur le bouton ci-dessous pour connecter ton compte Discord au panel.\n\n' +
      '**Ce que ça permet :**\n' +
      '• Récupérer ton email Discord\n' +
      '• Rejoindre des serveurs automatiquement\n' +
      '• Gérer ton compte depuis le panel'
    )
    .setURL(JOIN_URL);

  await interaction.reply({
    embeds: [embed],
    components: [{
      type: 1,
      components: [{
        type: 2,
        style: 5,
        label: 'Se connecter',
        url: JOIN_URL
      }]
    }]
  });
}

async function handleProfile(interaction) {
  const userData = db.findUser(interaction.user.id);
  if (!userData) {
    return interaction.reply({
      content: 'Tu n\'es pas encore connecté au panel. Utilise `/join` pour commencer.',
      ephemeral: true
    });
  }

  const avatarUrl = userData.avatar
    ? `https://cdn.discordapp.com/avatars/${userData.id}/${userData.avatar}.png`
    : null;

  const embed = new EmbedBuilder()
    .setColor(0x5865F2)
    .setTitle(`Profil de ${userData.username}`)
    .setThumbnail(avatarUrl)
    .addFields(
      { name: 'ID', value: userData.id, inline: true },
      { name: 'Email', value: userData.email || 'Non disponible', inline: true },
      { name: 'Connecté depuis', value: new Date(userData.created_at).toLocaleDateString('fr-FR'), inline: true },
      { name: 'Dernière synchro', value: new Date(userData.updated_at).toLocaleString('fr-FR'), inline: true }
    );

  await interaction.reply({ embeds: [embed], ephemeral: true });
}

async function handleEmail(interaction) {
  const userData = db.findUser(interaction.user.id);
  if (!userData) {
    return interaction.reply({
      content: 'Tu n\'es pas encore connecté au panel. Utilise `/join` pour commencer.',
      ephemeral: true
    });
  }

  if (!userData.email) {
    return interaction.reply({
      content: 'Aucun email enregistré. Utilise `/sync` pour synchroniser tes données.',
      ephemeral: true
    });
  }

  await interaction.reply({
    content: `📧 **Email enregistré :** ||${userData.email}||`,
    ephemeral: true
  });
}

async function handleServers(interaction) {
  const userData = db.findUser(interaction.user.id);
  if (!userData) {
    return interaction.reply({
      content: 'Tu n\'es pas encore connecté au panel. Utilise `/join` pour commencer.',
      ephemeral: true
    });
  }

  const guilds = JSON.parse(userData.guilds_joined || '[]');
  if (guilds.length === 0) {
    return interaction.reply({
      content: 'Tu n\'as encore rejoint aucun serveur via le panel.',
      ephemeral: true
    });
  }

  const guildNames = await Promise.all(guilds.map(async (gid) => {
    try {
      const guild = client.guilds.cache.get(gid) || await client.guilds.fetch(gid);
      return `**${guild.name}** (\`${gid}\`)`;
    } catch {
      return `\`${gid}\``;
    }
  }));

  const embed = new EmbedBuilder()
    .setColor(0x5865F2)
    .setTitle(`Serveurs rejoints (${guilds.length})`)
    .setDescription(guildNames.join('\n'));

  await interaction.reply({ embeds: [embed], ephemeral: true });
}

async function handleSync(interaction) {
  const userData = db.findUser(interaction.user.id);
  if (!userData) {
    return interaction.reply({
      content: 'Tu n\'es pas encore connecté au panel. Utilise `/join` pour commencer.',
      ephemeral: true
    });
  }

  await interaction.deferReply({ ephemeral: true });

  try {
    const fetch = require('node-fetch');
    const DISCORD_API = 'https://discord.com/api/v10';

    let token = userData.access_token;
    if (Date.now() > userData.token_expires_at) {
      const refreshRes = await fetch(`${DISCORD_API}/oauth2/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
          client_id: process.env.DISCORD_CLIENT_ID,
          client_secret: process.env.DISCORD_CLIENT_SECRET,
          grant_type: 'refresh_token',
          refresh_token: userData.refresh_token
        })
      });
      const refreshData = await refreshRes.json();
      if (!refreshData.access_token) {
        return interaction.editReply({ content: 'Session expirée, reconnecte-toi avec `/join`.' });
      }
      token = refreshData.access_token;
      userData.refresh_token = refreshData.refresh_token;
      userData.token_expires_at = Date.now() + refreshData.expires_in * 1000;
    }

    const userRes = await fetch(`${DISCORD_API}/users/@me`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    const userApiData = await userRes.json();

    db.addUser({
      id: userApiData.id,
      username: userApiData.username,
      discriminator: userApiData.discriminator,
      avatar: userApiData.avatar,
      email: userApiData.email || null,
      access_token: token,
      refresh_token: userData.refresh_token,
      token_expires_at: userData.token_expires_at
    });

    await interaction.editReply({ content: '✅ Données synchronisées avec succès !' });
  } catch (err) {
    console.error('Sync error:', err);
    await interaction.editReply({ content: '❌ Erreur lors de la synchronisation.' });
  }
}

async function handlePing(interaction) {
  const latency = Math.round(client.ws.ping);
  const embed = new EmbedBuilder()
    .setColor(0x5865F2)
    .setTitle('Pong!')
    .addFields(
      { name: 'Latence API', value: `${latency}ms`, inline: true },
      { name: 'Uptime', value: formatUptime(client.uptime), inline: true }
    );

  await interaction.reply({ embeds: [embed], ephemeral: true });
}

async function handleStats(interaction) {
  const users = db.listUsers();
  const totalGuilds = client.guilds.cache.size;
  const totalUsers = users.length;
  const withEmail = users.filter(u => u.email).length;
  const haveJoined = users.filter(u => u.guilds_joined && u.guilds_joined !== '[]').length;

  const embed = new EmbedBuilder()
    .setColor(0x5865F2)
    .setTitle('Statistiques')
    .addFields(
      { name: 'Serveurs du bot', value: `${totalGuilds}`, inline: true },
      { name: 'Utilisateurs enregistrés', value: `${totalUsers}`, inline: true },
      { name: 'Avec email', value: `${withEmail}`, inline: true },
      { name: 'Ont rejoint un serveur', value: `${haveJoined}`, inline: true },
      { name: 'Uptime', value: formatUptime(client.uptime), inline: true }
    );

  await interaction.reply({ embeds: [embed], ephemeral: true });
}

async function handleHelp(interaction) {
  const embed = new EmbedBuilder()
    .setColor(0x5865F2)
    .setTitle('Commandes disponibles')
    .setDescription('Voici la liste des commandes du bot :')
    .addFields(
      { name: '</join>', value: 'Obtenir le lien pour connecter ton compte', inline: false },
      { name: '</profile>', value: 'Afficher tes informations enregistrées', inline: false },
      { name: '</email>', value: 'Afficher ton email Discord', inline: false },
      { name: '</servers>', value: 'Lister les serveurs rejoints via le panel', inline: false },
      { name: '</sync>', value: 'Synchroniser tes données Discord', inline: false },
      { name: '</ping>', value: 'Vérifier la latence du bot', inline: false },
      { name: '</stats>', value: 'Statistiques du bot', inline: false },
      { name: '</help>', value: 'Afficher la liste des commandes disponibles', inline: false },
      { name: '</whois>', value: '[Admin] Infos d\'un utilisateur', inline: false }
    )
    .setFooter({ text: 'Discord Panel' });

  await interaction.reply({ embeds: [embed], ephemeral: true });
}

async function handleWhois(interaction) {
  if (!ADMIN_IDS.includes(interaction.user.id)) {
    return interaction.reply({ content: '❌ Tu n\'es pas autorisé à utiliser cette commande.', ephemeral: true });
  }

  const targetId = interaction.options.getString('user_id');
  const userData = db.findUser(targetId);

  if (!userData) {
    return interaction.reply({ content: `Aucun utilisateur trouvé avec l'ID \`${targetId}\`.`, ephemeral: true });
  }

  const guilds = JSON.parse(userData.guilds_joined || '[]');
  const embed = new EmbedBuilder()
    .setColor(0x5865F2)
    .setTitle(`Informations de ${userData.username}`)
    .addFields(
      { name: 'ID', value: userData.id, inline: true },
      { name: 'Email', value: userData.email || 'Non disponible', inline: true },
      { name: 'Serveurs rejoints', value: `${guilds.length}`, inline: true },
      { name: 'Inscrit le', value: new Date(userData.created_at).toLocaleString('fr-FR'), inline: true },
      { name: 'Dernière synchro', value: new Date(userData.updated_at).toLocaleString('fr-FR'), inline: true }
    );

  await interaction.reply({ embeds: [embed], ephemeral: true });
}

function formatUptime(ms) {
  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  return `${days}j ${hours % 24}h ${minutes % 60}m`;
}

client.login(process.env.DISCORD_BOT_TOKEN);
