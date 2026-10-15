import streamlit as st
import json
import requests
import base64
from io import BytesIO
from PIL import Image, ImageOps, ImageStat
import time
import re

# --- 1. CONFIGURATION ---
st.set_page_config(layout="wide", page_title="Ring & Jewelry AI Generator")

# --- 2. ฟังก์ชันตรวจสอบรหัสผ่าน (คงเดิม) ---
def check_password():
    if "my_app_password" not in st.secrets:
        st.error("❌ ยังไม่ได้ตั้งค่ารหัสผ่าน! กรุณาไปที่ Manage App > Settings > Secrets แล้วเพิ่ม: my_app_password = '...'", icon="⚠️")
        st.stop()

    def password_entered():
        if st.session_state["password"] == st.secrets.get("my_app_password"):
            st.session_state["password_correct"] = True
            if "password" in st.session_state:
                del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("กรุณาใส่รหัสผ่านเพื่อใช้งาน", type="password", on_change=password_entered, key="password")
        return False
    elif st.session_state["password_correct"]:
        return True
    else:
        st.text_input("กรุณาใส่รหัสผ่านเพื่อใช้งาน", type="password", on_change=password_entered, key="password")
        st.error("😕 รหัสผ่านไม่ถูกต้อง")
        return False

# --- 3. ส่วนเริ่มทำงานของแอพ ---
if not check_password():
    st.stop()

# --- MODEL CONFIG (เช็คล่าสุด 2026-10-15 จาก ai.google.dev/gemini-api/docs/deprecations) ---
# - gemini-3-pro-image-preview (ตัวเดิม) ถึงกำหนดปิดตั้งแต่ 2026-06-25 → ตัวแทนคือ gemini-3-pro-image (GA)
# - gemini-1.5-flash (ตัวเดิมของ SEO) ถูกปิดไปแล้ว → SEO ล้มทุกครั้งแล้วใช้ชื่อไฟล์สำรองเงียบ ๆ
# max_fidelity_refs = จำนวนรูปอ้างอิงที่โมเดลรักษารายละเอียดได้แม่น (API รับรวมสูงสุด 14 รูป)
IMAGE_MODELS = {
    "gemini-3-pro-image": {
        "label": "Nano Banana Pro — สมจริงสุด ลายสลัก/ตัวอักษรแม่นสุด (~$0.134/รูป)",
        "max_fidelity_refs": 6,
        "thinking_level": None,  # Pro คิดเองเสมอ ปรับไม่ได้
    },
    "gemini-nano-banana-2.1": {
        "label": "Nano Banana 2.1 — ใหม่สุด (ต.ค. 2026) ถูกกว่า ~3-4 เท่า (~$0.05/รูป 2K)",
        "max_fidelity_refs": 10,
        "thinking_level": "high",
    },
}
DEFAULT_IMAGE_MODEL = "gemini-3-pro-image"
MODEL_SEO_GEN = "gemini-3.8-flash"  # For generating SEO text (Fast & Cheap)
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
MAX_REFS_TOTAL = 14       # ลิมิตรูปอ้างอิงต่อ 1 request ของ API
AUTO_PICK_PER_ITEM = 2    # Fetch แล้วติ๊กรูปสินค้าเดี่ยว (พื้นสว่าง) ให้อัตโนมัติชิ้นละกี่รูป
SHOPIFY_API_VERSION = "2026-04"

# --- HELPER FUNCTIONS (คงเดิม) ---
def clean_key(value):
    if value is None: return ""
    return str(value).strip().replace(" ", "").replace('"', "").replace("'", "").replace("\n", "")

def safe_st_image(url, width=None, caption=None):
    if not url: return
    try:
        clean_url = str(url).strip().replace(" ", "").replace("\n", "")
        if clean_url.startswith("http"):
            st.image(clean_url, width=width, caption=caption)
    except Exception:
        st.warning("⚠️ Image unavailable")

def reset_app_state():
    """ฟังก์ชันสำหรับล้างค่าทั้งหมดใน Form รวมทั้งรูปที่ Fetch มาจาก Shopify"""
    st.session_state.generated_result = None
    st.session_state.generated_mime = None
    # ล้างช่อง edit prompt ด้วย
    if "result_edit_prompt" in st.session_state:
         del st.session_state["result_edit_prompt"]

    keys_to_clear = []
    for key in st.session_state.keys():
        if (key.startswith("upload_") or
            key.startswith("var_") or
            key.startswith("edit_prompt_area_") or # แก้ให้ตรงกับ key ที่ใช้จริง
            key.startswith("fetch_") or            # fetch_shop_ / fetch_meta_ / fetch_auto_ / fetch_nonce_
            key.startswith("sel_") or              # checkbox เลือกรูปอ้างอิง
            key.startswith("inp_") or
            key == "prev_style_id"):
            keys_to_clear.append(key)

    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]

# --- IMAGE HELPERS ---
def normalize_image(img):
    """หมุนตาม EXIF + แปลงเป็น RGB (PNG พื้นโปร่งใสวางบนพื้นขาว ไม่ให้กลายเป็นพื้นดำ)"""
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img

def pil_to_jpeg_bytes(img, max_side=1536, quality=92):
    """ย่อสำเนา (ไม่แตะรูปต้นฉบับใน session) แล้วแปลงเป็น JPEG"""
    img = normalize_image(img).copy()
    img.thumbnail((max_side, max_side))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()

