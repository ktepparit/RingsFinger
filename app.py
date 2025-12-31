import streamlit as st
import json
import requests
import base64
from io import BytesIO
from PIL import Image
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

# Model ID
MODEL_IMAGE_GEN = "models/gemini-3-pro-image-preview" # For generating images
MODEL_SEO_GEN = "models/gemini-1.5-flash" # For generating SEO text (Fast & Cheap)

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
    # ล้างช่อง edit prompt ด้วย
    if "result_edit_prompt" in st.session_state:
         del st.session_state["result_edit_prompt"]

    keys_to_clear = []
    for key in st.session_state.keys():
        if (key.startswith("upload_") or 
            key.startswith("var_") or 
            key.startswith("edit_prompt_area_") or # แก้ให้ตรงกับ key ที่ใช้จริง
            key.startswith("fetch_shop_") or
            key.startswith("inp_") or 
            key == "prev_style_id"):
            keys_to_clear.append(key)
            
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]

# --- SHOPIFY HELPERS (คงเดิม) ---
def get_shopify_product_images(shop_url, access_token, product_id):
    # ... (code เดิม) ...
    shop_url = shop_url.replace("https://", "").replace("http://", "").strip()
    if not shop_url.endswith(".myshopify.com"):
        shop_url += ".myshopify.com"
        
    url = f"https://{shop_url}/admin/api/2024-01/products/{product_id}/images.json"
    
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            images_data = data.get("images", [])
            
            pil_images = []
            for img_info in images_data:
                src = img_info.get("src")
                if src:
                    img_resp = requests.get(src, stream=True)
                    if img_resp.status_code == 200:
                        img_pil = Image.open(BytesIO(img_resp.content))
                        if img_pil.mode in ('RGBA', 'P'):
                            img_pil = img_pil.convert('RGB')
                        pil_images.append(img_pil)
            return pil_images, None
        else:
            return None, f"Shopify Error {response.status_code}"
    except Exception as e:
        return None, f"Connection Error: {str(e)}"

def get_target_product_details(shop_url, access_token, product_id):
    # ... (code เดิม) ...
    shop_url = shop_url.replace("https://", "").replace("http://", "").strip()
    if not shop_url.endswith(".myshopify.com"): shop_url += ".myshopify.com"
    
    url = f"https://{shop_url}/admin/api/2024-01/products/{product_id}.json?fields=title,handle"
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

def upload_image_to_shopify(shop_url, access_token, product_id, image_bytes, filename, alt_text):
    # ... (code เดิม) ...
    shop_url = shop_url.replace("https://", "").replace("http://", "").strip()
    if not shop_url.endswith(".myshopify.com"): shop_url += ".myshopify.com"
    
    url = f"https://{shop_url}/admin/api/2024-01/products/{product_id}/images.json"
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
        response = requests.post(url, headers=headers, json=payload, timeout=20)
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
    # ... (code เดิม) ...
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
    # ... (code เดิม) ...
    try:
        raw_key = st.secrets.get("JSONBIN_API_KEY", "")
        raw_bin = st.secrets.get("JSONBIN_BIN_ID", "")
        API_KEY = clean_key(raw_key)
        BIN_ID = clean_key(raw_bin)
        
        url = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
        headers = {"Content-Type": "application/json", "X-Master-Key": API_KEY}
        requests.put(url, json=data, headers=headers, timeout=10)
    except Exception as e: st.error(f"Save failed: {e}")

# --- IMAGE HELPER (PIL to Base64) ---
def img_to_base64(img):
    buf = BytesIO()
    if img.mode == 'RGBA': img = img.convert('RGB')
    img.thumbnail((1024, 1024)) 
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()

# --- NEW HELPER: Bytes to Base64 String ---
def bytes_to_base64_str(image_bytes):
    """Helper to convert raw bytes directly to base64 string"""
    return base64.b64encode(image_bytes).decode('utf-8')

# --- AI FUNCTION: SEO (คงเดิม) ---
def generate_seo_data(api_key, image_bytes, product_title, product_handle):
    # ... (code เดิม) ...
    key = clean_key(api_key)
    url = f"https://generativelanguage.googleapis.com/v1beta/{MODEL_SEO_GEN}:generateContent?key={key}"
    
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
    
    b64_img = base64.b64encode(image_bytes).decode('utf-8')
    
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": b64_img}}
            ]
        }],
        "generationConfig": {"response_mime_type": "application/json"}
    }
    
    try:
        res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
        if res.status_code == 200:
            result = res.json().get("candidates", [])[0].get("content", {}).get("parts", [])[0].get("text", "{}")
            return json.loads(result)
        else:
            fallback_name = f"{product_handle}-model.jpg" if product_handle else "ring-generated.jpg"
            return {"filename": fallback_name, "alt_text": product_title or "Ring on hand"}
    except Exception as e:
        return {"filename": "ring-generated.jpg", "alt_text": "Ring on hand"}

