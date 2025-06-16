import discord
from discord import app_commands
import os
from dotenv import load_dotenv
import datetime
import sqlite3
from discord.utils import get

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# Инициализация базы данных с исправленной структурой
def init_db():
    conn = sqlite3.connect('game_stats.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS stats
               (guild_id INTEGER PRIMARY KEY,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                territories INTEGER DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS history
               (id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                screenshot_url TEXT NOT NULL,
                territories INTEGER NOT NULL,
                note TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS bot_settings
               (guild_id INTEGER PRIMARY KEY,
                stats_channel_id INTEGER,
                allowed_role_id INTEGER)''')
    
    conn.commit()
    conn.close()

init_db()

@bot.event
async def on_ready():
    print(f'Бот {bot.user} запущен!')
    try:
        await tree.sync()
        print("Слэш-команды синхронизированы")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")

# Проверка прав
async def has_permission(interaction):
    conn = sqlite3.connect('game_stats.db')
    c = conn.cursor()
    c.execute('''SELECT allowed_role_id FROM bot_settings WHERE guild_id = ?''', (interaction.guild.id,))
    role_id = c.fetchone()
    conn.close()
    
    if not role_id or not role_id[0]:
        return True  # Если роль не установлена, разрешаем всем
    
    role = get(interaction.guild.roles, id=role_id[0])
    if role in interaction.user.roles:
        return True
    
    await interaction.response.send_message(
        "❌ У вас нет прав для использования этой команды!",
        ephemeral=True
    )
    return False

@tree.command(name="rate", description="Показать детальную статистику")
async def rate(interaction: discord.Interaction):
    conn = sqlite3.connect('game_stats.db')
    c = conn.cursor()
    
    # Получаем основную статистику
    c.execute('''SELECT wins, losses, territories FROM stats WHERE guild_id = ?''', (interaction.guild.id,))
    stats_data = c.fetchone()
    
    if not stats_data:
        embed = discord.Embed(
            title="📊 Статистика отсутствует",
            description="Используйте команды /att_win или /def_loose чтобы начать сбор статистики",
            color=discord.Color.light_grey()
        )
        await interaction.response.send_message(embed=embed)
        return
    
    wins, losses, territories = stats_data
    total_games = wins + losses
    
    # Получаем последние события
    c.execute('''SELECT action_type, timestamp FROM history 
                WHERE guild_id = ? 
                ORDER BY timestamp DESC LIMIT 5''', (interaction.guild.id,))
    history = c.fetchall()
    
    # Рассчитываем проценты
    win_rate = (wins / total_games * 100) if total_games > 0 else 0
    loss_rate = (losses / total_games * 100) if total_games > 0 else 0
    
    # Создаём прогресс-бар
    bar_length = 10
    win_bar = '🟩' * round(win_rate / 100 * bar_length)
    loss_bar = '🟥' * round(loss_rate / 100 * bar_length)
    
    # Формируем Embed
    embed = discord.Embed(
        title=f"📊 СТАТИСТИКА СЕРВЕРА {interaction.guild.name}",
        color=discord.Color.gold()
    )
    
    # Основные показатели
    embed.add_field(
        name="🏰 ТОЧЕК", 
        value=f"```{territories}/18```", 
        inline=False
    )
    
    # График соотношения
    embed.add_field(
        name=f"📈 СООТНОШЕНИЕ [{win_rate:.1f}%]",
        value=f"{win_bar}{loss_bar}\n"
              f"✅ {wins} побед | ❌ {losses} поражений",
        inline=False
    )
    
    # История последних событий (с временем вместо даты)
    if history:
        history_str = ""
        for action, timestamp in history:
            action_emoji = "🟢" if "win" in action else "🔴"
            # Преобразуем timestamp в объект datetime
            event_time = datetime.datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            # Форматируем только время (часы:минуты)
            time_str = event_time.strftime("%H:%M")
            history_str += f"{action_emoji} {time_str} - {action.replace('_', ' ').title()}\n"
        
        embed.add_field(
            name="⏳ ПОСЛЕДНИЕ СОБЫТИЯ",
            value=history_str,
            inline=False
        )
    
    # Динамика изменений (оставляем как было)
    if len(history) > 1:
        last_change = int(history[0][1][8:10]) - int(history[1][1][8:10])
        trend = "↑" if last_change >=0 else "↓"
        embed.add_field(
            name="📊 ДИНАМИКА",
            value=f"Последнее изменение: {trend} {abs(last_change)} точек",
            inline=True
        )
    
    embed.set_footer(text=f"Обновлено: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}")
    
    await interaction.response.send_message(embed=embed)
    conn.close()

# Команда /addrole
@tree.command(name="addrole", description="Установить роль для управления ботом")
@app_commands.describe(role="Роль, которая получит доступ к командам")
async def addrole(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Только администраторы могут использовать эту команду!",
            ephemeral=True
        )
        return
    
    conn = sqlite3.connect('game_stats.db')
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO bot_settings 
                (guild_id, allowed_role_id) VALUES (?, ?)''',
              (interaction.guild.id, role.id))
    conn.commit()
    conn.close()
    
    await interaction.response.send_message(
        f"✅ Роль {role.mention} теперь имеет доступ к командам бота!",
        ephemeral=True
    )
@tree.command(name="current", description="Установить текущее количество территорий")
@app_commands.describe(
    territories="Текущее количество территорий",
    note="Примечание (необязательно)"
)
async def current(interaction: discord.Interaction, territories: int, note: str = None):
    if not await has_permission(interaction):
        return
    
    await interaction.response.defer()
    
    conn = sqlite3.connect('game_stats.db')
    c = conn.cursor()
    
    # Обновляем статистику
    c.execute('''INSERT OR REPLACE INTO stats (guild_id, territories) VALUES (?, ?)''',
             (interaction.guild.id, territories))
    
    # Добавляем запись в историю
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''INSERT INTO history 
                (guild_id, user_id, action_type, timestamp, screenshot_url, territories, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
             (interaction.guild.id, interaction.user.id, "manual_update", 
              timestamp, "", territories, note))
    
    conn.commit()
    conn.close()
    
    # Отправляем подтверждение
    embed = discord.Embed(
        title="✅ Текущее количество территорий установлено",
        description=f"Установлено значение: **{territories}**",
        color=discord.Color.blue()
    )
    if note:
        embed.add_field(name="Примечание", value=note, inline=False)
    embed.set_footer(text=f"Установлено {interaction.user.display_name}")
    
    await interaction.followup.send(embed=embed)
# Команда /addchannel
@tree.command(name="addchannel", description="Установить канал для статистики")
@app_commands.describe(channel="Канал для отправки статистики")
async def addchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Только администраторы могут использовать эту команду!",
            ephemeral=True
        )
        return
    
    conn = sqlite3.connect('game_stats.db')
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO bot_settings 
                (guild_id, stats_channel_id) VALUES (?, ?)''',
              (interaction.guild.id, channel.id))
    conn.commit()
    conn.close()
    
    await interaction.response.send_message(
        f"✅ Канал {channel.mention} теперь используется для статистики!",
        ephemeral=True
    )

# ... (предыдущие импорты и настройки остаются без изменений)

# Новые команды атаки
@tree.command(name="att_win", description="Победа в атаке (+1 точка)")
@app_commands.describe(
    screenshot="Скриншот с подтверждением",
    note="Дополнительная заметка (необязательно)"
)
async def att_win(interaction: discord.Interaction, screenshot: discord.Attachment, note: str = None):
    await process_win(interaction, screenshot, note, attack=True)

@tree.command(name="att_loose", description="Поражение в атаке (точки не меняются)")
@app_commands.describe(
    screenshot="Скриншот с подтверждением",
    note="Дополнительная заметка (необязательно)"
)
async def att_loose(interaction: discord.Interaction, screenshot: discord.Attachment, note: str = None):
    await process_loose(interaction, screenshot, note, attack=True)

# Новые команды защиты
@tree.command(name="def_win", description="Победа в защите (точки не меняются)")
@app_commands.describe(
    screenshot="Скриншот с подтверждением",
    note="Дополнительная заметка (необязательно)"
)
async def def_win(interaction: discord.Interaction, screenshot: discord.Attachment, note: str = None):
    await process_win(interaction, screenshot, note, attack=False)

@tree.command(name="def_loose", description="Поражение в защите (-1 точка)")
@app_commands.describe(
    screenshot="Скриншот с подтверждением",
    note="Дополнительная заметка (необязательно)"
)
async def def_loose(interaction: discord.Interaction, screenshot: discord.Attachment, note: str = None):
    await process_loose(interaction, screenshot, note, attack=False)

# Общие функции обработки
async def process_win(interaction: discord.Interaction, screenshot: discord.Attachment, note: str, attack: bool):
    if not await has_permission(interaction):
        return
    
    if not screenshot.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
        await interaction.response.send_message("❌ Прикрепите скриншот в формате PNG/JPG/JPEG!", ephemeral=True)
        return

    await interaction.response.defer()
    
    conn = sqlite3.connect('game_stats.db')
    c = conn.cursor()
    
    # Получаем текущее количество территорий
    c.execute('''INSERT OR IGNORE INTO stats (guild_id) VALUES (?)''', (interaction.guild.id,))
    c.execute('''SELECT territories FROM stats WHERE guild_id = ?''', (interaction.guild.id,))
    current_territories = c.fetchone()[0]
    
    # Для атаки увеличиваем территории (макс 18)
    if attack:
        new_territories = min(current_territories + 1, 18)
        action_type = "att_win"
    else:
        new_territories = current_territories
        action_type = "def_win"
    
    # Обновляем статистику
    c.execute('''UPDATE stats SET 
                wins = wins + 1,
                territories = ?
                WHERE guild_id = ?''',
             (new_territories, interaction.guild.id))
    
    # Добавляем в историю
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''INSERT INTO history 
                (guild_id, user_id, action_type, timestamp, screenshot_url, territories, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
             (interaction.guild.id, interaction.user.id, action_type, 
              timestamp, screenshot.url, new_territories, note))
    
    conn.commit()
    
    # Отправляем в канал статистики
    await send_to_stats_channel(
        interaction=interaction,
        conn=conn,
        title="🟢 Победа в атаке!" if attack else "🟢 Победа в защите!",
        color=discord.Color.green(),
        territories=new_territories,
        note=note,
        screenshot_url=screenshot.url,
        emoji="😎"
    )
    
    conn.close()
    await interaction.followup.send(
        f"✅ {'Атакующая' if attack else 'Защитная'} победа зарегистрирована! Точки: {new_territories}",
        ephemeral=True
    )

async def process_loose(interaction: discord.Interaction, screenshot: discord.Attachment, note: str, attack: bool):
    if not await has_permission(interaction):
        return
    
    if not screenshot.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
        await interaction.response.send_message("❌ Прикрепите скриншот в формате PNG/JPG/JPEG!", ephemeral=True)
        return

    await interaction.response.defer()
    
    conn = sqlite3.connect('game_stats.db')
    c = conn.cursor()
    
    # Получаем текущее количество территорий
    c.execute('''INSERT OR IGNORE INTO stats (guild_id) VALUES (?)''', (interaction.guild.id,))
    c.execute('''SELECT territories FROM stats WHERE guild_id = ?''', (interaction.guild.id,))
    current_territories = c.fetchone()[0]
    
    # Для защиты уменьшаем территории (мин 0)
    if not attack:
        new_territories = max(current_territories - 1, 0)
        action_type = "def_loose"
    else:
        new_territories = current_territories
        action_type = "att_loose"
    
    # Обновляем статистику
    c.execute('''UPDATE stats SET 
                losses = losses + 1,
                territories = ?
                WHERE guild_id = ?''',
             (new_territories, interaction.guild.id))
    
    # Добавляем в историю
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''INSERT INTO history 
                (guild_id, user_id, action_type, timestamp, screenshot_url, territories, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
             (interaction.guild.id, interaction.user.id, action_type, 
              timestamp, screenshot.url, new_territories, note))
    
    conn.commit()
    
    # Отправляем в канал статистики
    await send_to_stats_channel(
        interaction=interaction,
        conn=conn,
        title="🔴 Поражение в атаке!" if attack else "🔴 Поражение в защите!",
        color=discord.Color.red(),
        territories=new_territories,
        note=note,
        screenshot_url=screenshot.url,
        emoji="😭"
    )
    
    conn.close()
    await interaction.followup.send(
        f"⚠️ {'Атакующее' if attack else 'Защитное'} поражение зарегистрировано! Территории: {new_territories}",
        ephemeral=True
    )

async def send_to_stats_channel(interaction, conn, title, color, territories, note, screenshot_url, emoji):
    c = conn.cursor()
    c.execute('SELECT stats_channel_id FROM bot_settings WHERE guild_id = ?', (interaction.guild.id,))
    channel_id = c.fetchone()
    
    if channel_id and channel_id[0]:
        channel = bot.get_channel(channel_id[0])
        if channel:
            embed = discord.Embed(
                title=title,
                description=f"Добавлено пользователем {interaction.user.mention}",
                color=color,
                timestamp=datetime.datetime.now()
            )
            embed.add_field(name="Текущие точки", value=str(territories))
            if note:
                embed.add_field(name="Заметка", value=note, inline=False)
            embed.set_image(url=screenshot_url)
            message = await channel.send(embed=embed)
            await message.add_reaction(emoji)

# ... (остальной код бота остается без изменений)

load_dotenv()
bot.run(os.getenv("DISCORD_TOKEN")))

