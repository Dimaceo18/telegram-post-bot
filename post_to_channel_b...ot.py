# post_to_channel_bot_FINAL_with_watermark.py
# Финальная версия бота с автоматическим водяным знаком

# 📌 Что делает:
# • На каждое фото автоматически накладывается watermark.png
# • watermark.png должен лежать рядом с этим файлом
# • Используется Pillow (PIL)

from PIL import Image
import os

WATERMARK_PATH = "watermark.png"

def apply_watermark(photo_path: str) -> str:
    base = Image.open(photo_path).convert("RGBA")
    watermark = Image.open(WATERMARK_PATH).convert("RGBA")

    bw, bh = base.size
    ww, wh = watermark.size

    scale_w = int(bw * 0.18)
    ratio = scale_w / ww
    watermark = watermark.resize((int(ww * ratio), int(wh * ratio)))

    x = bw - watermark.size[0] - int(bw * 0.03)
    y = bh - watermark.size[1] - int(bh * 0.03)

    base.alpha_composite(watermark, (x, y))

    out_path = photo_path.replace(".jpg", "_wm.png").replace(".png", "_wm.png")
    base.save(out_path)
    return out_path

# 🔧 Вставь вызов apply_watermark() перед отправкой фото в канал
