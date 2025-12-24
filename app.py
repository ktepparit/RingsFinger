import streamlit as st
import json
import requests
import base64
from io import BytesIO
from PIL import Image
import time
import re

# --- 1. CONFIGURATION ---
st.set_page_config(layout="wide", page_title="Ring AI Generator - Multi Finger")

# --- 2. ฟังก์ชันตรวจสอบรหัสผ่าน ---
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

st.toast("ยินดีต้อนรับ! เข้าสู่ระบบสำเร็จ", icon="✅")

# Model ID
MODEL_IMAGE_GEN = "models/gemini-3-pro-image-preview"

# --- HELPER: CLEANER ---
def clean_key(value):
    if value is None: return ""
    return str(value).strip().replace(" ", "").replace('"', "").replace("'", "").replace("\n", "")

# --- HELPER: SAFE IMAGE LOADER ---
def safe_st_image(url, width=None, caption=None):
    if not url: return
    try:
        clean_url = str(url).strip().replace(" ", "").replace("\n", "")
        if clean_url.startswith("http"):
            st.image(clean_url, width=width, caption=caption)
    except Exception:
        st.warning("⚠️ Image unavailable")

# --- HELPER: RESET STATE FUNCTION ---
def reset_app_state():
    """ฟังก์ชันสำหรับล้างค่าทั้งหมดใน Form รวมทั้งรูปที่ Fetch มาจาก Shopify"""
    st.session_state.generated_result = None
    
    keys_to_clear = []
    for key in st.session_state.keys():
        # เพิ่มการล้างค่า fetch_shop_
        if (key.startswith("upload_") or 
            key.startswith("var_") or 
            key.startswith("edit_prompt_") or
            key.startswith("fetch_shop_") or
            key == "prev_style_id"):
            keys_to_clear.append(key)
            
    for key in keys_to_clear:
        del st.session_state[key]

# --- SHOPIFY HELPER FUNCTION (NEW) ---
def get_shopify_product_images(shop_url, access_token, product_id):
    """ดึงรูปภาพทั้งหมดจาก Shopify Product ID"""
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
                    # Download Image Bytes
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

# --- DEFAULT PROMPTS ---
DEFAULT_PROMPTS = [
    {
        "id": "p1", "name": "Luxury Hand (Ring)", "category": "Ring",
        "template": "A realistic close-up of a female hand model wearing a ring with {face_size} face size, soft studio lighting, elegant jewelry photography.",
        "variables": "face_size",
        "sample_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c2/Ring_render.jpg/320px-Ring_render.jpg"
    }
]

# --- CLOUD DATABASE FUNCTIONS ---
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

# --- IMAGE HELPER ---
def img_to_base64(img):
    buf = BytesIO()
    if img.mode == 'RGBA': img = img.convert('RGB')
    img.thumbnail((1024, 1024)) 
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()

