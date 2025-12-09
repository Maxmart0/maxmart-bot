import os
import json
import time
from datetime import datetime

import discord
from discord.ext import commands

# ================== CONFIG ==================
TOKEN = os.getenv("TOKEN")  # su Render: Environment -> add variable TOKEN = <tuo token>

# ID CANALI (i tuoi)
ID_ORDINI_FORNITORI   = 1437442516017479750  # #ordini-da-fare-ai-fornitori
ID_MAGAZZINO          = 1437442556551233536  # #merce-in-arrivo-o-in-magazzino
ID_SPEDIZIONI         = 1437442600716992634  # #spedizioni-e-ritiri-clienti
ID_COMPLETATI         = 1437442636620234812  # #ordini-completati
ID_PROBLEMI           = 1437442673316335728  # #anomalie-e-problemi

# 👉 ID CANALE #ricerca-stato-ordine
ID_RICERCA            = 1448007555434414210

DATAFILE = "ordini.json"
# ============================================

# --------- Discord intents / bot ----------
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.reactions = True
intents.guilds = True

bot = commands.Bot(command_prefix="/", intents=intents)

STATI = {
    "🆕": "🆕 Da inviare al fornitore",
    "📤": "📤 Inviato al fornitore",
    "📦": "📦 Arrivato in magazzino",
    "🚚": "🚚 Spedito / Pronto al ritiro",
    "⚠️": "⚠️ Anomalia",
    "❌": "❌ Problema/Annullato",
    "✅": "✅ Completato"
}

FASE_TO_CHANNEL = {
    "🆕": ID_ORDINI_FORNITORI,
    "📤": ID_ORDINI_FORNITORI,
    "📦": ID_MAGAZZINO,
    "🚚": ID_SPEDIZIONI,
    "⚠️": ID_PROBLEMI,
    "❌": ID_PROBLEMI,
    "✅": ID_COMPLETATI
}

# ================== STORAGE ==================
def ora_it():
    return datetime.now().strftime("%d/%m/%Y %H:%M")

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
    if emoji == "⚠️":
        return ("⚠️ Anomalia su questo ordine")
    if emoji == "❌":
        return "❌ Ordine annullato / non evaso"
    if emoji == "✅":
        return ("- [x] Da inviare\n"
                "- [x] Inviato\n"
                "- [x] Arrivato\n"
                "- [x] Spedito\n"
                "- [x] Completato")
    return ""

def load_db():
    if not os.path.exists(DATAFILE):
        return {}
    try:
        with open(DATAFILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_db(x):
    with open(DATAFILE, "w", encoding="utf-8") as f:
        json.dump(x, f, ensure_ascii=False, indent=2)

db = load_db()

def is_order_message(text: str):
    return text and "**Checklist:**" in text

def render(order_id, dettagli, emoji):
    return (
        f"{emoji} **{order_id}**\n"
        f"{dettagli}\n\n"
        f"**Stato attuale:** {STATI[emoji]}\n"
        f"**Checklist:**\n{checklist_per(emoji)}\n\n"
        f"_Ultimo aggiornamento: {ora_it()}_"
    )

# ================== ORDER SYNC ==================
async def ensure_copy_in_phase_channel(order_id, dettagli, stato_emoji, create_if_missing):
    channel_id = FASE_TO_CHANNEL[stato_emoji]
    channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)

    record = db.get(order_id, {"messages": [], "stato": stato_emoji, "dettagli": dettagli})

    target_msg_id = None
    for m in record["messages"]:
        if m["channel_id"] == channel_id:
            target_msg_id = m["message_id"]
            break

    content = render(order_id, dettagli, stato_emoji)

    msg = None
    if target_msg_id:
        try:
            msg = await channel.fetch_message(target_msg_id)
            await msg.edit(content=content)
        except:
            msg = None

    if msg is None and create_if_missing:
        msg = await channel.send(content)
        for e in ["📤","📦","🚚","⚠️","❌","✅"]:
            try: await msg.add_reaction(e)
            except: pass

    if msg is None:
        record["stato"] = stato_emoji
        record["dettagli"] = dettagli
        db[order_id] = record
        save_db(db)
        return record

    updated = False
    for m in record["messages"]:
        if m["channel_id"] == channel_id:
            m["message_id"] = msg.id
            updated = True
    if not updated:
        record["messages"].append({"channel_id": channel_id, "message_id": msg.id})

    record["stato"] = stato_emoji
    record["dettagli"] = dettagli
    db[order_id] = record
    save_db(db)
    return record

async def update_all_copies(order_id, dettagli, stato_emoji):
    record = db.get(order_id)
    if not record:
        return
    new_content = render(order_id, dettagli, stato_emoji)
    for m in record["messages"]:
        ch = bot.get_channel(m["channel_id"]) or await bot.fetch_channel(m["channel_id"])
        try:
            msg = await ch.fetch_message(m["message_id"])
            await msg.edit(content=new_content)
        except:
            pass
    record["stato"] = stato_emoji
    record["dettagli"] = dettagli
    db[order_id] = record
    save_db(db)

# ================== COMMANDS ==================
@bot.command(name="nuovo")
async def nuovo(ctx, order_id: str, *, dettagli: str):
    stato = "🆕"
    msg = await ctx.send(render(order_id, dettagli, stato))
    for e in ["📤","📦","🚚","⚠️","❌","✅"]:
        await msg.add_reaction(e)

    record = db.get(order_id, {"messages": [], "stato": stato, "dettagli": dettagli})
    record["messages"].append({"channel_id": ctx.channel.id, "message_id": msg.id})
    db[order_id] = record
    save_db(db)

    await ensure_copy_in_phase_channel(order_id, dettagli, stato, create_if_missing=True)


@bot.command(name="ricerca")
async def ricerca(ctx, order_id: str):

    if ctx.channel.id != ID_RICERCA:
        return await ctx.send(f"ℹ️ Usa questo comando solo in <#{ID_RICERCA}>")

    record = db.get(order_id)
    if not record:
        return await ctx.send(f"❌ Nessun ordine trovato con ID `{order_id}`.")

    stato = record["stato"]
    dettagli = record["dettagli"]

    lines = [
        f"🔎 Risultato per ordine **{order_id}**",
        f"**Stato attuale:** {stato} {STATI[stato]}",
        "",
        "**Dettagli:**",
        dettagli,
        ""
    ]

    links = []
    for m in record["messages"]:
        ch = bot.get_channel(m["channel_id"]) or await bot.fetch_channel(m["channel_id"])
        try:
            msg = await ch.fetch_message(m["message_id"])
            links.append(f"- {ch.mention} → [vai al messaggio]({msg.jump_url})")
        except:
            pass

    if links:
        lines.append("**Messaggi collegati:**")
        lines.extend(links)

    await ctx.send("\n".join(lines))


# ================== /aperti ==================
@bot.command(name="aperti")
async def aperti(ctx):
    """Mostra tutti gli ordini NON completati."""
    
    aperti = {k: v for k,v in db.items() if v["stato"] != "✅"}

    if not aperti:
        return await ctx.send("🎉 Non ci sono ordini aperti!")

    gruppi = {
        "🆕": [],
        "📤": [],
        "📦": [],
        "🚚": [],
        "⚠️": [],
        "❌": []
    }

    for oid, rec in aperti.items():
        gruppi[rec["stato"]].append(oid)

    lines = ["📋 **ORDINI APERTI**"]

    for emoji in ["🆕","📤","📦","🚚","⚠️","❌"]:
        if gruppi[emoji]:
