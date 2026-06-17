require('dotenv/config');
const { REST, Routes } = require('discord.js');

const commands = [
  {
    name: 'join',
    description: 'Obtenir le lien pour connecter votre compte au panel',
    dm_permission: true
  },
  {
    name: 'profile',
    description: 'Afficher vos informations Discord enregistrées',
    dm_permission: true
  },
  {
    name: 'email',
    description: 'Afficher votre email Discord enregistré',
    dm_permission: true
  },
  {
    name: 'servers',
    description: 'Lister les serveurs que vous avez rejoints via le panel',
    dm_permission: true
  },
  {
    name: 'sync',
    description: 'Synchroniser vos informations Discord',
    dm_permission: true
  },
  {
    name: 'ping',
    description: 'Vérifier la latence du bot',
    dm_permission: true
  },
  {
    name: 'stats',
    description: 'Afficher les statistiques du bot',
    dm_permission: true
  },
  {
    name: 'help',
    description: 'Afficher la liste des commandes disponibles',
    dm_permission: true
  },
  {
    name: 'whois',
    description: '[Admin] Voir les infos d\'un utilisateur par ID',
    dm_permission: false,
    options: [{
      name: 'user_id',
      description: 'ID Discord de l\'utilisateur',
      type: 3,
      required: true
    }]
  }
];

const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_BOT_TOKEN);

(async () => {
  try {
    console.log('Déploiement des commandes slash...');
    const data = await rest.put(
      Routes.applicationCommands(process.env.DISCORD_CLIENT_ID),
      { body: commands }
    );
    console.log(`${data.length} commandes déployées avec succès !`);
  } catch (err) {
    console.error('Erreur:', err);
  }
})();
