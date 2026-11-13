"""
反應複誦 Bot（Reaction Echo Bot）

功能：
  當伺服器成員在文字頻道的訊息上加上指定的表情符號（預設 ➕ :heavy_plus_sign:），
  Bot 會透過 Webhook，用「該成員在伺服器上的頭像與暱稱」把那則訊息的文字內容再發送一次。

設定請見同資料夾的 .env（參考 .env.example）。
"""

import asyncio
import logging
import os
import re

import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

# 要偵測的表情符號：
#   - Unicode 表情直接填字元，例如 ➕
#   - 自訂表情填名稱或 ID，例如 plus 或 123456789012345678
#   - 留空 = 任何表情都觸發
TARGET_EMOJI = os.getenv("TARGET_EMOJI", "➕").strip()

# 只在指定頻道運作（以逗號分隔頻道 ID），留空 = 所有頻道
_channels = os.getenv("ALLOWED_CHANNEL_IDS", "").strip()
ALLOWED_CHANNEL_IDS = {int(c) for c in _channels.split(",") if c.strip().isdigit()}

WEBHOOK_NAME = "ReactionEcho"

# Webhook 頭像尺寸：16 / 32 / 64 / 128 / 256 / 512 / 1024 / 2048 / 4096
AVATAR_SIZE = 256

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("reaction-echo")

intents = discord.Intents.default()
intents.guilds = True
intents.guild_messages = True
intents.guild_reactions = True
intents.members = True          # 需在 Developer Portal 開啟 SERVER MEMBERS INTENT
intents.message_content = True  # 需在 Developer Portal 開啟 MESSAGE CONTENT INTENT

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
_commands_synced = False

# 頻道 ID -> Webhook 快取，避免每次都去查詢 / 建立
_webhook_cache: dict[int, discord.Webhook] = {}
_webhook_locks: dict[int, asyncio.Lock] = {}


def emoji_matches(emoji: discord.PartialEmoji) -> bool:
    if not TARGET_EMOJI:
        return True
    if emoji.is_unicode_emoji():
        # 去掉變體選擇符 (U+FE0F) 再比較，避免 ➕ / ➕️ 之類的差異
        return emoji.name.replace("️", "") == TARGET_EMOJI.replace("️", "")
    return TARGET_EMOJI in (emoji.name, str(emoji.id))


def safe_username(name: str) -> str:
    """Webhook 名稱不可包含 'discord'、'clyde'，長度 1~80。"""
    name = re.sub(r"(?i)discord", "Disc0rd", name)
    name = re.sub(r"(?i)clyde", "Clyd3", name)
    name = name.strip() or "成員"
    return name[:80]


async def get_webhook(channel: discord.abc.GuildChannel) -> discord.Webhook:
    """取得（或建立）此頻道中由本 Bot 擁有的 Webhook。"""
    lock = _webhook_locks.setdefault(channel.id, asyncio.Lock())
    async with lock:
        if channel.id in _webhook_cache:
            return _webhook_cache[channel.id]

        for wh in await channel.webhooks():
            if wh.user and wh.user.id == client.user.id and wh.token:
                _webhook_cache[channel.id] = wh
                return wh

        wh = await channel.create_webhook(name=WEBHOOK_NAME, reason="反應複誦 Bot")
        _webhook_cache[channel.id] = wh
        log.info("已在 #%s 建立 Webhook", channel.name)
        return wh


async def verify_still_exists(webhook: discord.Webhook, message_id: int, thread, channel_name: str) -> None:
    """發送 5 秒後檢查訊息是否還在，用來抓出被其他 Bot / AutoMod 刪除的情況。"""
    await asyncio.sleep(5)
    try:
        if thread is not None:
            await webhook.fetch_message(message_id, thread=thread)
        else:
            await webhook.fetch_message(message_id)
    except discord.NotFound:
        log.warning("#%s：複誦的訊息 %s 在 5 秒內被刪除了（可能是其他 Bot 或 AutoMod 刪的，或 Webhook 被刪除）",
                    channel_name, message_id)
    except discord.HTTPException:
        pass


