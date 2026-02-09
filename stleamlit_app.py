import warnings
import logging
import sys
import streamlit as st
import pandas as pd
import random
import plotly.graph_objects as go
from PIL import Image
import base64
import json
import io
import torch
import transformers
from transformers import VisionEncoderDecoderModel, ViTImageProcessor, AutoTokenizer

# ----------------------------------------------------
# 0. ログ・警告の完全抑制
# ----------------------------------------------------
logging.getLogger("transformers").setLevel(logging.ERROR)
warnings.filterwarnings('ignore')

# ----------------------------------------------------
# 1. ライブラリのインポート
# ----------------------------------------------------
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    import requests
    from streamlit import cache_resource, cache_data
except ImportError as e:
    st.error(f"🔴 必要なライブラリが見つかりません: {e}")

# ----------------------------------------------------
# 2. Moondream2 モデルのロード (ここが最強の変更点！)
# ----------------------------------------------------
@st.cache_resource
def load_food_ai_model(): 
    # 中身は安定の Vit-GPT2
    from transformers import VisionEncoderDecoderModel, ViTImageProcessor, AutoTokenizer
    model_name = "nlpconnect/vit-gpt2-image-captioning"
    
    processor = ViTImageProcessor.from_pretrained(model_name)
    model = VisionEncoderDecoderModel.from_pretrained(model_name)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    return processor, model, tokenizer, device

# 🔥 ここで関数を呼び出す（51行目のエラーをこれで解決）
processor, blip_model, tokenizer, device = load_food_ai_model()

# ----------------------------------------------------
# 3. Firebase 初期化
# ----------------------------------------------------
@cache_resource
def initialize_firebase():
    try:
        json_string = st.secrets.get("firebase_credentials_json", "")
        if json_string:
            creds_dict = json.loads(json_string)
            if 'private_key' in creds_dict:
                creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
            if not firebase_admin._apps:
                cred = credentials.Certificate(creds_dict)
                firebase_admin.initialize_app(cred)
            db = firestore.client()
            return db, True, db.collection("users").document().id
    except: pass
    return None, False, "default_user"

@cache_data(ttl=3600)
def load_nutrition_data(_db_client, user_id):
    if _db_client is None: return {}
    try:
        collection_ref = _db_client.collection(f"users/{user_id}/nutrition_logs")
        docs = collection_ref.stream()
        history_data = {}
        for doc in docs:
            data = doc.to_dict()
            meal_type = data.get("meal_type", "不明な食事")
            history_data[meal_type] = data
        return history_data
    except: return {}

def save_nutrition_data(meal_type, nutrition_data):
    if not st.session_state.auth_ready or st.session_state.db is None: return
    try:
        doc_ref = st.session_state.db.collection(f"users/{st.session_state.user_id}/nutrition_logs").document()
        data_to_save = {**nutrition_data, "meal_type": meal_type, "timestamp": firestore.SERVER_TIMESTAMP}
        doc_ref.set(data_to_save)
        st.success(f"✅ {meal_type}の記録を保存しました！")
        load_nutrition_data.clear()
        st.session_state.history = load_nutrition_data(st.session_state.db, st.session_state.user_id)
    except Exception as e: st.error(f"保存エラー: {e}")

# ----------------------------------------------------
# 4. セッションステート初期化
# ----------------------------------------------------
if 'db' not in st.session_state:
    db_client, auth_status, user_id = initialize_firebase()
    st.session_state.db, st.session_state.auth_ready, st.session_state.user_id = db_client, auth_status, user_id
if 'history' not in st.session_state: st.session_state.history = {}
if 'detected_foods' not in st.session_state: st.session_state.detected_foods = []
if 'manual_mode' not in st.session_state: st.session_state.manual_mode = False
if 'total_nutrition_for_day' not in st.session_state:
    st.session_state.total_nutrition_for_day = {"calories": 0, "protein": 0, "fat": 0, "carbohydrates": 0}
if 'last_added_nutrition' not in st.session_state:
    st.session_state.last_added_nutrition = {"calories": 0, "protein": 0, "fat": 0, "carbohydrates": 0}
if 'last_selected_meal_type' not in st.session_state: st.session_state.last_selected_meal_type = "朝食"
if 'show_total_chart' not in st.session_state: st.session_state.show_total_chart = True
if 'data_added' not in st.session_state: st.session_state.data_added = False