def image_bytes_to_jpeg(image_bytes, quality=92):
    """รูปจาก Gemini อาจเป็น PNG → แปลงเป็น JPEG ก่อนส่ง SEO / อัปโหลด"""
    img = normalize_image(Image.open(BytesIO(image_bytes)))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()

def looks_like_packshot(img):
    """รูปสินค้าเดี่ยวพื้นขาว/สว่าง = True · รูปนายแบบ/พื้นมืด = False (ดูความสว่างของขอบภาพ)"""
    try:
        small = img.convert("L").resize((64, 64))
        b = 4
        strips = [small.crop((0, 0, 64, b)), small.crop((0, 64 - b, 64, 64)),
                  small.crop((0, 0, b, 64)), small.crop((64 - b, 0, 64, 64))]
        return sum(ImageStat.Stat(s).mean[0] for s in strips) / 4 >= 180
    except Exception:
        return True

def default_pick(images, n=AUTO_PICK_PER_ITEM):
    """เลือกรูปสินค้าเดี่ยว n รูปแรก (ตามลำดับใน Shopify) · ถ้าไม่มีรูปพื้นสว่างเลย ใช้ n รูปแรก"""
    packshots = [i for i, img in enumerate(images) if looks_like_packshot(img)]
    return packshots[:n] if packshots else list(range(min(n, len(images))))

def image_part(image_bytes, mime="image/jpeg"):
    return {"inlineData": {"mimeType": mime, "data": base64.b64encode(image_bytes).decode("utf-8")}}

def detect_mime(image_bytes, fallback="image/png"):
    try:
        fmt = (Image.open(BytesIO(image_bytes)).format or "").upper()
        return {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(fmt, fallback)
    except Exception:
        return fallback

# --- SHOPIFY HELPERS ---
def _shop_domain(shop_url):
    shop_url = shop_url.replace("https://", "").replace("http://", "").strip().rstrip("/")
    if not shop_url.endswith(".myshopify.com"):
        shop_url += ".myshopify.com"
    return shop_url

def get_shopify_product_images(shop_url, access_token, product_id):
    url = f"https://{_shop_domain(shop_url)}/admin/api/{SHOPIFY_API_VERSION}/products/{product_id}/images.json"

    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            images_data = data.get("images", [])

            pil_images = []
            for img_info in images_data:
                src = img_info.get("src")
                if src:
                    img_resp = requests.get(src, timeout=30)
                    if img_resp.status_code == 200:
                        pil_images.append(normalize_image(Image.open(BytesIO(img_resp.content))))
            if not pil_images:
                return None, "สินค้านี้ไม่มีรูป"
            return pil_images, None
        else:
            return None, f"Shopify Error {response.status_code}"
    except Exception as e:
        return None, f"Connection Error: {str(e)}"

def get_target_product_details(shop_url, access_token, product_id):
    url = f"https://{_shop_domain(shop_url)}/admin/api/{SHOPIFY_API_VERSION}/products/{product_id}.json?fields=title,handle"
    headers = {"X-Shopify-Access-Token": access_token, "Content-Type": "application/json"}

    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            p = res.json().get("product", {})
            title = p.get("title", "")
            handle = p.get("handle", "")
            return title, handle
        else:
            return None, None
    except Exception as e:
        print(f"Error fetching target product: {e}")
        return None, None

def find_product_by_sku(shop_url, access_token, sku):
    """หา product จาก SKU ของ variant ผ่าน GraphQL (REST ค้นด้วย SKU ไม่ได้) → (info, error)"""
    url = f"https://{_shop_domain(shop_url)}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": access_token, "Content-Type": "application/json"}
    gql = """
    query FindBySku($q: String!) {
      productVariants(first: 50, query: $q) {
        nodes { sku product { legacyResourceId title handle } }
      }
    }
    """
    sku = sku.strip()
    want = sku.lower()
    escaped = sku.replace("\\", "\\\\").replace('"', '\\"')
    searches = [f'sku:"{escaped}"']
    if not re.search(r"\s", sku):
        searches.append(f"sku:{escaped}*")  # เผื่อ SKU แยกตามไซส์ เช่น R123-8, R123-9

    for q in searches:
        try:
            res = requests.post(url, headers=headers, json={"query": gql, "variables": {"q": q}}, timeout=15)
        except Exception as e:
            return None, f"Connection Error: {str(e)}"
        if res.status_code != 200:
            return None, f"Shopify Error {res.status_code}"
        body = res.json()
        if body.get("errors"):
            return None, f"Shopify GraphQL: {body['errors'][0].get('message', body['errors'])}"
        nodes = ((body.get("data") or {}).get("productVariants") or {}).get("nodes") or []
        exact = [n for n in nodes if (n.get("sku") or "").strip().lower() == want]
        prefix = [n for n in nodes if (n.get("sku") or "").strip().lower().startswith(want)]

        products = {}
        for n in (exact or prefix):
            p = n.get("product") or {}
            if p.get("legacyResourceId"):
                products.setdefault(str(p["legacyResourceId"]), {**p, "sku": n.get("sku")})
        if products:
            first_id, p = next(iter(products.items()))
            note = f"⚠️ SKU นี้ตรงกับ {len(products)} สินค้า — ใช้ตัวแรก" if len(products) > 1 else None
            return {"id": first_id, "title": p.get("title", ""), "handle": p.get("handle", ""),
                    "sku": p.get("sku"), "via": "SKU", "note": note}, None
    return None, f"ไม่พบ SKU: {sku}"

