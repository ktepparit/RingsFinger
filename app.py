import streamlit as st
import json
import requests
import base64
from io import BytesIO
from PIL import Image
import time
import re

# --- CONFIGURATION ---
st.set_page_config(layout="wide", page_title="Ring AI Generator - Multi Finger")

# Model ID
MODEL_IMAGE_GEN = "models/gemini-3-pro-image-preview"

# --- HELPER: CLEANER ---
def clean_key(value):
    if value is None: 
        return ""
    return str(value).strip().replace(" ", "").replace('"', "").replace("'", "").replace("\n", "")

# --- HELPER: SAFE IMAGE LOADER ---
def safe_st_image(url, width=None, caption=None):
    if not url: 
        return
    try:
        clean_url = str(url).strip().replace(" ", "").replace("\n", "")
        if clean_url.startswith("http"):
            st.image(clean_url, width=width, caption=caption)
    except Exception:
        st.warning("⚠️ Image unavailable")

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
        
        if not API_KEY or not BIN_ID: 
            return DEFAULT_PROMPTS
            
        url = f"https://api.jsonbin.io/v3/b/{BIN_ID}/latest"
        headers = {"X-Master-Key": API_KEY}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            return response.json().get("record", DEFAULT_PROMPTS)
        return DEFAULT_PROMPTS
    except: 
        return DEFAULT_PROMPTS

def save_prompts(data):
    try:
        raw_key = st.secrets.get("JSONBIN_API_KEY", "")
        raw_bin = st.secrets.get("JSONBIN_BIN_ID", "")
        API_KEY = clean_key(raw_key)
        BIN_ID = clean_key(raw_bin)
        
        url = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
        headers = {"Content-Type": "application/json", "X-Master-Key": API_KEY}
        requests.put(url, json=data, headers=headers, timeout=10)
    except Exception as e: 
        st.error(f"Save failed: {e}")

# --- IMAGE HELPER ---
def img_to_base64(img):
    buf = BytesIO()
    if img.mode == 'RGBA': 
        img = img.convert('RGB')
    img.thumbnail((1024, 1024)) 
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()

