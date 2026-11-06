import os, re, io, json
from urllib.request import urlopen, Request
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

BOT_TOKEN = os.environ.get('BOT_TOKEN', '9204868114:AAExpr8eERnSSc2UIOYP1KmW2kxlSedBofs')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36'

def fetch(url):
    req = Request(url, headers={'User-Agent': UA})
    return urlopen(req, timeout=30).read().decode('utf-8', 'ignore')

def parse_traktrain(url):
    html = fetch(url)
    m = re.search(r"var AWS_BASE_URL\s*=\s*['\"]([^'\"]+)['\"]", html)
    if not m:
        return None, 'AWS_BASE_URL не найден — это не страница артиста/кита'
    base = m.group(1)

    soup = BeautifulSoup(html, 'html.parser')
    keys = ['title', 'beatName', 'beat_name', 'trackName', 'track_name', 'name',
            'kitName', 'kit_name', 'sampleName', 'sample_name']
    generic = {'mp3 track', 'wav track', 'mp3', 'wav', 'track', 'untitled', 'download'}

    items, seen = [], set()
    for el in soup.select('[data-player-info]'):
        try:
            info = json.loads(el['data-player-info'])
        except Exception:
            continue
        src = info.get('src')
        if not src or src in seen:
            continue
        seen.add(src)
        name = None
        for k in keys:
            v = info.get(k)
            if isinstance(v, str) and v.strip() and v.strip().lower() not in generic:
                name = v.strip(); break
        if not name:
            t = el.find(class_=re.compile('(title|name|kit)', re.I))
            if t and t.get_text(strip=True):
                name = t.get_text(strip=True)
        if not name:
            name = 'item_' + str(len(items) + 1)
        ext = '.mp3'
        mext = re.search(r'\.(mp3|wav|zip|rar|7z|aif|aiff)(\?|$)', src, re.I)
        if mext:
            ext = '.' + mext.group(1).lower()
        items.append({'name': name, 'src': src, 'ext': ext})

    for a in soup.find_all('a', href=True):
        href = a['href']
        if re.search(r'\.(zip|rar|7z)(\?|$)', href, re.I) and href not in seen:
            seen.add(href)
            label = a.get_text(strip=True) or os.path.basename(href.split('?')[0])
            ext = '.' + re.search(r'\.(zip|rar|7z)', href, re.I).group(1).lower()
            items.append({'name': label, 'src': href, 'ext': ext})

    return {'base': base, 'items': items}, None

def download_file(base, src, ext):
    url = (base.rstrip('/') + '/' + src.lstrip('/')) if src.startswith('/') else base + src
    for h in [
        {'User-Agent': UA, 'Referer': 'https://traktrain.com/'},
        {'User-Agent': UA, 'Referer': 'https://www.traktrain.com/'},
        {'User-Agent': UA},
    ]:
        try:
            data = urlopen(Request(url, headers=h), timeout=60).read()
            if data:
                return data
        except Exception:
            continue
    return None

# ---- Telegram handlers ----

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Кидай ссылку traktrain.com/... — пришлю список файлов кнопками.\n"
        "Или прямую ссылку на mp3/wav/zip — скачаю сразу."
    )

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()
    if not text.startswith('http'):
        await update.message.reply_text("Нужна ссылка, начинающаяся с http")
        return

    # прямая ссылка на файл
    if re.search(r'\.(mp3|wav|zip|rar|7z|aif|aiff)(\?|$)', text, re.I) and 'traktrain.com/t/' not in text:
        await update.message.reply_text("Качаю файл...")
        ext = '.' + re.search(r'\.(mp3|wav|zip|rar|7z|aif|aiff)', text, re.I).group(1).lower()
        data = None
        for h in [{'User-Agent': UA, 'Referer': 'https://traktrain.com/'}, {'User-Agent': UA}]:
            try:
                data = urlopen(Request(text, headers=h), timeout=60).read()
                if data: break
            except Exception: pass
        if not data:
            await update.message.reply_text("Не удалось скачать файл")
            return
        name = os.path.basename(text.split('?')[0]) or ('file' + ext)
        await update.message.reply_document(document=io.BytesIO(data), filename=name)
        return

    if 'traktrain.com' not in text:
        await update.message.reply_text("Поддерживается только traktrain.com")
        return

    await update.message.reply_text("Парсю страницу...")
    try:
        parsed, err = parse_traktrain(text)
    except Exception as e:
        await update.message.reply_text("Ошибка загрузки: " + str(e))
        return

    if err:
        await update.message.reply_text(err)
        return

    items = parsed['items']
    if not items:
        await update.message.reply_text("Файлы не найдены — возможно, только платное")
        return

    # сохраняем в контексте чата
    ctx.user_data['base'] = parsed['base']
    ctx.user_data['items'] = items

    # кнопки по 10 на сообщение
    buttons = []
    for i, it in enumerate(items[:40]):
        label = (it['name'][:40] + ' ' + it['ext'])
        buttons.append([InlineKeyboardButton(label, callback_data=f"dl:{i}")])
    buttons.append([InlineKeyboardButton("Скачать все (" + str(len(items)) + ")", callback_data="all")])
    await update.message.reply_text(
        "Найдено " + str(len(items)) + " файлов. Жми кнопку:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    base = ctx.user_data.get('base')
    items = ctx.user_data.get('items', [])
    if not base or not items:
        await q.message.reply_text("Сессия истекла, кинь ссылку заново")
        return

    data_cb = q.data
    if data_cb == 'all':
        await q.message.reply_text("Качаю " + str(len(items)) + " файлов...")
        for i, it in enumerate(items):
            data = download_file(base, it['src'], it['ext'])
            if not data:
                await q.message.reply_text("Не удалось: " + it['name'])
                continue
            safe = re.sub(r'[^\w\s\-()]', '', it['name']).strip() or ('file' + it['ext'])
            if not safe.lower().endswith(it['ext']):
                safe += it['ext']
            await q.message.reply_document(document=io.BytesIO(data), filename=safe)
        return

    if data_cb.startswith('dl:'):
        i = int(data_cb.split(':')[1])
        if i >= len(items):
            await q.message.reply_text("Файл не найден")
            return
        it = items[i]
        await q.message.reply_text("Качаю: " + it['name'])
        data = download_file(base, it['src'], it['ext'])
        if not data:
            await q.message.reply_text("Не удалось скачать")
            return
        safe = re.sub(r'[^\w\s\-()]', '', it['name']).strip() or ('file' + it['ext'])
        if not safe.lower().endswith(it['ext']):
            safe += it['ext']
        await q.message.reply_document(document=io.BytesIO(data), filename=safe)

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(CallbackQueryHandler(on_callback))
    print("Бот запущен")
    app.run_polling()

if __name__ == '__main__':
    main()