def resolve_product(shop_url, access_token, text):
    """รับได้ทั้ง Product ID, ลิงก์หน้า admin ของสินค้า หรือ SKU → (info, error)"""
    q = str(text or "").strip()
    if not q:
        return None, "ใส่ Product ID หรือ SKU"
    m = re.search(r"(?:/products/|Product/)(\d+)", q)
    if m:
        q = m.group(1)
    looks_like_id = q.isdigit() and len(q) >= 10  # Product ID ของ Shopify ยาว 13 หลัก
    if looks_like_id:
        title, handle = get_target_product_details(shop_url, access_token, q)
        if title is not None:
            return {"id": q, "title": title, "handle": handle, "via": "ID", "note": None}, None
    info, err = find_product_by_sku(shop_url, access_token, q)
    if not info and looks_like_id and err and err.startswith("ไม่พบ"):
        err = f"ไม่พบ Product ID หรือ SKU: {q}"
    return info, err

def upload_image_to_shopify(shop_url, access_token, product_id, image_bytes, filename, alt_text):
    url = f"https://{_shop_domain(shop_url)}/admin/api/{SHOPIFY_API_VERSION}/products/{product_id}/images.json"
    headers = {"X-Shopify-Access-Token": access_token, "Content-Type": "application/json"}

    # Convert bytes to base64 string
    b64_string = base64.b64encode(image_bytes).decode('utf-8')

    payload = {
        "image": {
            "attachment": b64_string,
            "filename": filename,
            "alt": alt_text
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        if response.status_code in [200, 201]:
            return True, response.json()
        else:
            return False, f"Error {response.status_code}: {response.text}"
    except Exception as e:
        return False, str(e)

# --- LIBRARY FUNCTIONS (คงเดิม) ---
DEFAULT_PROMPTS = [
    {
        "id": "p1", "name": "Luxury Hand (Ring)", "category": "Ring",
        "template": "High-end jewelry photography, soft studio lighting, realistic skin texture, neutral background.",
        "variables": "",
        "sample_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c2/Ring_render.jpg/320px-Ring_render.jpg"
    }
]

def get_prompts():
    try:
        raw_key = st.secrets.get("JSONBIN_API_KEY", "")
        raw_bin = st.secrets.get("JSONBIN_BIN_ID", "")
        API_KEY = clean_key(raw_key)
        BIN_ID = clean_key(raw_bin)

        if not API_KEY or not BIN_ID: return DEFAULT_PROMPTS

        url = f"https://api.jsonbin.io/v3/b/{BIN_ID}/latest"
        headers = {"X-Master-Key": API_KEY}
        response = requests.get(url, headers=headers, timeout=5)

        if response.status_code == 200:
            return response.json().get("record", DEFAULT_PROMPTS)
        return DEFAULT_PROMPTS
    except: return DEFAULT_PROMPTS

def save_prompts(data):
    try:
        raw_key = st.secrets.get("JSONBIN_API_KEY", "")
        raw_bin = st.secrets.get("JSONBIN_BIN_ID", "")
        API_KEY = clean_key(raw_key)
        BIN_ID = clean_key(raw_bin)

        url = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
        headers = {"Content-Type": "application/json", "X-Master-Key": API_KEY}
        requests.put(url, json=data, headers=headers, timeout=10)
    except Exception as e: st.error(f"Save failed: {e}")

# --- AI: GEMINI CALL ---
def gemini_text_parts(data):
    """ดึงข้อความจาก candidate แรก (ข้าม thought parts)"""
    cands = data.get("candidates") or []
    if not cands: return ""
    parts = (cands[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))

def call_gemini_image(api_key, model, parts, aspect_ratio, image_size):
    """เรียก generateContent → (image_bytes, mime, error) · เลือกรูปสุดท้ายที่ไม่ใช่ thought (รูปร่างระหว่างคิด)"""
    gen_cfg = {
        "responseModalities": ["TEXT", "IMAGE"],
        "imageConfig": {"aspectRatio": aspect_ratio, "imageSize": image_size},
    }
    thinking_level = IMAGE_MODELS.get(model, {}).get("thinking_level")
    if thinking_level:
        gen_cfg["thinkingConfig"] = {"thinkingLevel": thinking_level}
    # ไม่ตั้ง temperature: Google แนะนำให้ Gemini 3 ทุกรุ่นใช้ค่า default 1.0
    # (ตั้งต่ำกว่า 1.0 เช่น 0.15 แบบเดิม ทำให้ผลเพี้ยน/วนลูปได้)
    payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": gen_cfg}
    url = f"{GEMINI_BASE_URL}/{model}:generateContent"
    # ส่ง key ทาง header ไม่ใส่ใน URL (error ของ requests จะพิมพ์ URL ออกมาบนจอ)
    headers = {"Content-Type": "application/json", "x-goog-api-key": clean_key(api_key)}

    res = None
    for attempt in range(3):
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=300)
        except requests.exceptions.Timeout:
            return None, None, "Timeout (5 นาที) — ลองลดจำนวนรูปอ้างอิง หรือใช้ 1K"
        except Exception as e:
            return None, None, f"Connection Error: {str(e)}"
        # 429 = โควตาต่อนาทีเต็ม, 5xx = โมเดลโหลดหนัก → รอแล้วลองใหม่ (request ที่ล้มไม่คิดเงิน)
        if res.status_code in (429, 500, 503, 504) and attempt < 2:
            time.sleep(8 * (attempt + 1))
            continue
        break

    if res.status_code != 200:
        return None, None, f"API Error {res.status_code}: {res.text[:800]}"

    data = res.json()
    cands = data.get("candidates") or []
    if not cands:
        block = (data.get("promptFeedback") or {}).get("blockReason")
        return None, None, f"ไม่มีผลลัพธ์ (blockReason={block})" if block else "ไม่มีผลลัพธ์จาก API"

    images = []
    for p in (cands[0].get("content") or {}).get("parts") or []:
        if p.get("thought"):
            continue
        blob = p.get("inlineData") or p.get("inline_data")
        if blob and blob.get("data"):
            images.append(blob)
    if images:
        blob = images[-1]
        img_bytes = base64.b64decode(blob["data"])
        mime = blob.get("mimeType") or blob.get("mime_type") or detect_mime(img_bytes)
        return img_bytes, mime, None

    reason = cands[0].get("finishReason")
    text = gemini_text_parts(data).strip()
    return None, None, f"โมเดลไม่ส่งรูปกลับ (finishReason={reason}) {text[:500]}"

# --- AI FUNCTION: SEO ---
def generate_seo_data(api_key, image_bytes, product_title, product_handle):
    """image_bytes ต้องเป็น JPEG (เรียก image_bytes_to_jpeg ก่อน)"""
    url = f"{GEMINI_BASE_URL}/{MODEL_SEO_GEN}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": clean_key(api_key)}
    fallback_name = f"{product_handle}-model.jpg" if product_handle else "ring-generated.jpg"
    fallback = {"filename": fallback_name, "alt_text": product_title or "Ring on hand"}

    prompt = f"""
    You are an SEO expert for a Jewelry E-commerce store.

    CONTEXT:
    This image is being uploaded to a product page.
    Target Product Name: "{product_title}"
    Target URL Slug (Handle): "{product_handle}"

    TASK:
    Create an SEO-friendly image filename and an Alt Text attribute specifically for this product.

    REQUIREMENTS:
    1. filename: MUST contain the product name or handle. Use lowercase, hyphens (-) as separators. End with .jpg.
       Example: if product is "Gold Ring", filename -> "gold-ring-model-hand.jpg"
    2. alt_text: Describe the image naturally but MUST include the product name "{product_title}". Max 125 characters.

    OUTPUT FORMAT (JSON ONLY):
    {{
        "filename": "...",
        "alt_text": "..."
    }}
    """

    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                image_part(image_bytes, "image/jpeg")
            ]
        }],
        "generationConfig": {"responseMimeType": "application/json"}
    }

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=60)
        if res.status_code != 200:
            print(f"SEO API Error {res.status_code}: {res.text[:300]}")
            return fallback
        data = json.loads(gemini_text_parts(res.json()) or "{}")
        filename = re.sub(r"[^a-z0-9-]+", "-", str(data.get("filename", "")).lower().removesuffix(".jpg")).strip("-")
        alt_text = str(data.get("alt_text", "")).strip()[:125]
        return {"filename": f"{filename}.jpg" if filename else fallback_name,
                "alt_text": alt_text or fallback["alt_text"]}
    except Exception as e:
        print(f"SEO Error: {e}")
        return fallback