# --- AI FUNCTION: GENERATE FROM SCRATCH (คงเดิมจาก Logiv V2) ---
def generate_image_multi_finger(api_key, all_images_dict, base_prompt):
    # ... (code เดิมที่อัปเดต logic แล้ว) ...
    key = clean_key(api_key)
    url = f"https://generativelanguage.googleapis.com/v1beta/{MODEL_IMAGE_GEN}:generateContent?key={key}"
    
    jewelry_locations = {
        "index": "Index Finger (finger next to thumb)",
        "middle": "Middle Finger (longest center finger)", 
        "ring": "Ring Finger (finger between middle and little)",
        "little": "Little Finger (pinky, smallest finger)",
        "bracelet": "Wrist",
        "necklace": "Neck"
    }
    
    empty_fingers = []
    finger_keys = ["index", "middle", "ring", "little"]
    for f_key in finger_keys:
        if f_key not in all_images_dict or not all_images_dict[f_key]:
            empty_fingers.append(jewelry_locations[f_key])
            
    ordered_keys = ["index", "middle", "ring", "little", "bracelet", "necklace"]
    parts = [] 
    
    has_necklace = "necklace" in all_images_dict and all_images_dict["necklace"]
    framing = "Portrait/Bust shot showing Hand and Neck" if has_necklace else "Close-up Macro shot of Hand and Wrist only"
    
    prompt_intro = f"""
    {base_prompt}
    
    IMAGE SETTING:
    - TYPE: Professional Jewelry Photography
    - FRAMING: {framing}
    - SUBJECT: A single female model.
    """
    
    positive_instructions = []
    image_global_index = 1
    
    for item_key in ordered_keys:
        if item_key in all_images_dict and all_images_dict[item_key]:
            imgs = all_images_dict[item_key]
            count = len(imgs)
            loc_name = jewelry_locations[item_key]
            
            if count == 1:
                ref_text = f"reference image #{image_global_index}"
                image_global_index += 1
            else:
                ref_text = f"reference images #{image_global_index} to #{image_global_index + count - 1}"
                image_global_index += count
            
            instruction = f"   * {loc_name.upper()}: WEARING the jewelry design shown in {ref_text}."
            positive_instructions.append(instruction)
            
            for img in imgs:
                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": img_to_base64(img)}})

    negative_instructions = []
    if empty_fingers:
        empty_list_str = ", ".join(empty_fingers)
        negative_instructions.append(f"   * The following fingers MUST BE BARE (No Rings): {empty_list_str}.")
    
    negative_instructions.append("   * Do NOT put rings on the Thumb.")
    negative_instructions.append("   * Do NOT duplicate items.")
    
    full_prompt_text = f"""
    {prompt_intro}

    --- MANDATORY PLACEMENT INSTRUCTIONS ---
    Please strictly follow these assignments. Do not shift jewelry to other positions.

    ACTIVE ZONES (WEAR JEWELRY HERE):
    {chr(10).join(positive_instructions)}

    EMPTY ZONES (NO JEWELRY HERE):
    {chr(10).join(negative_instructions)}

    --- QUALITY GUIDELINES ---
    1. Realistic skin texture and lighting.
    2. Jewelry details (gemstones, metal) must match references exactly.
    3. Anatomically correct hand pose.
    """

    parts.insert(0, {"text": full_prompt_text})
    
    try:
        res = requests.post(
            url, 
            json={
                "contents": [{"parts": parts}], 
                "generationConfig": {"temperature": 0.15} 
            }, 
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        
        if res.status_code != 200: return None, f"API Error {res.status_code}: {res.text}"
            
        content = res.json().get("candidates", [])[0].get("content", {}).get("parts", [])[0]
        
        if "inline_data" in content: return base64.b64decode(content["inline_data"]["data"]), None
        if "inlineData" in content: return base64.b64decode(content["inlineData"]["data"]), None
        if "text" in content: return None, f"Model returned text: {content['text']}"
            
        return None, "Unknown format"
    except Exception as e: return None, str(e)

# --- NEW AI FUNCTION: EDIT EXISTING IMAGE ---
def edit_generated_image(api_key, current_image_bytes, edit_instructions):
    """ฟังก์ชันสำหรับแก้ไขภาพเดิมตามคำสั่งใหม่"""
    key = clean_key(api_key)
    url = f"https://generativelanguage.googleapis.com/v1beta/{MODEL_IMAGE_GEN}:generateContent?key={key}"
    
    # แปลง bytes ภาพปัจจุบันเป็น base64 string
    base64_img = bytes_to_base64_str(current_image_bytes)

    # สร้าง Prompt สำหรับการแก้ไข
    edit_prompt = f"""
    Based on the provided image, perform the following modification:
    {edit_instructions}

    IMPORTANT:
    - Maintain professional jewelry photography style, lighting, and high realism as seen in the original image.
    - Keep all other elements of the original image intact unless specified otherwise by the instructions.
    - Ensure anatomically correct hand structure if moving rings.
    """

    # สร้าง Payload (รูปเดิม + คำสั่งแก้ไข)
    parts = [
        {"text": edit_prompt},
        {"inline_data": {"mime_type": "image/jpeg", "data": base64_img}}
    ]
    
    try:
        # ใช้ temperature ต่ำๆ เพื่อให้คงสภาพเดิมไว้ให้มากที่สุด
        res = requests.post(
            url, 
            json={
                "contents": [{"parts": parts}], 
                "generationConfig": {"temperature": 0.1} 
            }, 
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        
        if res.status_code != 200: return None, f"API Error {res.status_code}: {res.text}"
            
        content = res.json().get("candidates", [])[0].get("content", {}).get("parts", [])[0]
        
        if "inline_data" in content: return base64.b64decode(content["inline_data"]["data"]), None
        if "inlineData" in content: return base64.b64decode(content["inlineData"]["data"]), None
        if "text" in content: return None, f"Model returned text: {content['text']}"
            
        return None, "Unknown format"
    except Exception as e: return None, str(e)


# --- SESSION STATE INIT ---
if "library" not in st.session_state: st.session_state.library = get_prompts()
if "generated_result" not in st.session_state: st.session_state.generated_result = None
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
        """Helper to render input block for any item (finger or accessory)"""
        with container:
            with st.container(border=True):
                st.markdown(f"### {item_emoji} {item_name}")
                
                # Fetch Key
                fetch_key = f"fetch_shop_{item_key}"
                if fetch_key not in st.session_state:
                    st.session_state[fetch_key] = []
                
                # Shopify Input
                if sh_shop and sh_token:
                    c_id, c_btn = st.columns([2, 1])
                    prod_id = c_id.text_input("Shopify ID", placeholder="ID", key=f"inp_{item_key}", label_visibility="collapsed")
                    
                    if c_btn.button("Fetch", key=f"btn_{item_key}"):
                        if not prod_id:
                            st.warning("Enter ID")
                        else:
                            with st.spinner(".."):
                                imgs, err = get_shopify_product_images(sh_shop, sh_token, prod_id)
                                if imgs:
                                    st.session_state[fetch_key] = imgs
                                    st.success("✅")
                                else:
                                    st.error("❌")
                
                # Manual Upload
                uploaded_files = st.file_uploader(
                    "Or Upload", accept_multiple_files=True, type=["jpg", "png"],
                    key=f"upload_{item_key}", label_visibility="collapsed"
                )
                
                # Combine & Display
                current_images = []
                if st.session_state[fetch_key]:
                    current_images.extend(st.session_state[fetch_key])
                    st.info(f"Shopify: {len(st.session_state[fetch_key])}")
                    if st.button("Clear Fetch", key=f"clr_{item_key}"):
                        st.session_state[fetch_key] = []
                        st.rerun()
                
                if uploaded_files:
                    current_images.extend([Image.open(f) for f in uploaded_files])
                
                # Return images for main dict
                if current_images:
                    st.caption(f"✅ {len(current_images)} images")
                    thumb_cols = st.columns(min(3, len(current_images)))
                    for i, img in enumerate(current_images):
                        thumb_cols[i % 3].image(img, use_column_width=True)
                    return current_images
                else:
                    st.caption("⚪ Empty")
                    return []

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
    
    col_info, col_btn = st.columns([2, 1])
    
    with col_info:
        if total_items > 0:
            st.success(f"✅ Ready: {total_items} jewelry items assigned.")
            item_list = ", ".join([k.capitalize() for k in all_jewelry_images.keys()])
            st.caption(f"📍 Items: {item_list}")
        else:
            st.warning("⚠️ Assign at least one item (ID or Upload)")
    
    with col_btn:
        can_generate = bool(all_jewelry_images) and bool(api_key)
        
        if st.button("🚀 GENERATE PHOTO", type="primary", use_container_width=True, disabled=not can_generate):
            with st.spinner("🎨 Generating jewelry photo..."):
                img_bytes, error = generate_image_multi_finger(api_key, all_jewelry_images, user_edited_prompt)
                
                if img_bytes:
                    st.session_state.generated_result = img_bytes
                    st.success("✅ Done!")
                    st.rerun()
                else:
                    st.error(f"❌ Failed: {error}")
        
        if st.button("🔄 Reset / Clear All", use_container_width=True, on_click=reset_app_state):
            pass
    
    # --- DISPLAY RESULT & EDIT SECTION (NEW) ---
    if st.session_state.generated_result:
        st.divider()
        st.subheader("✨ Generated Result")
        
        # แสดงรูปภาพผลลัพธ์
        st.image(st.session_state.generated_result, use_column_width=True, caption="Current Generated Image")
        
        # --- ส่วนแก้ไขรูปภาพ (NEW SECTION) ---
        st.markdown("### 🎨 Edit This Image")
        edit_col1, edit_col2 = st.columns([3, 1])
        
        with edit_col1:
            edit_instructions = st.text_area(
                "Edit Instructions", 
                placeholder="Ex: Move the ring to the ring finger, make the hand whiter, make the ring smaller...",
                height=100,
                key="result_edit_prompt"
            )
            
        with edit_col2:
            st.write("") # Spacer
            st.write("") # Spacer
            if st.button("🔄 Apply Edits", type="primary", use_container_width=True, disabled=not edit_instructions):
                with st.spinner("🎨 Applying edits to image..."):
                    # เรียกฟังก์ชันแก้ไข โดยส่งรูปล่าสุด + คำสั่งแก้ไขไป
                    new_img_bytes, edit_error = edit_generated_image(
                        api_key, 
                        st.session_state.generated_result, 
                        edit_instructions
                    )
                    
                    if new_img_bytes:
                        # อัปเดตผลลัพธ์ด้วยรูปใหม่
                        st.session_state.generated_result = new_img_bytes
                        st.success("✅ Edits Applied!")
                        st.rerun() # รีเฟรชหน้าจอเพื่อแสดงรูปใหม่
                    else:
                        st.error(f"❌ Edit Failed: {edit_error}")

        st.divider()
        
        # --- DOWNLOAD & UPLOAD SECTION ---
        col_dl, col_up = st.columns([1, 2])
        
        with col_dl:
            st.markdown("### 💾 Download")
            st.download_button(
                "📥 Download Image",
                st.session_state.generated_result,
                "jewelry_gen.jpg",
                "image/jpeg",
                use_container_width=True,
                type="secondary"
            )
            
        with col_up:
            st.markdown("### ☁️ Upload to Shopify")
            target_upload_id = st.text_input("Target Product ID", key="target_upload_id", placeholder="Ex: 8234...", help="ID ของสินค้าปลายทางที่จะเอารูปนี้ไปใส่")
            
            if st.button("⬆️ Generate SEO & Upload", type="primary", use_container_width=True, disabled=not target_upload_id):
                
                with st.spinner(f"🔍 Fetching details for Product ID: {target_upload_id}..."):
                    t_title, t_handle = get_target_product_details(sh_shop, sh_token, target_upload_id)
                
                if not t_title:
                    st.error("❌ Product ID Not Found in Shopify.")
                else:
                    with st.spinner(f"🧠 Generating SEO for '{t_title}'..."):
                        seo_data = generate_seo_data(
                            api_key, 
                            st.session_state.generated_result, 
                            t_title, 
                            t_handle
                        )
                        final_filename = seo_data.get("filename", f"{t_handle}.jpg")
                        final_alt = seo_data.get("alt_text", t_title)
                        
                        st.info(f"📄 File: `{final_filename}`\n🏷️ Alt: `{final_alt}`")
                    
                    with st.spinner("☁️ Uploading..."):
                        success, resp = upload_image_to_shopify(
                            sh_shop, sh_token, 
                            target_upload_id, 
                            st.session_state.generated_result, 
                            final_filename, 
                            final_alt
                        )
                        
                        if success:
                            st.success(f"✅ Uploaded Successfully to '{t_title}'!")
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
