import os
import discord
from discord.ext import commands
from discord import app_commands
import random
import aiohttp
from PIL import Image
import pytesseract
import io
import asyncio
import functools

# Get token from environment variable
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if TOKEN is None:
    raise RuntimeError("DISCORD_BOT_TOKEN environment variable not set")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# === CONFIGURATION ===
WATCH_GUILD_ID = 123456789012345678  # Replace with your guild ID
WATCH_CHANNEL_ID = 987654321098765432  # Replace with your channel ID
SUMMON_COST = 50

# Banner mythic units detected from image
banner_mythics = {"middle": None, "left": None, "right": None}

# Rarity chances (base, cumulative by rarity)
RARITY_CHANCES = {
    "Secret": 0.00004,
    "Mythic": 0.005,
    "Legendary": 0.04,
    "Epic": 0.20,
    "Rare": 0.75496
}

# Fixed unit chances when rolled by rarity (except banner units get special chances)
FIXED_UNIT_CHANCES = {
    "Secret": 1.0,
    "Mythic": 0.003,
    "Legendary": 0.10,
    "Epic": 0.083,
    "Rare": 0.10
}

# Units by rarity
UNITS = {
    "Secret": ["Alocard"],
    "Mythic": [
        "Sosuke (Hebi)", "Ichiga (True Release)", "Kiskae", "Oryo", "Eizan", "Lilia", "Yuruicha", "Saber",
        "Medusa", "Kempache", "Hercool", "Kazzy", "NotGoodGuy", "Orehimi", "Deruta", "Rohan (Adult)", "Roku (Angel)",
        "Brisket", "Medea", "Archer", "Obita", "Tengon", "Akazo", "Noruto (Sage)", "Song Jinwu", "Cha-In",
        "Vogita Super", "Cu Chulainn", "Gujo", "Chaso", "Giro", "Valentine", "Itaduri", "Johnni", "Jag-o", "Todu",
        "Gear Boy", "Takaroda", "Speedcart", "Inumaki", "Nobara"
    ],
    "Legendary": [
        "Itochi", "Kinaru", "Bean", "Takaroda", "Nobara", "Roku (Dark)", "Goi", "Grim Wow", "Agony", "Inamuki"
    ],
    "Epic": [
        "Kokashi", "Alligator", "Kinnua", "Shinzi", "Pickleo", "Blossom", "Gaari", "Genas", "Inosake", "Genitsu",
        "Sprintwagon", "Nazuka"
    ],
    "Rare": [
        "Noruto", "Jon", "Roku", "Vogita", "Luffo", "Joe", "Rukio", "Ichiga", "Sosuke", "Sanjo"
    ]
}

# Units eligible for shiny and their rarity threshold
shiny_eligible = {"Takaroda", "Speedcart", "Inumaki", "Nobara"}

# User summon data (store total summons and pity states)
user_summon_data = {}

# User trait roll data
user_trait_data = {}

# --- FUNCTIONS for summon system ---

def roll_rarity(user_id):
    data = user_summon_data.setdefault(user_id, {"total_summons": 0, "mythic_pity": False, "legendary_pity": False})
    total = data["total_summons"]

    if total >= 400 and not data["mythic_pity"]:
        data["mythic_pity"] = True
        return "Mythic"
    if total >= 50 and not data["legendary_pity"]:
        data["legendary_pity"] = True
        return "Legendary"

    roll = random.random()
    cumulative = 0
    for rarity, chance in RARITY_CHANCES.items():
        cumulative += chance
        if roll < cumulative:
            return rarity
    return "Rare"

def get_unit_chances(rarity):
    units = UNITS[rarity]
    chances = {unit: FIXED_UNIT_CHANCES[rarity] for unit in units}

    # Override banner mythics chances only if rarity is Mythic and units exist
    if rarity == "Mythic":
        for slot, banner_unit in banner_mythics.items():
            if banner_unit and banner_unit in chances:
                chances[banner_unit] = 0.50 if slot == "middle" else 0.20
    return chances