# --- AI FUNCTION: GENERATE FROM SCRATCH ---
JEWELRY_LOCATIONS = {
    "index": "INDEX finger (the finger next to the thumb)",
    "middle": "MIDDLE finger (the longest, centre finger)",
    "ring": "RING finger (between the middle finger and the little finger)",
    "little": "LITTLE finger (the pinky, smallest finger)",
    "bracelet": "WRIST (bracelet)",
    "necklace": "NECK (necklace / pendant)",
}
ORDERED_KEYS = ["index", "middle", "ring", "little", "bracelet", "necklace"]
FINGER_KEYS = ["index", "middle", "ring", "little"]

def build_generation_parts(all_images_dict, base_prompt, hand_model):
    """ประกอบ prompt แบบวางป้ายข้อความคั่นหน้ารูปของแต่ละชิ้น (interleave)
    — แม่นกว่าการแปะรูปทั้งหมดไว้ท้าย prompt แล้วอ้าง 'reference image #5'"""
    used = [k for k in ORDERED_KEYS if all_images_dict.get(k)]
    letters = "ABCDEF"
    has_necklace = bool(all_images_dict.get("necklace"))
    framing = ("Portrait / bust shot that shows the hand and the neck"
               if has_necklace else "Close-up shot of one hand and the wrist")
    bare = [JEWELRY_LOCATIONS[k].split(" (")[0] for k in FINGER_KEYS if not all_images_dict.get(k)]
    assignments = "\n".join(f"- PRODUCT {letters[i]} → {JEWELRY_LOCATIONS[k]}" for i, k in enumerate(used))

    intro = f"""Create one photorealistic professional jewelry photo of a {hand_model} hand model wearing the exact products shown in the reference photos below.

STYLE / SCENE:
{base_prompt.strip()}

FRAMING: {framing}. Unless the style above says otherwise, show the back of one hand toward the camera, fingers relaxed and slightly apart, so every piece is fully visible and in sharp focus.

PLACEMENT (follow exactly):
{assignments}
"""
    parts = [{"text": intro}]
    for i, k in enumerate(used):
        n = len(all_images_dict[k])
        parts.append({"text": f"PRODUCT {letters[i]} — worn on the {JEWELRY_LOCATIONS[k]}. "
                              f"{n} reference photo(s) of this single product:"})
        for img in all_images_dict[k]:
            parts.append(image_part(pil_to_jpeg_bytes(img)))

    rules = [
        "Each product appears exactly once, only in its assigned position. Do not swap, mirror or duplicate products.",
        f"These fingers stay bare (no ring): {', '.join(bare)}. No ring on the thumb." if bare else "No ring on the thumb.",
        "No extra jewelry beyond the listed products (no additional rings, bracelets or watches).",
        "Reproduce every product faithfully: same silhouette, proportions, band width, engraved or embossed lettering, "
        "gemstone count and colour, and metal tones (keep silver areas silver and gold-tone accents gold-tone).",
        "Never invent, translate or rewrite engraved text. If lettering is too small to render legibly, keep the same "
        "style of engraved texture instead of writing new words.",
        "Realistic scale: rings sit at the base of the finger and fit the finger naturally, keeping each product's "
        "proportions from its photos.",
        "The reference photos may contain other hands, tattoos, backgrounds or props. Use them only to learn the jewelry "
        "design; do not copy hands, skin, tattoos or scenery from them.",
        "Anatomically correct hand: five fingers, natural knuckles and nails, realistic skin texture.",
    ]
    parts.append({"text": "RULES:\n" + "\n".join(f"{i + 1}. {r}" for i, r in enumerate(rules))})
    return parts

