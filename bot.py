import os
import json
import threading
from datetime import datetime

import discord
from discord.ext import commands
from aiohttp import web

# ================== CONFIG ==================
TOKEN = os.getenv("TOKEN")  # imposta su Render: Environment -> Add Variable (Key=TOKEN, Value=tuo token)

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
intents.message_content = True   # attivalo anche nel Developer Portal (Bot -> Privileged Gateway Intents)

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

db = load_db()  # { order_id: {"stato": "🆕", "dettagli": "...", "messages":[{"channel_id":int,"message_id":int}]} }

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

    for e in ["📤", "📦", "🚚", "✅", "⚠️", "❌"]:
        try:
            await msg.add_reaction(e)
        except Exception:
            pass

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
    print(f"✅ Bot avviato come {bot.user}")

@bot.command(name="nuovo")
async def nuovo(ctx, order_id: str, *, dettagli: str):
    # Crea la prima copia nel canale dove scrivi il comando
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

    # Assicura anche la copia nel canale di fase corrente
    await ensure_copy_in_phase_channel(order_id, dettagli, stato)

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return
    msg = reaction.message
    emoji = str(reaction.emoji)

    if not is_order_message(msg.content):
        return
    if emoji not in STATI:
        return

    # Prima riga: "EMOJI **ORD-...**"
    first = msg.content.splitlines()[0].strip()
    if "**" not in first:
        return
    try:
        order_id = first.split("**")[1].strip()
    except Exception:
        return

    # Dettagli = righe tra la seconda riga e "Stato attuale"
    lines = msg.content.splitlines()
    dettagli_lines = []
    for line in lines[1:]:
        if line.startswith("**Stato attuale:**"):
            break
        dettagli_lines.append(line)
    dettagli = "\n".join(dettagli_lines).strip()

    await ensure_copy_in_phase_channel(order_id, dettagli, emoji)
    await update_all_copies(order_id, dettagli, emoji)

# ---------------- Keep-Alive HTTP (Render Free) ---------------
# Render Free Web Service richiede che l'app "ascolti" su una porta ($PORT).
# Avviamo un micro-server aiohttp su un thread dedicato così il bot resta attivo.
async def handle(request):
    return web.Response(text="Bot MaxMart attivo ✅")

def run_web():
    app = web.Application()
    app.add_routes([web.get("/", handle)])
    port = int(os.getenv("PORT", "10000"))  # Render passa $PORT; fallback 10000
    web.run_app(app, host="0.0.0.0", port=port)

# Avvio del micro-server HTTP in parallelo
threading.Thread(target=run_web, daemon=True).start()

# ---------------- Avvio del bot ----------------
if not TOKEN:
    print("❌ ERRORE: variabile d'ambiente TOKEN mancante. Imposta TOKEN su Render (Environment).")
else:
    bot.run(TOKEN)
