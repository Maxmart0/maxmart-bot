import os
import json
import asyncio
from datetime import datetime

import discord
from discord.ext import commands
from aiohttp import web

# ================== CONFIG ==================
TOKEN = os.getenv("TOKEN")  # su Render: Environment -> add variable TOKEN = <tuo token>

# ID CANALI (i tuoi)
ID_ORDINI_FORNITORI   = 1437442516017479750  # #ordini-da-fare-ai-fornitori
ID_MAGAZZINO          = 1437442556551233536  # #merce-in-arrivo-o-in-magazzino
ID_SPEDIZIONI         = 1437442600716992634  # #spedizioni-e-ritiri-clienti
ID_COMPLETATI         = 1437442636620234812  # #ordini-completati
ID_PROBLEMI           = 1437442673316335728  # #anomalie-e-problemi

DATAFILE = "ordini.json"
# ============================================

# --------- Discord intents / bot ----------
intents = discord.Intents.default()
intents.message_content = True   # abilitato anche nel Developer Portal
intents.messages = True
intents.reactions = True
intents.guilds = True

bot = commands.Bot(command_prefix="/", intents=intents)

STATI = {
    "🆕": "🆕 Da inviare al fornitore",
    "📤": "📤 Inviato al fornitore",
    "📦": "📦 Arrivato in magazzino",
    "🚚": "🚚 Spedito / Pronto al ritiro",
    "✅": "✅ Completato (consegnato/ritirato)",
    "⚠️": "⚠️ Anomalia",
    "❌": "❌ Problema/Annullato"
}

FASE_TO_CHANNEL = {
    "🆕": ID_ORDINI_FORNITORI,
    "📤": ID_ORDINI_FORNITORI,
    "📦": ID_MAGAZZINO,
    "🚚": ID_SPEDIZIONI,
    "✅": ID_COMPLETATI,
    "⚠️": ID_PROBLEMI,
    "❌": ID_PROBLEMI
}

# ------------- Utils / storage -------------
def checklist_per(emoji: str) -> str:
    if emoji == "🆕":
        return ("- [ ] Da inviare al fornitore\n"
                "- [ ] Inviato al fornitore\n"
                "- [ ] Arrivato in magazzino\n"
                "- [ ] Spedito / Pronto al ritiro\n"
                "- [ ] Completato")
    if emoji == "📤":
        return ("- [x] Da inviare al fornitore\n"
                "- [x] Inviato al fornitore\n"
                "- [ ] Arrivato in magazzino\n"
                "- [ ] Spedito / Pronto al ritiro\n"
                "- [ ] Completato")
    if emoji == "📦":
        return ("- [x] Da inviare al fornitore\n"
                "- [x] Inviato al fornitore\n"
                "- [x] Arrivato in magazzino\n"
                "- [ ] Spedito / Pronto al ritiro\n"
                "- [ ] Completato")
    if emoji == "🚚":
        return ("- [x] Da inviare al fornitore\n"
                "- [x] Inviato al fornitore\n"
                "- [x] Arrivato in magazzino\n"
                "- [x] Spedito / Pronto al ritiro\n"
                "- [ ] Completato")
    if emoji == "✅":
        return ("- [x] Da inviare al fornitore\n"
                "- [x] Inviato al fornitore\n"
                "- [x] Arrivato in magazzino\n"
                "- [x] Spedito / Pronto al ritiro\n"
                "- [x] Completato")
    if emoji == "⚠️":
        return ("- [x] Da inviare al fornitore\n"
                "⚠️ Problema rilevato (in lavorazione)")
    if emoji == "❌":
        return ("❌ Ordine annullato / non evaso")
    return ""

def ora_it():
    return datetime.now().strftime("%d/%m/%Y %H:%M")

def load_db():
    if not os.path.exists(DATAFILE):
        return {}
    try:
        with open(DATAFILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_db(db_obj):
    with open(DATAFILE, "w", encoding="utf-8") as f:
        json.dump(db_obj, f, ensure_ascii=False, indent=2)

db = load_db()

def is_order_message(content: str) -> bool:
    return content and "**Checklist:**" in content

def render(order_id: str, dettagli: str, stato_emoji: str) -> str:
    return (
        f"{stato_emoji} **{order_id}**\n"
        f"{dettagli}\n\n"
        f"**Stato attuale:** {STATI[stato_emoji]}\n"
        f"**Checklist:**\n{checklist_per(stato_emoji)}\n\n"
        f"_Ultimo aggiornamento: {ora_it()}_"
    )

# --------- Sync across phase channels ---------
async def ensure_copy_in_phase_channel(order_id: str, dettagli: str, stato_emoji: str) -> dict:
    channel_id = FASE_TO_CHANNEL[stato_emoji]
    channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)

    record = db.get(order_id, {"stato": "🆕", "messages": [], "dettagli": dettagli})
    target_msg_id = None
    for m in record["messages"]:
        if m["channel_id"] == channel_id:
            target_msg_id = m["message_id"]
            break

    content = render(order_id, dettagli, stato_emoji)

    if target_msg_id:
        try:
            msg = await channel.fetch_message(target_msg_id)
            await msg.edit(content=content)
        except Exception:
            msg = await channel.send(content)
    else:
        msg = await channel.send(content)

    # aggiunge le reazioni di stato sul messaggio “di fase”
    for e in ["📤", "📦", "🚚", "✅", "⚠️", "❌"]:
        try:
            await msg.add_reaction(e)
        except Exception:
            pass

    # aggiorna il record
    updated = False
    for m in record["messages"]:
        if m["channel_id"] == channel_id:
            m["message_id"] = msg.id
            updated = True
            break
    if not updated:
        record["messages"].append({"channel_id": channel_id, "message_id": msg.id})

    record["stato"] = stato_emoji
    record["dettagli"] = dettagli
    db[order_id] = record
    save_db(db)
    return record