# ----------------------------------------------------
# 5. CSVデータロード
# ----------------------------------------------------
@cache_data
def load_nutrition_data_from_csv():
    try:
        df = pd.read_csv("food_nutrition.csv")
        df_cleaned = df.drop_duplicates(subset=['food'], keep='last')
        return df_cleaned.set_index('food').T.to_dict(), list(df_cleaned['food'])
    except:
        d = {"ごはん": {"calories": 168, "protein": 2.5, "fat": 0.3, "carbohydrates": 37.1}}
        return d, list(d.keys())

nutrition_dict, available_foods = load_nutrition_data_from_csv()

food_categories = {
    "朝食": ["クロワッサン", "プレーンヨーグルト", "イチゴ", "ラズベリー", "トースト", "ジャム", "牛乳", "シリアル"],
    "昼食・夕食": ["ごはん", "鶏肉", "味噌汁", "パスタ", "ステーキ", "ハンバーグ", "カレーライス", "ラーメン", "餃子"],
    "野菜・フルーツ": ["トマト", "ブロッコリー", "サラダ", "バナナ", "リンゴ", "アボカド"],
    "おやつ": ["チョコレート", "クッキー", "アイスクリーム", "ドーナツ", "ポテトチップス"],
}
daily_needs = {"calories": 2000, "protein": 60, "fat": 50, "carbohydrates": 300}
meal_ratios = {"朝食": 0.25, "昼食": 0.35, "夕食": 0.30, "おやつ": 0.10}