# --- AI FUNCTION (GEMINI) - BATCH ALL FINGERS ---
def generate_image_multi_finger(api_key, finger_images_dict, base_prompt):
    key = clean_key(api_key)
    url = f"https://generativelanguage.googleapis.com/v1beta/{MODEL_IMAGE_GEN}:generateContent?key={key}"
    
    finger_names = {
        "index": "Index Finger (the finger next to the thumb)",
        "middle": "Middle Finger (the center finger)", 
        "ring": "Ring Finger (the finger between middle and little)",
        "little": "Little Finger (the smallest finger, pinky)"
    }
    
    finger_instructions = []
    image_counter = 1
    rings_count = 0
    ordered_keys = ["index", "middle", "ring", "little"]
    
    for finger_key in ordered_keys:
        if finger_key in finger_images_dict and finger_images_dict[finger_key]:
            num_imgs = len(finger_images_dict[finger_key])
            rings_count += 1
            if num_imgs == 1:
                finger_instructions.append(f"- {finger_names[finger_key]}: MUST wear the ring shown in reference image #{image_counter}")
                image_counter += 1
            else:
                img_range = f"reference images #{image_counter}-{image_counter + num_imgs - 1}"
                finger_instructions.append(f"- {finger_names[finger_key]}: MUST wear the ring combination shown in {img_range}")
                image_counter += num_imgs
    
    instruction_text = "\n".join(finger_instructions)
    
    full_prompt = f"""{base_prompt}

TASK: Generate a professional photograph of a single human hand wearing exactly {rings_count} rings.

STRICT MANDATORY RING PLACEMENT (Follow Exactly):
{instruction_text}

CRITICAL CONSTRAINTS:
1.  ANATOMICAL CORRECTNESS IS PARAMOUNT. Place each ring precisely on the named finger in the instructions above.
2.  DO NOT SHIFT RINGS. Do not place a ring intended for one finger onto an adjacent finger.
3.  REFERENCE ACCURACY. Keep each ring's design, gemstones, and metal texture EXACTLY as shown in its corresponding reference image(s).
4.  Show only ONE hand in the final image.
5.  Ensure lighting and pose highlight all {rings_count} rings clearly.
"""

    parts = [{"text": full_prompt}]
    
    for finger_key in ordered_keys:
        if finger_key in finger_images_dict:
            for img in finger_images_dict[finger_key]:
                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": img_to_base64(img)}})
    
    try:
        res = requests.post(
            url, 
            json={
                "contents": [{"parts": parts}], 
                "generationConfig": {"temperature": 0.2} 
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
st.title("💍 Ring AI Generator - Multi Finger Batch")
st.caption("Enter Product ID or Upload references for each finger.")

# --- TABS ---
tab1, tab2 = st.tabs(["✨ Generate Image", "📚 Library Manager"])

# ============= TAB 1: GENERATE IMAGE =============
with tab1:
    # --- STEP 1: SELECT STYLE ---
    st.subheader("1️⃣ Select Ring Style Template")
    
    lib = st.session_state.library
    ring_prompts = [p for p in lib if p.get('category') == 'Ring']
    
    if not ring_prompts:
        st.error("❌ No Ring templates found.")
        st.stop()
    
    col_style1, col_style2 = st.columns([2, 1])
    
    with col_style1:
        selected_style = st.selectbox("Choose Ring Style", ring_prompts, format_func=lambda x: x.get('name', 'Unknown'), key="style_select")
        
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
        user_edited_prompt = st.text_area("Base Instruction", value=final_base_prompt, height=150, key=prompt_key)
    
    with col_style2:
        if selected_style.get("sample_url"):
            st.write("**Sample:**")
            safe_st_image(selected_style["sample_url"], width=200)
    
    st.divider()
    
    # --- STEP 2: INPUT FOR EACH FINGER (SHOPIFY + UPLOAD) ---
    st.subheader("2️⃣ Setup Each Finger (Product ID or Upload)")
    
    fingers = [
        {"key": "index", "name": "Index Finger", "emoji": "☝️"},
        {"key": "middle", "name": "Middle Finger", "emoji": "🖕"},
        {"key": "ring", "name": "Ring Finger", "emoji": "💍"},
        {"key": "little", "name": "Little Finger", "emoji": "🤙"}
    ]
    
    row1_col1, row1_col2 = st.columns(2)
    row2_col1, row2_col2 = st.columns(2)
    columns_layout = [row1_col1, row1_col2, row2_col1, row2_col2]
    
    finger_images_dict = {}
    
    for idx, finger_info in enumerate(fingers):
        finger_key = finger_info["key"]
        finger_name = finger_info["name"]
        emoji = finger_info["emoji"]
        
        # Session State Key for Fetched Images
        fetch_key = f"fetch_shop_{finger_key}"
        if fetch_key not in st.session_state:
            st.session_state[fetch_key] = []
        
        with columns_layout[idx]:
            with st.container(border=True):
                st.markdown(f"### {emoji} {finger_name}")
                
                # --- A. SHOPIFY INPUT ---
                if sh_shop and sh_token:
                    c_id, c_btn = st.columns([2, 1])
                    prod_id = c_id.text_input("Shopify ID", placeholder="Product ID", key=f"inp_{finger_key}", label_visibility="collapsed")
                    
                    if c_btn.button("Fetch", key=f"btn_{finger_key}"):
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
                
                # --- B. MANUAL UPLOAD ---
                uploaded_files = st.file_uploader(
                    "Or Upload Image",
                    accept_multiple_files=True,
                    type=["jpg", "png"],
                    key=f"upload_{finger_key}", 
                    label_visibility="collapsed"
                )
                
                # --- C. COMBINE & DISPLAY ---
                current_images = []
                
                # 1. Add Fetched
                if st.session_state[fetch_key]:
                    current_images.extend(st.session_state[fetch_key])
                    st.info(f"Using {len(st.session_state[fetch_key])} from Shopify")
                    if st.button("Clear Fetch", key=f"clr_{finger_key}"):
                        st.session_state[fetch_key] = []
                        st.rerun()
                
                # 2. Add Uploaded
                if uploaded_files:
                    current_images.extend([Image.open(f) for f in uploaded_files])
                
                # 3. Store in Main Dict & Preview
                if current_images:
                    finger_images_dict[finger_key] = current_images
                    thumb_cols = st.columns(min(3, len(current_images)))
                    for i, img in enumerate(current_images):
                        thumb_cols[i % 3].image(img, use_column_width=True)
                else:
                    st.caption("⚪ Empty")
    
    st.divider()
    
    # --- STEP 3: GENERATE & RESET ---
    st.subheader("3️⃣ Generate Multi-Finger Photo")
    
    total_fingers = len(finger_images_dict)
    total_images = sum(len(imgs) for imgs in finger_images_dict.values())
    
    col_info, col_btn = st.columns([2, 1])
    
    with col_info:
        if total_fingers > 0:
            st.success(f"✅ Ready: {total_fingers} finger(s) assigned.")
            finger_list = ", ".join([f["name"] for f in fingers if f["key"] in finger_images_dict])
            st.caption(f"📍 Fingers: {finger_list}")
        else:
            st.warning("⚠️ Assign at least one ring (ID or Upload)")
    
    with col_btn:
        can_generate = bool(finger_images_dict) and bool(api_key)
        
        if st.button("🚀 GENERATE PHOTO", type="primary", use_container_width=True, disabled=not can_generate):
            with st.spinner("🎨 Generating multi-finger ring photo..."):
                img_bytes, error = generate_image_multi_finger(api_key, finger_images_dict, user_edited_prompt)
                
                if img_bytes:
                    st.session_state.generated_result = img_bytes
                    st.success("✅ Done!")
                    st.rerun()
                else:
                    st.error(f"❌ Failed: {error}")
        
        if st.button("🔄 Reset / Clear All", use_container_width=True, on_click=reset_app_state):
            pass
    
    # --- DISPLAY RESULT ---
    if st.session_state.generated_result:
        st.divider()
        st.subheader("✨ Generated Result")
        
        col_result1, col_result2 = st.columns([3, 1])
        with col_result1:
            st.image(st.session_state.generated_result, use_column_width=True, caption="Multi-Finger Ring Photo")
        
        with col_result2:
            st.download_button(
                "📥 Download",
                st.session_state.generated_result,
                "multi_finger_rings.jpg",
                "image/jpeg",
                use_container_width=True,
                type="primary"
            )
            if st.button("🔄 Generate Again", use_container_width=True):
                st.session_state.generated_result = None
                st.rerun()

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
