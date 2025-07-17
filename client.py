import os
from dotenv import load_dotenv
import discord
from discord import app_commands, Interaction
from discord.ext import commands
import random
import string
import io
from PIL import Image, ImageDraw, ImageFont
import asyncio
import datetime

from keep_alive import keep_alive

load_dotenv()
token = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

user_balances = {}
message_count = 0
ticket_category_id = None
SOCIAL_CHANNEL_ID = None
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# LOCK / UNLOCK
@tree.command(name="lock", description="Verrouille un salon")
@app_commands.describe(channel="Salon à verrouiller (optionnel)")
async def lock(interaction: Interaction, channel: discord.TextChannel = None):
    channel = channel or interaction.channel
    await interaction.response.defer(ephemeral=True)
    await channel.set_permissions(interaction.guild.default_role, send_messages=False)
    await interaction.followup.send(f"🔒 Salon {channel.mention} verrouillé.", ephemeral=True)
    
@tree.command(name="unlock", description="Déverrouille un salon")
@app_commands.describe(channel="Salon à déverrouiller (optionnel)")
async def unlock(interaction: Interaction, channel: discord.TextChannel = None):
    channel = channel or interaction.channel
    await interaction.response.defer(ephemeral=True)
    await channel.set_permissions(interaction.guild.default_role, send_messages=True)
    await interaction.followup.send(f"🔓 Salon {channel.mention} déverrouillé.", ephemeral=True)

# TICKET SYSTEM
@tree.command(name="ticket", description="Crée un ticket privé")
async def ticket(interaction: Interaction):
    if not ticket_category_id:
        await interaction.response.send_message("Catégorie tickets non définie.", ephemeral=True)
        return
    category = interaction.guild.get_channel(ticket_category_id)
    if not category:
        await interaction.response.send_message("Catégorie tickets invalide.", ephemeral=True)
        return
    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        interaction.guild.me: discord.PermissionOverwrite(view_channel=True)
    }
    ticket_channel = await interaction.guild.create_text_channel(
        f"ticket-{interaction.user.name}", overwrites=overwrites, category=category
    )
    await ticket_channel.send(f"Bonjour {interaction.user.mention}, explique ton problème.")
    await interaction.response.send_message(f"Ticket créé : {ticket_channel.mention}", ephemeral=True)

@tree.command(name="close", description="Ferme le ticket actuel")
async def close(interaction: Interaction):
    if interaction.channel.name.startswith("ticket-"):
        await interaction.response.defer(ephemeral=True)
        await interaction.channel.send("Ticket fermé.")
        await asyncio.sleep(2)
        await interaction.channel.delete()
        # Pas de followup nécessaire après delete
    else:
        await interaction.response.send_message("Cette commande ne peut être utilisée que dans un ticket.", ephemeral=True)

@tree.command(name="setticketcat", description="Définit la catégorie pour les tickets")
@app_commands.describe(cat="Catégorie")
async def setticketcat(interaction: Interaction, cat: discord.CategoryChannel):
    global ticket_category_id
    ticket_category_id = cat.id
    await interaction.response.send_message(f"Catégorie tickets : {cat.name}", ephemeral=True)