async def invalidate_webhook(channel_id: int, webhook: discord.Webhook) -> None:
    """清除失效的 Webhook 快取（只清掉同一個，避免誤刪別的協程剛建好的新 Webhook）。"""
    lock = _webhook_locks.setdefault(channel_id, asyncio.Lock())
    async with lock:
        cached = _webhook_cache.get(channel_id)
        if cached is not None and cached.id == webhook.id:
            _webhook_cache.pop(channel_id, None)


@client.event
async def on_webhooks_update(channel: discord.abc.GuildChannel):
    """頻道的 Webhook 有變動（例如被手動刪除）時，清掉快取，下次會重新確認。"""
    _webhook_cache.pop(channel.id, None)


# ─────────────────────────── 斜線指令（限管理員） ───────────────────────────

async def sync_commands(guild: discord.Guild) -> None:
    """把指令同步到指定伺服器（伺服器指令會立即生效）。"""
    try:
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
        log.info("已同步斜線指令到伺服器：%s", guild.name)
    except discord.HTTPException as e:
        log.error("同步斜線指令到 %s 失敗：%s", guild.name, e)


@tree.command(name="刪除webhook", description="刪除本 Bot 建立的 Webhook（限管理員）")
@app_commands.describe(範圍="要刪除哪裡的 Webhook")
@app_commands.choices(範圍=[
    app_commands.Choice(name="本頻道", value="channel"),
    app_commands.Choice(name="整個伺服器", value="guild"),
])
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
async def cmd_delete_webhooks(interaction: discord.Interaction, 範圍: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True, thinking=True)

    try:
        if 範圍.value == "guild":
            webhooks = await interaction.guild.webhooks()
        else:
            channel = interaction.channel
            if isinstance(channel, discord.Thread):
                channel = channel.parent
            if channel is None or not hasattr(channel, "webhooks"):
                await interaction.followup.send("這個頻道不支援 Webhook。", ephemeral=True)
                return
            webhooks = await channel.webhooks()
    except discord.Forbidden:
        await interaction.followup.send("Bot 缺少「管理 Webhook」權限，無法讀取 Webhook 列表。", ephemeral=True)
        return

    mine = [wh for wh in webhooks if wh.user and wh.user.id == client.user.id]
    deleted, failed = 0, 0
    for wh in mine:
        try:
            await wh.delete(reason=f"由 {interaction.user} 使用 /刪除webhook")
            _webhook_cache.pop(wh.channel_id, None)
            deleted += 1
        except discord.NotFound:
            _webhook_cache.pop(wh.channel_id, None)
            deleted += 1  # 已經不存在，視同刪除
        except discord.HTTPException:
            failed += 1

    where = "整個伺服器" if 範圍.value == "guild" else "本頻道"
    msg = f"已刪除{where}中本 Bot 建立的 Webhook：{deleted} 個。"
    if failed:
        msg += f"\n有 {failed} 個刪除失敗（可能是權限不足）。"
    if not mine:
        msg = f"{where}中沒有本 Bot 建立的 Webhook。"
    msg += "\n之後有人按反應時，Bot 會自動重新建立 Webhook 並正常運作。"
    log.info("%s 使用 /刪除webhook（%s）：刪除 %d、失敗 %d", interaction.user, where, deleted, failed)
    await interaction.followup.send(msg, ephemeral=True)


@tree.command(name="清除webhook快取", description="清除 Bot 記憶體中所有的 Webhook 快取（限管理員）")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
async def cmd_clear_cache(interaction: discord.Interaction):
    count = len(_webhook_cache)
    _webhook_cache.clear()
    log.info("%s 使用 /清除webhook快取：清除 %d 筆", interaction.user, count)
    await interaction.response.send_message(
        f"已清除 {count} 筆 Webhook 快取。\n"
        "下次發送時 Bot 會重新向 Discord 查詢或建立 Webhook。",
        ephemeral=True,
    )