# --- AI FUNCTION (GEMINI) - BATCH ALL FINGERS ---
def generate_image_multi_finger(api_key, finger_images_dict, base_prompt):
    """
    finger_images_dict: {"index": [img1, img2], "middle": [img3], ...}
    base_prompt: The prompt text (user edited)
    """
    key = clean_key(api_key)
    url = f"https://generativelanguage.googleapis.com/v1beta/{MODEL_IMAGE_GEN}:generateContent?key={key}"
    
    # สร้าง instruction ที่บอกว่าแต่ละนิ้วใส่แหวนอะไร
    finger_names = {
        "index": "index finger",
        "middle": "middle finger", 
        "ring": "ring finger",
        "little": "little finger"
    }
    
    finger_instructions = []
    image_counter = 1
    
    for finger_key in ["index", "middle", "ring", "little"]:
        if finger_key in finger_images_dict and finger_images_dict[finger_key]:
            num_imgs = len(finger_images_dict[finger_key])
            if num_imgs == 1:
                finger_instructions.append(f"- {finger_names[finger_key]}: wearing the ring shown in image #{image_counter}")
                image_counter += 1
            else:
                img_range = f"images #{image_counter}-{image_counter + num_imgs - 1}"
                finger_instructions.append(f"- {finger_names[finger_key]}: wearing the ring shown in {img_range}")
                image_counter += num_imgs
    
    instruction_text = "\n".join(finger_instructions)
    
    full_prompt = f"""{base_prompt}

IMPORTANT RING PLACEMENT:
{instruction_text}

Constraints:
- Show ONE hand with all specified rings worn on their designated fingers
- Keep each ring design EXACTLY as shown in the reference images (same shape, gemstones, texture)
- Only improve lighting, hand pose, background, and photography quality
- Do not hallucinate or modify ring details"""

    # สร้าง parts: text + images ตามลำดับ
    parts = [{"text": full_prompt}]
    
    for finger_key in ["index", "middle", "ring", "little"]:
        if finger_key in finger_images_dict:
            for img in finger_images_dict[finger_key]:
                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": img_to_base64(img)}})
    
    try:
        res = requests.post(
            url, 
            json={
                "contents": [{"parts": parts}], 
                "generationConfig": {"temperature": 0.3}
            }, 
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        
        if res.status_code != 200: 
            return None, f"API Error {res.status_code}: {res.text}"
            
        content = res.json().get("candidates", [])[0].get("content", {}).get("parts", [])[0]
        
        if "inline_data" in content: 
            return base64.b64decode(content["inline_data"]["data"]), None
        if "inlineData" in content: 
            return base64.b64decode(content["inlineData"]["data"]), None
        if "text" in content: 
            return None, f"Model returned text: {content['text']}"
            
        return None, "Unknown format"
    except Exception as e: 
        return None, str(e)

# --- SESSION STATE INIT ---
if "library" not in st.session_state: 
    st.session_state.library = get_prompts()

if "generated_result" not in st.session_state:
    st.session_state.generated_result = None

if "edit_target" not in st.session_state:
    st.session_state.edit_target = None

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
    
    if "JSONBIN_API_KEY" in st.secrets: 
        st.caption("✅ Database Connected")
    else: 
        st.warning("⚠️ Local Mode")

# --- MAIN UI ---
st.title("💍 Ring AI Generator - Multi Finger Batch")
st.caption("Upload ring references for up to 4 fingers and generate ONE professional photo with all rings")

# --- TABS ---
tab1, tab2 = st.tabs(["✨ Generate Image", "📚 Library Manager"])

# ============= TAB 1: GENERATE IMAGE =============
with tab1:
    # --- STEP 1: SELECT STYLE ---
    st.subheader("1️⃣ Select Ring Style Template")
    
    lib = st.session_state.library
    ring_prompts = [p for p in lib if p.get('category') == 'Ring']
    
    if not ring_prompts:
        st.error("❌ No Ring templates found. Please add templates in Library Manager.")
        st.stop()
    
    col_style1, col_style2 = st.columns([2, 1])
    
    with col_style1:
        # 1. Select Box
        selected_style = st.selectbox(
            "Choose Ring Style", 
            ring_prompts, 
            format_func=lambda x: x.get('name', 'Unknown'),
            key="style_select"
        )
        
        # 2. Variable Inputs
        template_text = selected_style.get('template', '')
        vars_list = [v.strip() for v in selected_style.get('variables', '').split(",") if v.strip()]
        user_vals = {}
        
        if vars_list:
            st.write("**Customize Parameters:**")
            cols = st.columns(len(vars_list))
            for i, v in enumerate(vars_list):
                # ใช้ Dynamic Key เพื่อความเสถียรของ UI
                user_vals[v] = cols[i].text_input(v, key=f"var_{selected_style['id']}_{v}")
        
        # 3. สร้างข้อความ Prompt
        final_base_prompt = template_text
        for k, v in user_vals.items():
            final_base_prompt = final_base_prompt.replace(f"{{{k}}}", v)
        
        # 4. แสดงช่อง Base Instruction (ใช้ Dynamic Key แก้ปัญหาข้อความไม่เปลี่ยน)
        st.write("**Preview & Edit Prompt:**")
        
        # --- KEY FIX IS HERE ---
        # การใส่ ID ลงไปใน key จะทำให้ Streamlit สร้าง widget ใหม่ทุกครั้งที่เปลี่ยน Style
        prompt_key = f"edit_prompt_area_{selected_style['id']}"
        
        user_edited_prompt = st.text_area(
            "Base Instruction", 
            value=final_base_prompt, 
            height=150, 
            disabled=False, 
            key=prompt_key
        )
    
    with col_style2:
        if selected_style.get("sample_url"):
            st.write("**Sample:**")
            safe_st_image(selected_style["sample_url"], width=200)
    
    st.divider()
    
    # --- STEP 2: UPLOAD REFERENCES ---
    st.subheader("2️⃣ Upload Ring References for Each Finger")
    st.caption("Upload images for the fingers you want to show rings on (1-4 fingers)")
    
    fingers = [
        {"key": "index", "name": "Index Finger", "emoji": "☝️"},
        {"key": "middle", "name": "Middle Finger", "emoji": "🖕"},
        {"key": "ring", "name": "Ring Finger", "emoji": "💍"},
        {"key": "little", "name": "Little Finger", "emoji": "🤙"}
    ]
    
    # Layout: 2x2 grid
    row1_col1, row1_col2 = st.columns(2)
    row2_col1, row2_col2 = st.columns(2)
    columns_layout = [row1_col1, row1_col2, row2_col1, row2_col2]
    
    finger_images_dict = {}
    
    for idx, finger_info in enumerate(fingers):
        finger_key = finger_info["key"]
        finger_name = finger_info["name"]
        emoji = finger_info["emoji"]
        
        with columns_layout[idx]:
            with st.container(border=True):
                st.markdown(f"### {emoji} {finger_name}")
                
                uploaded_files = st.file_uploader(
                    "Upload ring reference(s)",
                    accept_multiple_files=True,
                    type=["jpg", "png"],
                    key=f"upload_{finger_key}",
                    label_visibility="collapsed"
                )
                
                if uploaded_files:
                    images = [Image.open(f) for f in uploaded_files]
                    finger_images_dict[finger_key] = images
                    
                    st.caption(f"✅ {len(images)} image(s) uploaded")
                    thumb_cols = st.columns(min(3, len(images)))
                    for i, img in enumerate(images):
                        thumb_cols[i % len(thumb_cols)].image(img, use_column_width=True)
                else:
                    st.caption("⚪ No images (finger will be empty)")
    
    st.divider()
    
    # --- STEP 3: GENERATE ---
    st.subheader("3️⃣ Generate Multi-Finger Photo")
    
    total_fingers = len(finger_images_dict)
    total_images = sum(len(imgs) for imgs in finger_images_dict.values())
    
    col_info, col_btn = st.columns([2, 1])
    
    with col_info:
        if total_fingers > 0:
            st.success(f"✅ Ready: {total_fingers} finger(s) with {total_images} reference image(s)")
            finger_list = ", ".join([f["name"] for f in fingers if f["key"] in finger_images_dict])
            st.caption(f"📍 Fingers: {finger_list}")
        else:
            st.warning("⚠️ Please upload at least one ring reference")
    
    with col_btn:
        can_generate = bool(finger_images_dict) and bool(api_key)
        
        if st.button(
            "🚀 GENERATE PHOTO", 
            type="primary", 
            use_container_width=True,
            disabled=not can_generate
        ):
            with st.spinner("🎨 Generating multi-finger ring photo..."):
                # ส่งค่า user_edited_prompt (ที่แก้ไขแล้ว) ไปยังฟังก์ชัน AI
                img_bytes, error = generate_image_multi_finger(
                    api_key, 
                    finger_images_dict, 
                    user_edited_prompt 
                )
                
                if img_bytes:
                    st.session_state.generated_result = img_bytes
                    st.success("✅ Photo generated successfully!")
                    st.rerun()
                else:
                    st.error(f"❌ Generation failed: {error}")
    
    # --- DISPLAY RESULT ---
    if st.session_state.generated_result:
        st.divider()
        st.subheader("✨ Generated Result")
        
        col_result1, col_result2 = st.columns([3, 1])
        
        with col_result1:
            st.image(
                st.session_state.generated_result, 
                use_column_width=True,
                caption="Multi-Finger Ring Photo"
            )
        
        with col_result2:
            st.download_button(
                "📥 Download Image",
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
    st.caption("Manage your ring photo style templates")
    
    target = st.session_state.edit_target
    title = f"✏️ Edit: {target['name']}" if target else "➕ Add New Template"
    
    with st.form("lib_form", border=True):
        st.write(f"**{title}**")
        
        c1, c2 = st.columns(2)
        n = c1.text_input("Template Name", value=target['name'] if target else "")
        c = c2.text_input("Category", value=target['category'] if target else "Ring")
        
        t = st.text_area("Prompt Template", value=target['template'] if target else "", height=120)
        
        c3, c4 = st.columns(2)
        v = c3.text_input("Variables (comma-separated)", value=target['variables'] if target else "")
        u = c4.text_input("Sample Image URL", value=target['sample_url'] if target else "")
        
        cols = st.columns([1, 1, 3])
        
        if cols[0].form_submit_button("💾 Save", type="primary"):
            new = {
                "id": target['id'] if target else str(len(st.session_state.library) + 1000),
                "name": n,
                "category": c,
                "template": t,
                "variables": v,
                "sample_url": u
            }
            
            if target:
                for idx, item in enumerate(st.session_state.library):
                    if item['id'] == target['id']:
                        st.session_state.library[idx] = new
                        break
            else:
                st.session_state.library.append(new)
            
            save_prompts(st.session_state.library)
            st.session_state.edit_target = None
            st.success("✅ Saved!")
            st.rerun()
        
        if target and cols[1].form_submit_button("❌ Cancel"):
            st.session_state.edit_target = None
            st.rerun()
    
    st.divider()
    st.write("**Existing Templates:**")
    
    ring_items = [p for p in st.session_state.library if p.get('category') == 'Ring']
    
    if not ring_items:
        st.info("No Ring templates yet. Add one above!")
    
    for i, p in enumerate(ring_items):
        c1, c2, c3, c4 = st.columns([1, 4, 1, 1])
        
        if p.get("sample_url"):
            with c1:
                safe_st_image(p["sample_url"], width=60)
        
        c2.write(f"**{p.get('name')}**")
        c2.caption(f"Variables: {p.get('variables', 'None')}")
        
        if c3.button("✏️", key=f"e{i}"):
            st.session_state.edit_target = p
            st.rerun()
        
        if c4.button("🗑️", key=f"d{i}"):
            st.session_state.library.remove(p)
            save_prompts(st.session_state.library)
            st.rerun()
        
        st.divider()

# --- FOOTER ---
st.markdown("---")
st.caption("💎 Made for jewelry creators | Powered by Gemini AI")