# ----------------------------------------------------
# 6. UI & デザイン
# ----------------------------------------------------
st.set_page_config(page_title="栄養チェッカー", layout="centered")
st.title("食事画像から栄養をチェック！")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=M+PLUS+Rounded+1c:wght@400;700&display=swap');
    html, body, .stApp { font-family: 'M PLUS Rounded 1c', sans-serif; color: #876358; background: linear-gradient(135deg, #E0F7E0 0%, #F5E8C7 100%) !important; }
    h1, h2, h3, h4 { color: #E7889A !important; }
    div[data-testid="stButton"] button { background-color: #876358 !important; color: #FFF !important; border-radius: 25px !important; font-weight: bold; border: none !important; box-shadow: 0 4px 0 #5d4037; transition: all 0.2s ease; padding: 0.5rem 1.5rem !important; }
    div[data-testid="stButton"] button:active { transform: translateY(3px); box-shadow: 0 1px 0 #5d4037; }
    div[data-testid="stButton"] button[kind="primary"] { background-color: #E7889A !important; box-shadow: 0 4px 0 #c56e7e; }
    .advice-card { background-color: #FFFFFF !important; border-radius: 20px !important; padding: 25px !important; margin: 20px 0 !important; box-shadow: 0 10px 20px rgba(0,0,0,0.05); color: #876358 !important; position: relative; }
    .advice-card::before { content: ""; position: absolute; top: 20px; bottom: 20px; left: 0; width: 6px; background: #E7889A; border-radius: 0 10px 10px 0; }
    .advice-title { color: #E7889A; font-weight: bold; font-size: 1.1em; margin-bottom: 8px; }
</style>
""", unsafe_allow_html=True)

# ----------------------------------------------------
# 7. メインロジック
# ----------------------------------------------------
camera_photo = st.camera_input("📸 カメラで食事を撮影")
uploaded_file = st.file_uploader("📂 または画像をアップロード", type=["jpg", "jpeg", "png"])
final_input_file = camera_photo if camera_photo else uploaded_file

if final_input_file:
    st.image(final_input_file, caption='分析対象の画像', width="stretch")
    selected_meal_type = st.selectbox("どの食事ですか？", options=list(meal_ratios.keys()))

    if st.button("画像から自動分析 (AI)", type='primary'):
        st.session_state.manual_mode = False
        with st.spinner("お皿の上の料理をすべてリストアップ中..."):
            image = Image.open(io.BytesIO(final_input_file.getvalue())).convert("RGB")
            
            # --- ここから Vit-GPT2 複数認識モード ---
            pixel_values = processor(images=image, return_tensors="pt").pixel_values.to(device)

            # AIに「8通りの可能性」を同時に考えさせ、食材を網羅する
            output_ids = blip_model.generate(
                pixel_values,
                max_length=50,
                num_beams=15,             # 探索を広げる
                num_return_sequences=8,   # 8パターンの回答を出す
                repetition_penalty=3.5,   # 同じ言葉を禁止して他の食材を探させる
                do_sample=True,
                temperature=0.9,
                pad_token_id=tokenizer.eos_token_id
            )
            
            combined_caption = ""
            for out in output_ids:
                combined_caption += tokenizer.decode(out, skip_special_tokens=True).lower() + " "
            
            st.write(f"🔍 AI解析のヒント: `{combined_caption}`")

            # 🌟 キーワードマッピング（英語名 -> CSVの日本語名）
            # ここにCSVにある料理名をどんどん追加すると精度が上がります
            keyword_map = {
                "croissant": "クロワッサン", "bread": "食パン", "toast": "トースト",
                "yogurt": "プレーンヨーグルト", "berry": "ラズベリー", "berries": "ラズベリー",
                "strawberry": "イチゴ", "fruit": "イチゴ", "jam": "ジャム",
                "milk": "牛乳", "coffee": "コーヒー", "rice": "ごはん",
                "chicken": "鶏肉", "meat": "鶏肉", "egg": "卵", "salad": "サラダ",
                "soup": "味噌汁", "pasta": "パスタ", "pizza": "ピザ", "fish": "鮭",
                "curry": "カレーライス", "ramen": "ラーメン", "noodle": "ラーメン",
                "sandwich": "サンドイッチ", "burger": "ハンバーグ", "tofu": "豆腐"
            }

            detected = []
            for eng, jpn in keyword_map.items():
                if eng in combined_caption:
                    if jpn in available_foods:
                        detected.append(jpn)

            st.session_state.detected_foods = list(set(detected))
            st.session_state.manual_mode = True
            st.rerun()

    st.markdown("---")
    if st.session_state.manual_mode:
        selected_foods = st.multiselect("AIが見つけた料理 (修正可)", options=available_foods, default=st.session_state.detected_foods)

        if st.button("栄養情報を計算"):
            if selected_foods:
                meal_nutri = {"calories": 0, "protein": 0, "fat": 0, "carbohydrates": 0}
                for f in selected_foods:
                    if f in nutrition_dict:
                        for k in meal_nutri: meal_nutri[k] += nutrition_dict[f].get(k, 0)
                
                for k in st.session_state.total_nutrition_for_day:
                    st.session_state.total_nutrition_for_day[k] += meal_nutri[k]
                
                st.session_state.last_added_nutrition = meal_nutri
                st.session_state.last_selected_meal_type = selected_meal_type
                st.session_state.data_added = True
                st.rerun()

# ----------------------------------------------------
# 8. グラフ & アドバイス
# ----------------------------------------------------
if st.session_state.data_added:
    st.markdown("---")
    st.subheader("栄養レポート")
    t = st.session_state.total_nutrition_for_day
    cols = st.columns(4)
    cols[0].metric("カロリー", f"{t['calories']:.0f}kcal")
    cols[1].metric("たんぱく", f"{t['protein']:.1f}g")
    cols[2].metric("脂質", f"{t['fat']:.1f}g")
    cols[3].metric("炭水化物", f"{t['carbohydrates']:.1f}g")

    if st.button("今日一日をリセット"):
        st.session_state.total_nutrition_for_day = {"calories": 0, "protein": 0, "fat": 0, "carbohydrates": 0}
        st.session_state.data_added = False
        st.rerun()

    categories = ["カロリー", "たんぱく質", "脂質", "炭水化物"]
    values = [min((t[k] / daily_needs[k]) * 100, 120) if daily_needs[k]>0 else 0 for k in ["calories", "protein", "fat", "carbohydrates"]]
    
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=[100]*4, theta=categories, fill='toself', name='目標', fillcolor='rgba(231, 136, 154, 0.2)', line_color='rgba(231, 136, 154, 0.5)'))
    fig.add_trace(go.Scatterpolar(r=values, theta=categories, fill='toself', name='摂取', fillcolor='rgba(135, 206, 250, 0.6)', line_color='skyblue'))
    fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 120])), paper_bgcolor='#FDFCF0', title="1日の目標達成度")
    st.plotly_chart(fig, width='stretch')

    if t['calories'] > daily_needs['calories']: advice_msg, icon = "今日は少しエネルギー多め。明日は野菜中心に！", "⚠️"
    elif t['protein'] < (daily_needs['protein'] * 0.5): advice_msg, icon = "タンパク質が不足気味。卵やお肉を足そう！", "🥚"
    else: advice_msg, icon = "完璧なバランス！その調子で頑張ろう✨", "👏"

    st.markdown(f"""
    <div class="advice-card">
        <div class="advice-title">{icon} ちょこっとアドバイス</div>
        <div class="advice-text">{advice_msg}</div>
    </div>
    """, unsafe_allow_html=True)

    if st.session_state.auth_ready:
        st.button("この記録を保存", on_click=save_nutrition_data, args=(st.session_state.last_selected_meal_type, st.session_state.last_added_nutrition))