async def update_all_copies(order_id: str, dettagli: str, stato_emoji: str):
    if order_id not in db:
        return
    record = db[order_id]
    new_content = render(order_id, dettagli, stato_emoji)
    for m in record.get("messages", []):
        ch = bot.get_channel(m["channel_id"]) or await bot.fetch_channel(m["channel_id"])
        try:
            msg = await ch.fetch_message(m["message_id"])
            await msg.edit(content=new_content)
        except Exception:
            continue
    record["stato"] = stato_emoji
    record["dettagli"] = dettagli
    db[order_id] = record
    save_db(db)

# ----------------- Events/commands -----------------
@bot.event
async def on_ready():
    print(f"✅ Bot avviato come {bot.user} (latency: {bot.latency})")

@bot.command(name="nuovo")
async def nuovo(ctx, order_id: str, *, dettagli: str):
    stato = "🆕"
    content = render(order_id, dettagli, stato)
    msg = await ctx.send(content)
    for e in ["📤", "📦", "🚚", "✅", "⚠️", "❌"]:
        await msg.add_reaction(e)

    record = db.get(order_id, {"stato": stato, "messages": [], "dettagli": dettagli})
    record["messages"].append({"channel_id": ctx.channel.id, "message_id": msg.id})
    record["stato"] = stato
    record["dettagli"] = dettagli
    db[order_id] = record
    save_db(db)

    await ensure_copy_in_phase_channel(order_id, dettagli, stato)

# --------- NUOVO HANDLER: funziona anche sui messaggi vecchi ---------
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """Gestisce i cambi di stato anche su messaggi vecchi (non in cache)."""
    # ignora le reazioni del bot stesso
    if bot.user is None:
        return
    if payload.user_id == bot.user.id:
        return

    emoji = str(payload.emoji)

    # consideriamo solo le emoji di stato
    if emoji not in STATI:
        return

    # recupera canale e messaggio
    channel = bot.get_channel(payload.channel_id) or await bot.fetch_channel(payload.channel_id)
    try:
        msg = await channel.fetch_message(payload.message_id)
    except discord.NotFound:
        return
    except Exception as e:
        print("Errore fetch message:", e)
        return

    # consideriamo solo i messaggi creati dal bot (gli ordini)
    if msg.author.id != bot.user.id:
        return

    content = msg.content or ""
    if not is_order_message(content):
        return

    # debug leggero
    print(f"🔥 Reazione {emoji} su msg {msg.id} nel canale {channel.id}")

    # prima riga: contiene l'ID ordine
    first = content.splitlines()[0].strip()
    if "**" not in first:
        return
    try:
        order_id = first.split("**")[1].strip()
    except Exception:
        return

    # estraiamo i dettagli (fino a **Stato attuale:**)
    lines = content.splitlines()
    dettagli_lines = []
    for line in lines[1:]:
        if line.startswith("**Stato attuale:**"):
            break
        dettagli_lines.append(line)
    dettagli = "\n".join(dettagli_lines).strip()

    # 👇 AGGANCIA ANCHE IL MESSAGGIO CORRENTE AL RECORD DELL'ORDINE
    record = db.get(order_id, {"stato": "🆕", "messages": [], "dettagli": dettagli})
    found_current = False
    for m in record.get("messages", []):
        if m["channel_id"] == channel.id and m["message_id"] == msg.id:
            found_current = True
            break
    if not found_current:
        record.setdefault("messages", []).append({"channel_id": channel.id, "message_id": msg.id})
    record["dettagli"] = dettagli
    db[order_id] = record
    save_db(db)

    # crea/aggiorna la copia nel canale di fase e poi aggiorna tutte le copie
    await ensure_copy_in_phase_channel(order_id, dettagli, emoji)
    await update_all_copies(order_id, dettagli, emoji)

# ---------------- Keep-Alive HTTP (Render Free) ---------------
async def handle(request):
    return web.Response(text="Bot MaxMart attivo ✅")

async def start_web_app():
    app = web.Application()
    app.add_routes([web.get("/", handle)])
    port = int(os.getenv("PORT", "10000"))
    runner = web.AppRunner(app, handle_signals=False)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Web server attivo su 0.0.0.0:{port}")
    return runner

async def main():
    if not TOKEN:
        print("❌ ERRORE: variabile d'ambiente TOKEN mancante. Imposta TOKEN su Render (Environment).")
        return

    # 1) Avvia prima il web server (Render deve vedere la porta aperta)
    runner = await start_web_app()

    # 2) Avvia il bot Discord nello stesso event loop
    try:
        await bot.start(TOKEN)
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