def generate_image_multi_finger(api_key, model, all_images_dict, base_prompt, hand_model, aspect_ratio, image_size):
    parts = build_generation_parts(all_images_dict, base_prompt, hand_model)
    return call_gemini_image(api_key, model, parts, aspect_ratio, image_size)

# --- AI FUNCTION: EDIT EXISTING IMAGE ---
def edit_generated_image(api_key, model, current_image_bytes, current_mime, edit_instructions,
                         ref_images_dict, aspect_ratio, image_size):
    """แก้ไขภาพเดิมตามคำสั่งใหม่ · แนบรูปสินค้าจริงไปด้วย กันลายแหวนเพี้ยนสะสมทุกรอบที่แก้"""
    parts = [
        {"text": f"""Edit the image below. Change ONLY this:
{edit_instructions}

Keep everything else exactly the same: the hand, pose, skin, lighting, background, camera angle, and every piece of jewelry the instruction does not mention. Keep the professional jewelry photography style and realism. If moving a ring, keep the hand anatomically correct."""},
        image_part(current_image_bytes, current_mime or detect_mime(current_image_bytes)),
    ]
    used = [k for k in ORDERED_KEYS if ref_images_dict and ref_images_dict.get(k)]
    if used:
        parts.append({"text": "Reference photos of the real products, for detail accuracy only. Every piece of jewelry in "
                              "the edited image must keep matching these designs exactly. Do not copy hands or backgrounds "
                              "from them. If the instruction moves a product, follow the instruction."})
        budget = MAX_REFS_TOTAL - 1  # 1 รูปคือภาพที่กำลังแก้
        for k in used:
            imgs = ref_images_dict[k][:budget]
            if not imgs:
                break
            parts.append({"text": f"Product currently on the {JEWELRY_LOCATIONS[k]}:"})
            for img in imgs:
                parts.append(image_part(pil_to_jpeg_bytes(img)))
            budget -= len(imgs)
    return call_gemini_image(api_key, model, parts, aspect_ratio, image_size)


# --- SESSION STATE INIT ---
if "library" not in st.session_state: st.session_state.library = get_prompts()
if "generated_result" not in st.session_state: st.session_state.generated_result = None
if "generated_mime" not in st.session_state: st.session_state.generated_mime = None
if "edit_target" not in st.session_state: st.session_state.edit_target = None

# --- SIDEBAR CONFIG ---
with st.sidebar:
    st.title("⚙️ Configuration")

    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        st.success("✅ Gemini Key Loaded")
    elif "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
        st.success("✅ Google Key Loaded")
    else:
        api_key = st.text_input("Gemini API Key", type="password")
    api_key = clean_key(api_key)

    # Check Shopify Secrets
    sh_shop = st.secrets.get("SHOPIFY_SHOP_URL", "")
    sh_token = st.secrets.get("SHOPIFY_ACCESS_TOKEN", "")
    if sh_shop and sh_token:
        st.success("✅ Shopify Connected")
    else:
        st.warning("⚠️ Shopify Secrets Missing")

    if "JSONBIN_API_KEY" in st.secrets: st.caption("✅ Database Connected")
    else: st.warning("⚠️ Local Mode")

    st.divider()
    st.subheader("🎨 Image Settings")
    image_model = st.selectbox(
        "Model", list(IMAGE_MODELS), index=list(IMAGE_MODELS).index(DEFAULT_IMAGE_MODEL),
        format_func=lambda m: IMAGE_MODELS[m]["label"], key="image_model"
    )
    st.caption(f"`{image_model}`")
    image_size = st.selectbox("Resolution", ["1K", "2K", "4K"], index=1, key="image_size",
                              help="Nano Banana Pro ราคา 1K = 2K เท่ากัน · 4K แพงขึ้นและช้ากว่า")
    aspect_ratio = st.selectbox("Aspect Ratio", ["1:1", "4:5", "3:4", "4:3", "3:2", "16:9", "9:16"], index=0,
                                key="aspect_ratio", help="1:1 เข้ากับแกลเลอรีรูปสินค้า Shopify")
    hand_model = st.radio("Hand Model", ["male", "female"], horizontal=True, key="hand_model")

