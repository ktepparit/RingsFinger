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
        # 1. Selectbox
        selected_style = st.selectbox(
            "Choose Ring Style", 
            ring_prompts, 
            format_func=lambda x: x.get('name', 'Unknown'),
            key="style_select"
        )
        
        # 2. Variables Input
        template_text = selected_style.get('template', '')
        vars_list = [v.strip() for v in selected_style.get('variables', '').split(",") if v.strip()]
        user_vals = {}
        
        if vars_list:
            st.write("**Customize Parameters:**")
            cols = st.columns(len(vars_list))
            for i, v in enumerate(vars_list):
                # ใช้ key แบบ dynamic เพื่อแยก input ของแต่ละ style ออกจากกัน
                user_vals[v] = cols[i].text_input(v, key=f"var_{selected_style['id']}_{v}")
        
        # 3. Create Final Prompt String
        final_base_prompt = template_text
        for k, v in user_vals.items():
            final_base_prompt = final_base_prompt.replace(f"{{{k}}}", v)
        
        # 4. Preview & Edit Prompt (FIXED HERE)
        st.write("**Preview & Edit Prompt:**")
        
        # เทคนิคแก้ไข: ใช้ ID ของ Style มาเป็นส่วนหนึ่งของ Key
        # เมื่อเปลี่ยน Style -> Key เปลี่ยน -> Streamlit สร้าง Text Area ใหม่ -> ค่าเปลี่ยนทันที
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
    
    # ... (ส่วน Upload รูปภาพ เหมือนเดิม ไม่ต้องแก้) ...
    
    # ... (ส่วนปุ่ม Generate ต้องเช็คว่าส่ง user_edited_prompt เข้าไป) ...