def roll_unit(rarity):
    chances = get_unit_chances(rarity)
    total = sum(chances.values())
    roll = random.uniform(0, total)
    cumulative = 0
    for unit, chance in chances.items():
        cumulative += chance
        if roll <= cumulative:
            return unit
    # Fallback
    return random.choice(list(chances.keys()))

def is_shiny(unit, rarity, shinyhunter):
    if unit in shiny_eligible and rarity in ("Mythic", "Legendary", "Secret"):
        shiny_chance = 0.03 if shinyhunter else 0.015
        return random.random() < shiny_chance
    return False

async def extract_banner_units_from_image(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.read()
    image = Image.open(io.BytesIO(data))
    text = pytesseract.image_to_string(image)

    found_units = []
    for unit in UNITS["Mythic"]:
        if unit.lower() in text.lower():
            found_units.append(unit)
        if len(found_units) == 3:
            break

    if len(found_units) < 3:
        return None

    return {
        "middle": found_units[0],
        "left": found_units[1],
        "right": found_units[2]
    }

# --- DISCORD EVENTS ---

@bot.event
async def on_message(message):
    if (
        message.guild and
        message.guild.id == WATCH_GUILD_ID and
        message.channel.id == WATCH_CHANNEL_ID and
        message.attachments
    ):
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith("image"):
                extracted = await extract_banner_units_from_image(attachment.url)
                if extracted:
                    banner_mythics.update(extracted)
                    await message.channel.send(
                        f"📢 **Banner Updated!**\n"
                        f"🟣 Middle: {banner_mythics['middle']}\n"
                        f"🔵 Left: {banner_mythics['left']}\n"
                        f"🟢 Right: {banner_mythics['right']}"
                    )
                else:
                    await message.channel.send("❗ Could not auto-detect all 3 banner units.")
    await bot.process_commands(message)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    await tree.sync()

# --- SLASH COMMANDS ---

@tree.command(name="summon", description="Summon units with real chances and pity system.")
@app_commands.describe(amount="Number of summons (max 100)", shinyhunter="Enable shiny hunter bonus (true/false)")
async def summon(interaction: discord.Interaction, amount: int, shinyhunter: bool = False):
    if amount < 1 or amount > 100:
        await interaction.response.send_message("Amount must be between 1 and 100.", ephemeral=True)
        return

    user_id = interaction.user.id
    data = user_summon_data.setdefault(user_id, {"total_summons": 0, "mythic_pity": False, "legendary_pity": False})

    total_cost = amount * SUMMON_COST
    results = []

    mythic_pity_used = False
    legendary_pity_used = False

    for _ in range(amount):
        rarity = roll_rarity(user_id)

        if data["mythic_pity"]:
            mythic_pity_used = True
            data["total_summons"] = 0
            data["mythic_pity"] = False
            data["legendary_pity"] = False
        elif data["legendary_pity"]:
            legendary_pity_used = True
            data["total_summons"] = 0
            data["legendary_pity"] = False
        else:
            data["total_summons"] += 1

        unit = roll_unit(rarity)
        shiny = is_shiny(unit, rarity, shinyhunter)
        result = f"**{unit}** ({rarity})"
        if shiny:
            result += " ✨ *Shiny!*"
        results.append(result)

    summons_until_mythic = max(0, 400 - data["total_summons"])
    summons_until_legendary = max(0, 50 - data["total_summons"])

    pity_messages = []
    if mythic_pity_used:
        pity_messages.append("💥 Mythic pity triggered! Guaranteed Mythic this summon!")
    if legendary_pity_used:
        pity_messages.append("✨ Legendary pity triggered! Guaranteed Legendary this summon!")

    pity_status = (
        f"🎯 Summons until next Legendary pity: **{summons_until_legendary}**\n"
        f"🔥 Summons until next Mythic pity: **{summons_until_mythic}**"
    )

    response = (
        f"🎉 You rolled **{amount}** summon(s) and spent **{total_cost}** gems.\n"
        + "\n".join(results)
        + ("\n\n" + "\n".join(pity_messages) if pity_messages else "")
        + "\n\n" + pity_status
    )

    await interaction.response.send_message(response)

# Trait roll cog
class TraitRoller(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.trait_data = {
            "Range": 1 / 3.85,
            "Swift": 1 / 3.85,
            "Vigor": 1 / 3.85,
            "Scholar": 1 / 10,
            "Marksman": 1 / 15.39,
            "Fortune": 1 / 40,
            "Blitz": 1 / 54.05,
            "Solar": 1 / 200,
            "Deadeye": 1 / 266.67,
            "Ethereal": 1 / 571.43,
            "Monarch": 1 / 1000,
        }
        self.trait_emojis = {
            "Range": "<:Range:1389867136822018109>",
            "Swift": "<:Swift:1389867156056834119>",
            "Vigor": "<:Vigor:1389867176705654834>",
            "Scholar": "<:Scholar:1389867212818616360>",
            "Marksman": "<:Marksman:1389867231374086254>",
            "Fortune": "<:Fortune:1389867250336534598>",
            "Blitz": "<:Blitz:1389867307798499400>",
            "Solar": "<:Solar:1389867355315634236>",
            "Deadeye": "<:Deadeye:1389867374383202344>",
            "Ethereal": "<:Ethereal:1389867398353387520>",
            "Monarch": "<:Monarch:1389867414988132382>"
        }
        self.trait_rarity = {
            "Rare": ["Range", "Swift", "Vigor"],
            "Legendary": ["Scholar", "Marksman", "Fortune", "Blitz"],
            "Mythic": ["Solar", "Deadeye", "Ethereal", "Monarch"]
        }
        self.trait_names = list(self.trait_data.keys())
        self.weights = list(self.trait_data.values())

    @app_commands.command(name="trait_roll", description="Roll traits with real odds")
    @app_commands.describe(amount="Number of trait rolls (1-10000)")
    async def trait_roll(self, interaction: discord.Interaction, amount: int):
        if amount < 1 or amount > 10000:
            await interaction.response.send_message("Amount must be between 1 and 10,000.", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        if user_id not in user_trait_data:
            user_trait_data[user_id] = {"pity": 0, "total": {name: 0 for name in self.trait_names}}

        await interaction.response.send_message(f"Rolling {amount:,} times... Please wait...")

        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            functools.partial(random.choices, self.trait_names, weights=self.weights, k=amount)
        )

        user_trait_data[user_id]["pity"] += amount
        counts = {trait: 0 for trait in self.trait_names}
        for trait in results:
            counts[trait] += 1

        if user_trait_data[user_id]["pity"] >= 2500:
            counts["Monarch"] += 1
            user_trait_data[user_id]["pity"] = 0

        for trait, count in counts.items():
            user_trait_data[user_id]["total"][trait] += count

        embed = discord.Embed(
            title=f"<:TraitReroll:1389869460910768242> Trait Roll Results — {amount:,} Rolls",
            color=discord.Color.blue()
        )

        for rarity, traits in self.trait_rarity.items():
            value = ""
            for trait in traits:
                emoji = self.trait_emojis.get(trait, "")
                value += f"{emoji} {trait} **x{counts[trait]:,}**\n"
            embed.add_field(name=f"__**{rarity}**__", value=value, inline=False)

        await interaction.edit_original_response(embed=embed)

    @app_commands.command(name="average_trait", description="See your most rolled trait of all time")
    async def average_trait(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        if user_id not in user_trait_data or all(v == 0 for v in user_trait_data[user_id]["total"].values()):
            await interaction.response.send_message("You haven't rolled any traits yet.", ephemeral=True)
            return

        total_counts = user_trait_data[user_id]["total"]
        most_common = max(total_counts.items(), key=lambda x: x[1])
        emoji = self.trait_emojis.get(most_common[0], "")
        await interaction.response.send_message(
            f"Your average trait is: {emoji} **{most_common[0]}** (x{most_common[1]:,})"
        )

    @app_commands.command(name="clear_traits", description="Reset your total trait rolls to 0")
    async def clear_traits(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        user_trait_data[user_id] = {"pity": 0, "total": {name: 0 for name in self.trait_names}}
        await interaction.response.send_message("Your total trait data has been cleared.", ephemeral=True)

async def setup():
    await bot.add_cog(TraitRoller(bot))

async def main():
    await setup()
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
