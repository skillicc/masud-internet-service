#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""মাসুদ ইন্টারনেট সার্ভিস — ছবি বানানোর স্ক্রিপ্ট / image build script.

    py tools/build-img.py            # সব ছবি
    py tools/build-img.py hero       # নামের অংশ দিয়ে একটিমাত্র slot

মূল ছবি থাকে _src/ ফোল্ডারে (git-এ যায় না), ফলাফল যায় img/ ফোল্ডারে।
প্রতিটি ছবির জন্য কয়েকটি মাপ + AVIF/WebP তৈরি হয়, যাতে ব্রাউজার নিজের
পর্দার মাপ অনুযায়ী সবচেয়ে ছোট ফাইলটাই নামায়।

দর্শকের বড় অংশ গ্রামের মোবাইল ইন্টারনেটে, তাই প্রতিটি কিলোবাইট গোনা হয়েছে।
"""
import base64
import io
import os
import sys

from PIL import Image, ImageCms, ImageFilter, ImageOps

SRC, OUT = "_src", "img"

# প্রস্থের ধাপ — WIDE: হিরো/অফার/কভারেজ/স্ট্যাট, CARD: ধাপের ছোট কার্ড
WIDE = (480, 720, 1120)
CARD = (360, 540, 720)

# বড় মাপ সবসময় ছোট হয়ে রেন্ডার হয়, তাই সেখানে কম কোয়ালিটিতেও দাগ চোখে পড়ে না
Q = {360: (62, 76), 480: (62, 76), 540: (55, 68), 720: (55, 68), 1120: (48, 60)}

# কোনো ছবি ৭২০w AVIF-এ এর চেয়ে বড় হলে সেটা এই দর্শকের জন্য বেশি জটিল —
# সহজ/কম ডিটেইলের ফ্রেম বেছে নেওয়া ভালো
BUDGET_KB = 30

#       মূল ফাইল       আউট নাম             ধাপ    অনুপাত  ফোকাস-y  jpeg?  lqip?
JOBS = [
    ("hero.jpg",     "hero-family",      WIDE,  3 / 2,  0.40,    True,  True),
    ("offer.jpg",    "offer-router",     WIDE,  3 / 2,  0.50,    False, False),
    ("step1.jpg",    "step-1-call",      CARD,  4 / 3,  0.42,    False, False),
    # মূল ছবিটি খাড়া (2:3) — ফোকাস উপরে রাখলে খুঁটি ও কর্মী দুজনেই ফ্রেমে থাকে
    ("step2.jpg",    "step-2-survey",    CARD,  4 / 3,  0.30,    False, False),
    ("step3.jpg",    "step-3-wifi",      CARD,  4 / 3,  0.45,    False, False),
    ("coverage.jpg", "coverage-village", WIDE,  2 / 1,  0.55,    False, False),
    ("stats.jpg",    "stats-fiber",      WIDE,  2 / 1,  0.50,    False, False),
]

SRGB = ImageCms.createProfile("sRGB")


def load(path):
    """রঙ sRGB-তে আনে, ক্যামেরার ঘোরানো ঠিক করে, বাড়তি তথ্য মুছে দেয়।"""
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)                 # ক্যামেরার rotation ট্যাগ
    icc = im.info.get("icc_profile")
    if icc:                                          # প্রোফাইল রূপান্তর, শুধু ফেলে দেওয়া নয়
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            im = ImageCms.profileToProfile(im, src, SRGB, outputMode="RGB")
        except Exception:
            pass                                     # অদ্ভুত প্রোফাইল হলে sRGB ধরেই চলি
    im = im.convert("RGB")
    # WebP/AVIF প্লাগইন kwarg না পেলে im.info থেকেই প্রোফাইল তুলে নেয় — তাই এখানেই মুছতে হয়
    im.info.pop("icc_profile", None)
    im.info.pop("exif", None)
    return im


def crop_to(im, ratio, focus):
    """ছবিকে নির্দিষ্ট অনুপাতে কাটে। লম্বা হলে focus অনুযায়ী উপর/নিচ ঠিক করে।"""
    w, h = im.size
    if w / h > ratio:                                # বেশি চওড়া — দুপাশ সমান করে কাটি
        nw = int(round(h * ratio))
        x = (w - nw) // 2
        return im.crop((x, 0, x + nw, h))
    nh = int(round(w / ratio))                       # বেশি লম্বা — focus ধরে কাটি
    y = int(round((h - nh) * focus))
    return im.crop((0, y, w, y + nh))


def emit(im, name, widths, jpeg):
    for w in widths:
        h = int(round(w * im.height / im.width))
        r = im.resize((w, h), Image.LANCZOS)
        # ছোট করার পর সামান্য শার্প — নইলে ধোঁয়াটে লাগে
        r = r.filter(ImageFilter.UnsharpMask(radius=0.6, percent=58, threshold=3))
        aq, wq = Q[w]
        r.save("%s/%s-%d.avif" % (OUT, name, w), quality=aq, speed=5)
        r.save("%s/%s-%d.webp" % (OUT, name, w), quality=wq, method=6)
        if jpeg and w == 720:                        # শুধু একটাই JPEG — নিরাপত্তা জাল
            r.save("%s/%s-%d.jpg" % (OUT, name, w), quality=76,
                   optimize=True, progressive=True)
        ka = os.path.getsize("%s/%s-%d.avif" % (OUT, name, w)) / 1024.0
        kw = os.path.getsize("%s/%s-%d.webp" % (OUT, name, w)) / 1024.0
        flag = "   <-- budget-er cheye boro" if ka > BUDGET_KB else ""
        print("  %-24s avif %6.1fK   webp %6.1fK%s" % ("%s-%d" % (name, w), ka, kw, flag))


def lqip(im, name):
    """২৪px চওড়া ঝাপসা ছবি — CSS-এ বসানোর জন্য base64।

    ধীর লাইনে হিরোর জায়গাটা খালি বাক্স না দেখিয়ে রঙিন আভা দেখাবে।
    """
    t = im.resize((24, max(1, int(round(24 * im.height / im.width)))), Image.LANCZOS)
    b = io.BytesIO()
    t.save(b, "WEBP", quality=42)
    raw = b.getvalue()
    print("  LQIP %s: %d bytes" % (name, len(raw)))
    print("  data:image/webp;base64," + base64.b64encode(raw).decode())


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if not os.path.isdir(SRC):
        print("! %s/ folder nei" % SRC)
        return 1
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    missing = 0
    for master, name, ladder, ratio, focus, jpeg, want_lqip in JOBS:
        if only and only not in name:
            continue
        path = os.path.join(SRC, master)
        if not os.path.exists(path):
            print("! pawa jayni: %s" % path)
            missing += 1
            continue
        print(name)
        im = crop_to(load(path), ratio, focus)
        emit(im, name, ladder, jpeg)
        if want_lqip:
            lqip(im, name)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