# --- MAIN UI ---
st.title("💍 Ring & Jewelry AI Generator")
st.caption("Generate full jewelry set photos: Rings, Bracelets, and Necklaces.")

# --- TABS ---
tab1, tab2 = st.tabs(["✨ Generate Image", "📚 Library Manager"])

# ============= TAB 1: GENERATE IMAGE =============
with tab1:
    # --- STEP 1: SELECT STYLE ---
    st.subheader("1️⃣ Select Style Template")

    lib = st.session_state.library
    ring_prompts = [p for p in lib if p.get('category') == 'Ring']

    if not ring_prompts:
        st.error("❌ No Ring templates found.")
        st.stop()

    col_style1, col_style2 = st.columns([2, 1])

    with col_style1:
        selected_style = st.selectbox("Choose Style", ring_prompts, format_func=lambda x: x.get('name', 'Unknown'), key="style_select")

        template_text = selected_style.get('template', '')
        vars_list = [v.strip() for v in selected_style.get('variables', '').split(",") if v.strip()]
        user_vals = {}

        if vars_list:
            st.write("**Customize Parameters:**")
            cols = st.columns(len(vars_list))
            for i, v in enumerate(vars_list):
                user_vals[v] = cols[i].text_input(v, key=f"var_{selected_style['id']}_{v}")

        final_base_prompt = template_text
        for k, v in user_vals.items():
            final_base_prompt = final_base_prompt.replace(f"{{{k}}}", v)

        st.write("**Preview & Edit Prompt:**")
        prompt_key = f"edit_prompt_area_{selected_style['id']}"
        user_edited_prompt = st.text_area("Base Instruction", value=final_base_prompt, height=100, key=prompt_key)

    with col_style2:
        if selected_style.get("sample_url"):
            st.write("**Sample:**")
            safe_st_image(selected_style["sample_url"], width=200)

    st.divider()

    # --- HELPER UI FOR IMAGE INPUT ---
    def render_input_block(item_key, item_name, item_emoji, container):
        """Helper to render input block for any item (finger or accessory) → คืนเฉพาะรูปที่ติ๊กเลือก"""
        with container:
            with st.container(border=True):
                st.markdown(f"### {item_emoji} {item_name}")

                # Fetch Keys
                fetch_key = f"fetch_shop_{item_key}"
                meta_key = f"fetch_meta_{item_key}"
                auto_key = f"fetch_auto_{item_key}"
                nonce_key = f"fetch_nonce_{item_key}"
                if fetch_key not in st.session_state:
                    st.session_state[fetch_key] = []
                if nonce_key not in st.session_state:
                    st.session_state[nonce_key] = 0

                # Shopify Input (Product ID หรือ SKU)
                if sh_shop and sh_token:
                    c_id, c_btn = st.columns([2, 1])
                    prod_query = c_id.text_input("Product ID / SKU", placeholder="Product ID หรือ SKU", key=f"inp_{item_key}", label_visibility="collapsed")

                    if c_btn.button("Fetch", key=f"btn_{item_key}"):
                        if not prod_query.strip():
                            st.warning("ใส่ Product ID หรือ SKU")
                        else:
                            with st.spinner("กำลังดึงรูปจาก Shopify..."):
                                info, err = resolve_product(sh_shop, sh_token, prod_query)
                                imgs = None
                                if info:
                                    imgs, err = get_shopify_product_images(sh_shop, sh_token, info["id"])
                            if imgs:
                                st.session_state[fetch_key] = imgs
                                st.session_state[meta_key] = info
                                st.session_state[auto_key] = default_pick(imgs)
                                st.session_state[nonce_key] += 1  # checkbox ชุดใหม่ ใช้ค่า auto-pick
                            else:
                                st.error(f"❌ {err}")

                # Manual Upload
                uploaded_files = st.file_uploader(
                    "Or Upload", accept_multiple_files=True, type=["jpg", "jpeg", "png", "webp"],
                    key=f"upload_{item_key}", label_visibility="collapsed"
                )

                fetched = st.session_state[fetch_key]
                if fetched:
                    meta = st.session_state.get(meta_key) or {}
                    label = meta.get("title") or "Shopify"
                    if meta.get("via") == "SKU":
                        label += f" · SKU {meta.get('sku')}"
                    st.info(f"{label} ({len(fetched)} รูป)")
                    if meta.get("note"):
                        st.caption(meta["note"])
                    if st.button("Clear Fetch", key=f"clr_{item_key}"):
                        st.session_state[fetch_key] = []
                        st.session_state.pop(meta_key, None)
                        st.rerun()

                # รูปทั้งหมด + checkbox (รูปนายแบบใส่แหวนทำให้โมเดลสับสน → ติ๊กให้เฉพาะรูปสินค้าเดี่ยว)
                nonce = st.session_state[nonce_key]
                auto = set(st.session_state.get(auto_key, []))
                candidates = [(img, i in auto, f"sel_{item_key}_s{nonce}_{i}") for i, img in enumerate(fetched)]
                for f in uploaded_files or []:
                    fid = getattr(f, "file_id", None) or f"{f.name}_{f.size}"
                    candidates.append((normalize_image(Image.open(f)), True, f"sel_{item_key}_u_{fid}"))

                if not candidates:
                    st.caption("⚪ Empty")
                    return []

                selected = []
                thumb_cols = st.columns(3)
                for n, (img, default_on, sel_key) in enumerate(candidates):
                    with thumb_cols[n % 3]:
                        st.image(img, width="stretch")
                        if st.checkbox("ใช้รูปนี้", value=default_on, key=sel_key):
                            selected.append(img)
                st.caption(f"✅ ใช้ {len(selected)}/{len(candidates)} รูป · แนะนำ 1–2 รูปสินค้าเดี่ยวต่อชิ้น")
                return selected

    # --- STEP 2: RINGS INPUT ---
    st.subheader("2️⃣ Fingers (Rings)")

    fingers = [
        {"key": "index", "name": "Index Finger", "emoji": "☝️"},
        {"key": "middle", "name": "Middle Finger", "emoji": "🖕"},
        {"key": "ring", "name": "Ring Finger", "emoji": "💍"},
        {"key": "little", "name": "Little Finger", "emoji": "🤙"}
    ]

    row1_col1, row1_col2 = st.columns(2)
    row2_col1, row2_col2 = st.columns(2)
    finger_cols = [row1_col1, row1_col2, row2_col1, row2_col2]

    all_jewelry_images = {}

    for idx, f in enumerate(fingers):
        imgs = render_input_block(f["key"], f["name"], f["emoji"], finger_cols[idx])
        if imgs: all_jewelry_images[f["key"]] = imgs

    st.divider()

    # --- STEP 3: ACCESSORIES INPUT ---
    st.subheader("3️⃣ Accessories (Bracelet & Necklace)")

    accessories = [
        {"key": "bracelet", "name": "Bracelet", "emoji": "📿"},
        {"key": "necklace", "name": "Necklace / Pendant", "emoji": "⛓️"}
    ]

    acc_c1, acc_c2 = st.columns(2)
    acc_cols = [acc_c1, acc_c2]

    for idx, acc in enumerate(accessories):
        imgs = render_input_block(acc["key"], acc["name"], acc["emoji"], acc_cols[idx])
        if imgs: all_jewelry_images[acc["key"]] = imgs

    st.divider()

    # --- STEP 4: GENERATE & RESET ---
    st.subheader("4️⃣ Generate Photo")

    total_items = len(all_jewelry_images)
    total_refs = sum(len(v) for v in all_jewelry_images.values())
    fidelity_limit = IMAGE_MODELS[image_model]["max_fidelity_refs"]

    col_info, col_btn = st.columns([2, 1])

    with col_info:
        if total_items > 0:
            st.success(f"✅ Ready: {total_items} jewelry items · {total_refs} reference images")
            item_list = ", ".join([k.capitalize() for k in all_jewelry_images.keys()])
            st.caption(f"📍 Items: {item_list} · Model: `{image_model}` · {image_size} · {aspect_ratio}")
            if total_refs > MAX_REFS_TOTAL:
                st.error(f"❌ รูปอ้างอิงรวม {total_refs} รูป เกินลิมิต {MAX_REFS_TOTAL} รูปของ API — เอาติ๊กออกบ้าง")
            elif total_refs > fidelity_limit:
                st.warning(f"⚠️ โมเดลนี้รักษารายละเอียดได้แม่นราว {fidelity_limit} รูป — ตอนนี้ {total_refs} รูป ยิ่งเยอะยิ่งเพี้ยน")
        else:
            st.warning("⚠️ Assign at least one item (ID / SKU or Upload)")

    with col_btn:
        can_generate = bool(all_jewelry_images) and bool(api_key) and total_refs <= MAX_REFS_TOTAL

        if st.button("🚀 GENERATE PHOTO", type="primary", width="stretch", disabled=not can_generate):
            with st.spinner("🎨 Generating jewelry photo... (ประมาณ 30–120 วินาที)"):
                img_bytes, img_mime, error = generate_image_multi_finger(
                    api_key, image_model, all_jewelry_images, user_edited_prompt,
                    hand_model, aspect_ratio, image_size
                )

                if img_bytes:
                    st.session_state.generated_result = img_bytes
                    st.session_state.generated_mime = img_mime
                    st.success("✅ Done!")
                    st.rerun()
                else:
                    st.error(f"❌ Failed: {error}")

        if st.button("🔄 Reset / Clear All", width="stretch", on_click=reset_app_state):
            pass

    # --- DISPLAY RESULT & EDIT SECTION ---
    if st.session_state.generated_result:
        st.divider()
        st.subheader("✨ Generated Result")

        # แสดงรูปภาพผลลัพธ์
        st.image(st.session_state.generated_result, width="stretch", caption="Current Generated Image")

        # --- ส่วนแก้ไขรูปภาพ ---
        st.markdown("### 🎨 Edit This Image")
        edit_col1, edit_col2 = st.columns([3, 1])

        with edit_col1:
            edit_instructions = st.text_area(
                "Edit Instructions",
                placeholder="Ex: Move the ring to the ring finger, make the hand whiter, make the ring smaller...",
                height=100,
                key="result_edit_prompt"
            )
            send_refs = st.checkbox("แนบรูปสินค้าที่เลือกไว้ไปด้วย (กันลายแหวนเพี้ยนตอนแก้)", value=True, key="edit_send_refs")

        with edit_col2:
            st.write("") # Spacer
            st.write("") # Spacer
            if st.button("🔄 Apply Edits", type="primary", width="stretch", disabled=not edit_instructions):
                with st.spinner("🎨 Applying edits to image..."):
                    # ส่งรูปล่าสุด + คำสั่งแก้ไข (+ รูปสินค้าจริง)
                    new_img_bytes, new_mime, edit_error = edit_generated_image(
                        api_key, image_model,
                        st.session_state.generated_result,
                        st.session_state.generated_mime,
                        edit_instructions,
                        all_jewelry_images if send_refs else None,
                        aspect_ratio, image_size
                    )

                    if new_img_bytes:
                        # อัปเดตผลลัพธ์ด้วยรูปใหม่
                        st.session_state.generated_result = new_img_bytes
                        st.session_state.generated_mime = new_mime
                        st.success("✅ Edits Applied!")
                        st.rerun() # รีเฟรชหน้าจอเพื่อแสดงรูปใหม่
                    else:
                        st.error(f"❌ Edit Failed: {edit_error}")

        st.divider()

        # --- DOWNLOAD & UPLOAD SECTION ---
        col_dl, col_up = st.columns([1, 2])

        with col_dl:
            st.markdown("### 💾 Download")
            out_mime = st.session_state.generated_mime or "image/png"
            out_ext = {"image/jpeg": "jpg", "image/webp": "webp"}.get(out_mime, "png")
            st.download_button(
                "📥 Download Image",
                st.session_state.generated_result,
                f"jewelry_gen.{out_ext}",
                out_mime,
                width="stretch",
                type="secondary"
            )

        with col_up:
            st.markdown("### ☁️ Upload to Shopify")
            target_upload_query = st.text_input("Target Product ID / SKU", key="target_upload_id", placeholder="Ex: 8234... หรือ SKU", help="ID หรือ SKU ของสินค้าปลายทางที่จะเอารูปนี้ไปใส่")

            if st.button("⬆️ Generate SEO & Upload", type="primary", width="stretch", disabled=not (target_upload_query and sh_shop and sh_token)):

                with st.spinner(f"🔍 Fetching details for: {target_upload_query}..."):
                    target_info, target_err = resolve_product(sh_shop, sh_token, target_upload_query)

                if not target_info:
                    st.error(f"❌ Product Not Found in Shopify: {target_err}")
                else:
                    t_id, t_title, t_handle = target_info["id"], target_info["title"], target_info["handle"]
                    upload_bytes = image_bytes_to_jpeg(st.session_state.generated_result)
                    with st.spinner(f"🧠 Generating SEO for '{t_title}'..."):
                        seo_data = generate_seo_data(api_key, upload_bytes, t_title, t_handle)
                        final_filename = seo_data.get("filename", f"{t_handle}.jpg")
                        final_alt = seo_data.get("alt_text", t_title)

                        st.info(f"📄 File: `{final_filename}`\n🏷️ Alt: `{final_alt}`")

                    with st.spinner("☁️ Uploading..."):
                        success, resp = upload_image_to_shopify(
                            sh_shop, sh_token,
                            t_id,
                            upload_bytes,
                            final_filename,
                            final_alt
                        )

                        if success:
                            st.success(f"✅ Uploaded Successfully to '{t_title}' (ID {t_id})!")
                            time.sleep(1)
                        else:
                            st.error(f"❌ Upload Failed: {resp}")


