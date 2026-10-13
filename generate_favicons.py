import math
from PIL import Image, ImageDraw, ImageFont
import os

docs_dir = os.path.join(os.path.dirname(__file__), "docs")

def create_icon(size=180):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # パディングと角丸半径
    pad = int(size * 0.08)
    radius = int(size * 0.28)
    
    # オレンジグラデーション背景
    # 疑似グラデーションをレイヤーで描画
    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg_draw = ImageDraw.Draw(bg)
    bg_draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=radius,
        fill=(249, 115, 22, 255) # #f97316
    )

    # 上部ハイライトグラデーション
    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hl_draw = ImageDraw.Draw(highlight)
    hl_draw.rounded_rectangle(
        [pad + 2, pad + 2, size - pad - 2, int(size * 0.52)],
        radius=radius - 2,
        fill=(255, 255, 255, 40)
    )
    
    # 葉っぱ（右上）
    leaf_w = int(size * 0.22)
    leaf_h = int(size * 0.16)
    lx = size - pad - int(size * 0.18)
    ly = pad - int(size * 0.06)
    bg_draw.ellipse([lx, ly, lx + leaf_w, ly + leaf_h], fill=(16, 185, 129, 255)) # #10b981

    img = Image.alpha_composite(img, bg)
    img = Image.alpha_composite(img, highlight)

    # 「和」の文字描画
    # Windowsの標準フォントを使用 (MS Mincho, Yu Mincho, Meiryo)
    draw_final = ImageDraw.Draw(img)
    font_size = int(size * 0.50)
    
    font_paths = [
        "C:\\Windows\\Fonts\\meiryob.ttc",
        "C:\\Windows\\Fonts\\YuGothB.ttc",
        "C:\\Windows\\Fonts\\meiryo.ttc",
        "C:\\Windows\\Fonts\\msgothic.ttc"
    ]
    font = None
    for p in font_paths:
        if os.path.exists(p):
            try:
                font = ImageFont.truetype(p, font_size)
                break
            except Exception:
                continue
    if not font:
        font = ImageFont.load_default()

    # 中央配置
    text = "和"
    bbox = draw_final.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1] + int(size * 0.02)

    # ドロップシャドウ
    draw_final.text((tx, ty + int(size * 0.02)), text, font=font, fill=(154, 52, 18, 120))
    # 白文字
    draw_final.text((tx, ty), text, font=font, fill=(255, 255, 255, 255))

    return img

# 180x180 (Apple touch icon)
icon180 = create_icon(180)
icon180.save(os.path.join(docs_dir, "apple-touch-icon.png"), "PNG")

# 64x64 (Favicon PNG)
icon64 = create_icon(64)
icon64.save(os.path.join(docs_dir, "favicon.png"), "PNG")

print("Favicon PNGs created successfully!")