# ARRIVÉE / DÉPART / CAPTCHA
@bot.event
async def on_member_join(member):
    captcha_text = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    image = Image.new('RGB', (200, 70), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(FONT_PATH, 40)
    draw.text((20, 10), captcha_text, font=font, fill=(0,0,0))
    with io.BytesIO() as image_binary:
        image.save(image_binary, 'PNG')
        image_binary.seek(0)
        try:
            await member.send("Bienvenue ! Veuillez entrer ce captcha pour accéder au serveur :", file=discord.File(fp=image_binary, filename="captcha.png"))
        except:
            return
    def check(m):
        return m.author == member and isinstance(m.channel, discord.DMChannel)
    try:
        msg = await bot.wait_for('message', check=check, timeout=120)
        if msg.content.strip().upper() == captcha_text:
            await member.send("Captcha réussi. Bienvenue !")
            role = discord.utils.get(member.guild.roles, name="Membre")
            if role:
                await member.add_roles(role)
        else:
            await member.send("Captcha incorrect. Réessaie en rejoignant le serveur.")
            await member.kick(reason="Captcha échoué")
    except asyncio.TimeoutError:
        try:
            await member.send("Temps écoulé. Réessaie en rejoignant le serveur.")
        except:
            pass
        await member.kick(reason="Captcha non répondu")

@bot.event
async def on_member_remove(member):
    channel = discord.utils.get(member.guild.text_channels, name="général")
    if channel:
        await channel.send(f"{member.name} a quitté le serveur !")

# STATISTIQUES
@bot.event
async def on_message(message):
    global message_count
    if message.author.bot:
        return
    message_count += 1
    await bot.process_commands(message)

@tree.command(name="stats", description="Affiche les statistiques du serveur")
async def stats(interaction: Interaction):
    guild = interaction.guild
    embed = discord.Embed(title="Statistiques du serveur")
    embed.add_field(name="Membres", value=str(guild.member_count))
    embed.add_field(name="Salons", value=str(len(guild.channels)))
    embed.add_field(name="Messages depuis le lancement", value=str(message_count))
    await interaction.response.send_message(embed=embed, ephemeral=True)

# SOCIAL NOTIFY
@tree.command(name="setsocial", description="Définit le salon pour notification sociale")
@app_commands.describe(chan="Salon de notification")
async def setsocial(interaction: Interaction, chan: discord.TextChannel):
    global SOCIAL_CHANNEL_ID
    SOCIAL_CHANNEL_ID = chan.id
    await interaction.response.send_message(f"Salon social défini : {chan.mention}", ephemeral=True)

async def notify_social(message):
    if SOCIAL_CHANNEL_ID:
        channel = bot.get_channel(SOCIAL_CHANNEL_ID)
        if channel:
            await channel.send(f"Notification sociale : {message}")

# ÉCONOMIE
@tree.command(name="daily", description="Récupère les points quotidiens")
async def daily(interaction: Interaction):
    uid = str(interaction.user.id)
    now = datetime.date.today()
    user = user_balances.get(uid, {"balance": 0, "last_daily": None})
    if user["last_daily"] == now:
        await interaction.response.send_message("Tu as déjà réclamé ta récompense aujourd’hui.", ephemeral=True)
        return
    user["balance"] += 100
    user["last_daily"] = now
    user_balances[uid] = user
    await interaction.response.send_message("Tu as reçu 100 points !", ephemeral=True)

@tree.command(name="balance", description="Montre le solde de points d'un membre")
@app_commands.describe(member="Membre (optionnel)")
async def balance(interaction: Interaction, member: discord.Member = None):
    member = member or interaction.user
    uid = str(member.id)
    bal = user_balances.get(uid, {"balance": 0})["balance"]
    await interaction.response.send_message(f"{member.mention} possède {bal} points.", ephemeral=True)

@tree.command(name="pay", description="Donne des points à quelqu'un")
@app_commands.describe(member="Membre à payer", amount="Montant")
async def pay(interaction: Interaction, member: discord.Member, amount: int):
    uid = str(interaction.user.id)
    tuid = str(member.id)
    if amount <= 0:
        await interaction.response.send_message("Montant invalide.", ephemeral=True)
        return
    if user_balances.get(uid, {"balance":0})["balance"] < amount:
        await interaction.response.send_message("Solde insuffisant.", ephemeral=True)
        return
    user_balances[uid]["balance"] -= amount
    user_balances[tuid] = user_balances.get(tuid, {"balance":0})
    user_balances[tuid]["balance"] += amount
    await interaction.response.send_message(f"{interaction.user.mention} a donné {amount} points à {member.mention}.", ephemeral=True)

# SYNC SLASH COMMANDS
@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user}")
    try:
        await tree.sync()
        print("Slash commands synchronisées.")
    except Exception as e:
        print(f"Erreur lors de la sync des slash commands: {e}")

keep_alive()
bot.run(token=token)