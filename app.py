# --- AI FUNCTION (GEMINI) - IMPROVED LOGIC ---
def generate_image_multi_finger(api_key, all_images_dict, base_prompt):
    key = clean_key(api_key)
    url = f"https://generativelanguage.googleapis.com/v1beta/{MODEL_IMAGE_GEN}:generateContent?key={key}"
    
    # Mapping ชื่อและคำอธิบายตำแหน่งให้ชัดเจนที่สุด
    jewelry_locations = {
        "index": "Index Finger (finger next to thumb)",
        "middle": "Middle Finger (longest center finger)", 
        "ring": "Ring Finger (finger between middle and little)",
        "little": "Little Finger (pinky, smallest finger)",
        "bracelet": "Wrist",
        "necklace": "Neck"
    }
    
    # แยกรายการที่มีรูป (Active) และไม่มีรูป (Empty)
    active_items = []
    empty_fingers = []
    
    # เช็คเฉพาะนิ้ว (เพื่อสั่งให้ว่างถ้าไม่มีรูป)
    finger_keys = ["index", "middle", "ring", "little"]
    for f_key in finger_keys:
        if f_key not in all_images_dict or not all_images_dict[f_key]:
            empty_fingers.append(jewelry_locations[f_key])
            
    # เช็ครายการทั้งหมดเพื่อเตรียมรูปภาพ
    ordered_keys = ["index", "middle", "ring", "little", "bracelet", "necklace"]
    parts = [] 
    
    # ส่วนที่ 1: Base Prompt + Framing
    has_necklace = "necklace" in all_images_dict and all_images_dict["necklace"]
    framing = "Portrait/Bust shot showing Hand and Neck" if has_necklace else "Close-up Macro shot of Hand and Wrist only"
    
    prompt_intro = f"""
    {base_prompt}
    
    IMAGE SETTING:
    - TYPE: Professional Jewelry Photography
    - FRAMING: {framing}
    - SUBJECT: A single female model.
    """
    
    # ส่วนที่ 2: สร้าง Instruction แบบเจาะจง (Active Items)
    positive_instructions = []
    image_global_index = 1
    
    for item_key in ordered_keys:
        if item_key in all_images_dict and all_images_dict[item_key]:
            imgs = all_images_dict[item_key]
            count = len(imgs)
            loc_name = jewelry_locations[item_key]
            
            # สร้างข้อความระบุเจาะจง
            if count == 1:
                ref_text = f"reference image #{image_global_index}"
                image_global_index += 1
            else:
                ref_text = f"reference images #{image_global_index} to #{image_global_index + count - 1}"
                image_global_index += count
            
            instruction = f"   * {loc_name.upper()}: WEARING the jewelry design shown in {ref_text}."
            positive_instructions.append(instruction)
            
            # เก็บรูปเข้า parts ทันที (เพื่อให้ลำดับตรงกับ text)
            for img in imgs:
                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": img_to_base64(img)}})

    # ส่วนที่ 3: คำสั่งห้าม (Negative Constraints) - สำคัญมาก!
    negative_instructions = []
    if empty_fingers:
        empty_list_str = ", ".join(empty_fingers)
        negative_instructions.append(f"   * The following fingers MUST BE BARE (No Rings): {empty_list_str}.")
    
    negative_instructions.append("   * Do NOT put rings on the Thumb.")
    negative_instructions.append("   * Do NOT duplicate items.")
    
    # รวม Prompt ทั้งหมด
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

    # เอา Text Prompt ไปไว้หน้าสุดของ parts
    parts.insert(0, {"text": full_prompt_text})
    
    try:
        # ปรับ temperature ลงต่ำอีกนิดเพื่อให้ AI ทำตามคำสั่งเคร่งครัดขึ้น
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
