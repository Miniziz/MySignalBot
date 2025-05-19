
import logging
import asyncio
import json
import websockets
import ta
import pandas as pd
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import ParseMode
import os
from collections import deque
from datetime import datetime

API_TOKEN = os.getenv('API_TOKEN')
USER_ID = int(os.getenv('USER_ID'))

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

symbols = ['ETHUSDT', 'BTCUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT', 'DOGEUSDT', 'MATICUSDT', 'AVAXUSDT', 'DOTUSDT']
price_data = {sym: deque(maxlen=100) for sym in symbols}
active_positions = {}
recent_signals = deque(maxlen=10)
bot_active = True

@dp.message_handler(commands=["start"])
async def start_cmd(message: types.Message):
    if message.from_user.id == USER_ID:
        await message.reply("Бот активен. Реальное время. Следим за 10 монетами.")

@dp.message_handler(commands=["status"])
async def status_cmd(message: types.Message):
    if message.from_user.id == USER_ID:
        if not active_positions:
            await message.reply("Нет активных сигналов.")
        else:
            msg = "Активные сигналы:\n"
            for sym, data in active_positions.items():
                msg += f"• {sym}: вход {data['entry']:.4f}, TP {data['tp']:.4f}, SL {data['sl']:.4f}\n"
            await message.reply(msg)

@dp.message_handler(commands=["ping"])
async def ping_cmd(message: types.Message):
    if message.from_user.id == USER_ID:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        await message.reply(f"✅ Бот работает. Время UTC: {now}")

@dp.message_handler(commands=["pause"])
async def pause_cmd(message: types.Message):
    global bot_active
    if message.from_user.id == USER_ID:
        bot_active = False
        await message.reply("⏸️ Бот поставлен на паузу. Сигналы временно отключены.")

@dp.message_handler(commands=["resume"])
async def resume_cmd(message: types.Message):
    global bot_active
    if message.from_user.id == USER_ID:
        bot_active = True
        await message.reply("▶️ Бот возобновил работу. Сигналы снова активны.")

@dp.message_handler(commands=["signals"])
async def signals_cmd(message: types.Message):
    if message.from_user.id == USER_ID:
        if not recent_signals:
            await message.reply("Пока не было ни одного сигнала.")
        else:
            msg = "Последние сигналы:\n"
            for sig in list(recent_signals)[::-1]:
                msg += f"• {sig}\n"
            await message.reply(msg)

async def send_keepalive():
    while True:
        now = datetime.utcnow().strftime("%H:%M:%S")
        logging.info(f"[KEEPALIVE] Bot alive at {now}")
        await asyncio.sleep(1200)

async def bybit_ws():
    url = "wss://stream.bybit.com/v5/public/linear"
    subscribe_msg = {
        "op": "subscribe",
        "args": [f"kline.1m.{sym}" for sym in symbols]
    }

    async with websockets.connect(url) as ws:
        await ws.send(json.dumps(subscribe_msg))
        while True:
            try:
                msg = await ws.recv()
                data = json.loads(msg)
                if not bot_active:
                    continue
                if 'data' in data and isinstance(data['data'], dict):
                    kline = data['data']
                    symbol = kline['symbol']
                    close = float(kline['close'])
                    price_data[symbol].append(close)

                    if len(price_data[symbol]) >= 14:
                        series = pd.Series(price_data[symbol])
                        rsi = ta.momentum.RSIIndicator(series).rsi().iloc[-1]
                        if symbol not in active_positions and rsi < 30:
                            tp = close * 1.04
                            sl = close * 0.96
                            active_positions[symbol] = {'entry': close, 'tp': tp, 'sl': sl}
                            now = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
                            signal_text = f"{now} | {symbol} | Вход: ${close:.4f}"
                            recent_signals.append(signal_text)
                            msg = (
                                f"📉 <b>Сигнал по {symbol}</b>\n"
                                f"Цена входа: ${close:.4f}\n"
                                f"RSI: {rsi:.2f} (перепроданность)\n\n"
                                f"🎯 TP: ${tp:.4f}\n"
                                f"❌ SL: ${sl:.4f}"
                            )
                            await bot.send_message(USER_ID, msg, parse_mode=ParseMode.HTML)

                        elif symbol in active_positions:
                            if close >= active_positions[symbol]['tp']:
                                await bot.send_message(USER_ID, f"✅ <b>{symbol}</b> достиг Take-Profit!", parse_mode=ParseMode.HTML)
                                del active_positions[symbol]
                            elif close <= active_positions[symbol]['sl']:
                                await bot.send_message(USER_ID, f"❌ <b>{symbol}</b> достиг Stop-Loss!", parse_mode=ParseMode.HTML)
                                del active_positions[symbol]

            except Exception as e:
                logging.error(f"Ошибка WebSocket: {e}")
                await asyncio.sleep(5)

def start_bot():
    loop = asyncio.get_event_loop()
    loop.create_task(bybit_ws())
    loop.create_task(send_keepalive())
    executor.start_polling(dp, skip_updates=True)
