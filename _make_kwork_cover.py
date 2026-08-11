"""Обложка Kwork: половина ИНН + имя закрыты, проверки обрезаны."""

from PIL import Image, ImageDraw, ImageFilter

SRC = r"C:\Users\User\.cursor\projects\c-Users-User-OneDrive-Desktop-GOLD\assets\c__Users_User_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images_photo_2026-07-23_13-47-59-672e0cf7-19cb-4bf8-83f3-05988c73085a.png"
OUT = r"C:\Users\User\OneDrive\Desktop\GOLD\kwork_cover_card.png"


def solid_blur(im: Image.Image, box, fill, blur: int = 10) -> None:
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(im.width, x1), min(im.height, y1)
    crop = im.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(blur))
    im.paste(crop, (x0, y0))
    d = ImageDraw.Draw(im)
    d.rectangle((x0, y0, x1, y1), fill=fill)


def main() -> None:
    im = Image.open(SRC).convert("RGB")

    # Вторая половина ИНН
    solid_blur(im, (835, 168, 950, 204), fill=(232, 248, 210), blur=14)
    # Название организации
    solid_blur(im, (70, 222, 340, 262), fill=(255, 255, 255), blur=14)

    # Обрезать проверки/дисциплину — оставить шапку + ИНН + начало карточки
    # «Членство в СРО:» ~ y 268–300; ниже — проверки
    crop_bottom = 315
    im = im.crop((0, 0, im.width, crop_bottom))

    # Чуть расширить холст вниз белым/фоном, чтобы не выглядело обрезанным резко
    pad = 24
    canvas = Image.new("RGB", (im.width, im.height + pad), (236, 242, 228))
    canvas.paste(im, (0, 0))
    # нижняя полоска как продолжение чата
    d = ImageDraw.Draw(canvas)
    d.rectangle((48, im.height - 8, 820, im.height + 8), fill=(255, 255, 255))

    canvas.save(OUT, "PNG")
    print(f"saved {OUT} size={canvas.size}")


if __name__ == "__main__":
    main()