# ============= TAB 2: LIBRARY MANAGER =============
with tab2:
    st.subheader("📚 Prompt Library Manager")
    target = st.session_state.edit_target
    title = f"✏️ Edit: {target['name']}" if target else "➕ Add New Template"

    with st.form("lib_form", border=True):
        st.write(f"**{title}**")
        c1, c2 = st.columns(2)
        n = c1.text_input("Name", value=target['name'] if target else "")
        c = c2.text_input("Category", value=target['category'] if target else "Ring")
        t = st.text_area("Template", value=target['template'] if target else "", height=120)
        c3, c4 = st.columns(2)
        v = c3.text_input("Vars", value=target['variables'] if target else "")
        u = c4.text_input("Sample URL", value=target['sample_url'] if target else "")

        cols = st.columns([1, 1, 3])
        if cols[0].form_submit_button("💾 Save", type="primary"):
            new = {"id": target['id'] if target else str(len(st.session_state.library)+1000), "name": n, "category": c, "template": t, "variables": v, "sample_url": u}
            if target:
                for idx, item in enumerate(st.session_state.library):
                    if item['id'] == target['id']: st.session_state.library[idx] = new; break
            else: st.session_state.library.append(new)
            save_prompts(st.session_state.library)
            st.session_state.edit_target = None; st.rerun()

        if target and cols[1].form_submit_button("❌ Cancel"):
            st.session_state.edit_target = None; st.rerun()

    st.divider()
    for i, p in enumerate([x for x in st.session_state.library if x.get('category') == 'Ring']):
        c1, c2, c3, c4 = st.columns([1, 4, 1, 1])
        if p.get("sample_url"):
            with c1: safe_st_image(p["sample_url"], width=60)
        c2.write(f"**{p.get('name')}**"); c2.caption(f"Vars: {p.get('variables')}")
        if c3.button("✏️", key=f"e{i}"): st.session_state.edit_target = p; st.rerun()
        if c4.button("🗑️", key=f"d{i}"): st.session_state.library.remove(p); save_prompts(st.session_state.library); st.rerun()
        st.divider()

st.markdown("---")
st.caption("💎 Powered by Gemini AI")