@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        text = "只有擁有「管理員」權限的成員可以使用這個指令。"
    elif isinstance(error, app_commands.NoPrivateMessage):
        text = "這個指令只能在伺服器中使用。"
    else:
        log.exception("斜線指令發生錯誤", exc_info=error)
        text = "執行指令時發生錯誤，請查看 Bot 的視窗紀錄。"
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


@client.event
async def on_guild_join(guild: discord.Guild):
    await sync_commands(guild)


@client.event
async def on_ready():
    global _commands_synced
    log.info("已登入：%s (ID %s)", client.user, client.user.id)
    if not _commands_synced:
        _commands_synced = True
        for guild in client.guilds:
            await sync_commands(guild)
    log.info("偵測表情：%s", TARGET_EMOJI or "（任何表情）")
    if ALLOWED_CHANNEL_IDS:
        log.info("僅限頻道：%s", ", ".join(map(str, ALLOWED_CHANNEL_IDS)))


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    # 只處理伺服器內的反應
    if payload.guild_id is None or payload.member is None:
        return
    member: discord.Member = payload.member
    if member.bot:
        return
    if not emoji_matches(payload.emoji):
        return

    channel = client.get_channel(payload.channel_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(payload.channel_id)
        except discord.HTTPException:
            return

    # 討論串：Webhook 要建在父頻道，發送時指定 thread
    thread = None
    base_channel = channel
    if isinstance(channel, discord.Thread):
        thread = channel
        base_channel = channel.parent
        if base_channel is None:
            return

    if ALLOWED_CHANNEL_IDS and channel.id not in ALLOWED_CHANNEL_IDS and base_channel.id not in ALLOWED_CHANNEL_IDS:
        return

    if not isinstance(base_channel, (discord.TextChannel, discord.ForumChannel, discord.VoiceChannel, discord.StageChannel)):
        return

    # 先從 Bot 的訊息快取拿（Bot 上線後收到的訊息都在裡面），拿不到才呼叫 API
    message = discord.utils.get(client.cached_messages, id=payload.message_id)
    if message is None:
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            log.warning("讀取訊息失敗 (ID %s)", payload.message_id)
            return

    content = message.content
    if not content:
        # 沒有文字時改送附件連結；兩者都沒有就略過
        content = "\n".join(a.url for a in message.attachments)
    if not content:
        return
    content = content[:2000]

    avatar_url = member.display_avatar.with_size(AVATAR_SIZE).url
    log.info("頭像網址（%s）：%s", member.display_name, avatar_url)

    kwargs = dict(
        content=content,
        username=safe_username(member.display_name),   # 伺服器暱稱（沒有則為全域名稱）
        avatar_url=avatar_url,                         # 伺服器頭像（沒有則為帳號頭像）
        allowed_mentions=discord.AllowedMentions.none(),  # 不會重新 @ 到任何人
        wait=True,  # 等 Discord 回傳實際建立的訊息，才能確認真的有發出去
    )
    if thread is not None:
        kwargs["thread"] = thread

    try:
        # 最多嘗試 2 次：第一次失敗（Webhook 被刪）就立刻重建並補發
        for attempt in range(2):
            webhook = await get_webhook(base_channel)
            try:
                sent = await webhook.send(**kwargs)
                log.info("#%s：以 %s 的身分複誦訊息 %s → 新訊息 %s（Webhook %s）",
                         channel.name, member.display_name, message.id, sent.id, webhook.id)
                asyncio.create_task(verify_still_exists(webhook, sent.id, thread, channel.name))
                break
            except discord.NotFound:
                await invalidate_webhook(base_channel.id, webhook)
                if attempt == 0:
                    log.warning("#%s 的 Webhook 已失效，正在重新建立並補發…", base_channel.name)
                else:
                    log.error("#%s 重建 Webhook 後仍發送失敗", base_channel.name)
    except discord.Forbidden:
        log.error("權限不足：請給 Bot『管理 Webhook』與『讀取訊息歷史』權限（#%s）", base_channel.name)
    except discord.HTTPException as e:
        log.error("發送失敗：%s", e)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("找不到 DISCORD_TOKEN，請先把 .env.example 複製成 .env 並填入 Bot Token。")
    client.run(TOKEN, log_handler=None)
