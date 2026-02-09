import warnings
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
from transformers import BlipProcessor, BlipForConditionalGeneration

# ----------------------------------------------------
# 1. ライブラリのインポートと初期設定
# ----------------------------------------------------
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    import requests
    from streamlit import cache_resource, cache_data
except ImportError as e:
    st.error(f"🔴 必要なライブラリが見つかりません: {e}")

warnings.filterwarnings('ignore', category=DeprecationWarning)

# ----------------------------------------------------
# 2. BLIP モデルのロード (警告対策済み)
# ----------------------------------------------------
@st.cache_resource
def load_blip_model():
    # use_fast=True を指定して警告を抑制
    processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base", use_fast=True)
    model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")
    return processor, model

processor, blip_model = load_blip_model()

def analyze_image_with_blip(uploaded_file):
    try:
        image = Image.open(io.BytesIO(uploaded_file.getvalue())).convert("RGB")
        inputs = processor(image, return_tensors="pt")
        output = blip_model.generate(**inputs, max_new_tokens=40) # 少し長めに生成
        caption = processor.decode(output[0], skip_special_tokens=True)
        return {"caption": caption}
    except Exception as e:
        st.error(f"❌ BLIP解析エラー: {e}")
        return None

# ----------------------------------------------------
# 3. Firebase 初期化 (既存ロジック維持)
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
    try:
        import os
        if os.path.exists("serviceAccountKey.json"):
            if not firebase_admin._apps:
                cred = credentials.Certificate("serviceAccountKey.json")
                firebase_admin.initialize_app(cred)
            db = firestore.client()
            return db, True, "local_developer_user"
    except Exception as e:
        st.warning(f"Firebase接続失敗: {e}")
    return None, False, "default_user"

# データロード・保存関数 (修正なし)
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
# 4. セッションステート初期化 (既存維持)
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
    "朝食": ["クロワッサン", "プレーンヨーグルト", "イチゴ", "ラズベリー", "トースト", "ジャム", "牛乳", "シリアル", "ゆで卵", "パンケーキ", "フレンチトースト", "メロンパン", "あんぱん", "食パン", "バゲット"],
    "昼食・夕食": ["ごはん", "鶏肉", "ほうれん草", "卵", "納豆", "味噌汁", "鮭", "豆腐", "パスタ", "ステーキ", "ハンバーグ", "カレーライス", "ラーメン", "餃子", "炒飯", "サンドイッチ", "カツ丼", "親子丼", "牛丼", "天ぷら", "焼き魚", "煮物", "豚の角煮", "麻婆豆腐", "エビチリ"],
    "野菜・フルーツ": ["トマト", "ブロッコリー", "人参", "きゅうり", "玉ねぎ", "じゃがいも", "サラダ", "バナナ", "リンゴ", "アボカド"],
    "おやつ": ["チョコレート", "クッキー", "アイスクリーム", "ドーナツ", "ポテトチップス"],
}
daily_needs = {"calories": 2000, "protein": 60, "fat": 50, "carbohydrates": 300}
meal_ratios = {"朝食": 0.25, "昼食": 0.35, "夕食": 0.30, "おやつ": 0.10}

# ----------------------------------------------------
# 6. UI & メインロジック
# ----------------------------------------------------
st.set_page_config(page_title="栄養チェッカー", layout="centered")
st.title("食事画像から栄養をチェック！")

st.markdown("""
<style>
    /* Google Fontsから丸文字を読み込み */
    @import url('https://fonts.googleapis.com/css2?family=M+PLUS+Rounded+1c:wght@400;700&display=swap');
    
    html, body, .stApp { 
        font-family: 'M PLUS Rounded 1c', sans-serif; 
        color: #876358; 
        background: linear-gradient(135deg, #E0F7E0 0%, #F5E8C7 100%) !important; 
    }
    
    h1, h2, h3, h4 { color: #E7889A !important; }

    /* タグの装飾 */
    span[data-baseweb="tag"] {
          background-color: #3a943a !important; 
          color: #FFF !important;
          border-radius: 8px !important;
    }

    /* ボタンをぷくっと丸く、浮き出るように */
    div[data-testid="stButton"] button { 
        background-color: #876358 !important; 
        color: #FFF !important; 
        border-radius: 25px !important; /* もっと丸く */
        font-weight: bold; 
        border: none !important;
        box-shadow: 0 4px 0 #5d4037; /* 下側の厚み */
        transition: all 0.2s ease;
        padding: 0.5rem 1.5rem !important;
    }
    
    /* ボタンを押した時の「カチッ」とした動き */
    div[data-testid="stButton"] button:active {
        transform: translateY(3px);
        box-shadow: 0 1px 0 #5d4037;
    }
    
    /* プライマリボタン（AI分析）はピンク */
    div[data-testid="stButton"] button[kind="primary"] { 
        background-color: #E7889A !important; 
        box-shadow: 0 4px 0 #c56e7e;
    }

    /* 💡 アドバイスのカード風デザイン（ここがメインの変更！） */
    .advice-card {
        background-color: #FFFFFF !important;
        border: none !important;
        border-radius: 20px !important;
        padding: 25px !important;
        margin: 20px 0 !important;
        /* ぷくっと浮き出る多重の影 */
        box-shadow: 0 10px 20px rgba(0,0,0,0.05), 0 6px 6px rgba(0,0,0,0.05);
        color: #876358 !important;
        position: relative;
    }
    
    /* 左側のパステルライン */
    .advice-card::before {
        content: "";
        position: absolute;
        top: 20px;
        bottom: 20px;
        left: 0;
        width: 6px;
        background: #E7889A;
        border-radius: 0 10px 10px 0;
    }

    .advice-title {
        color: #E7889A;
        font-weight: bold;
        font-size: 1.1em;
        margin-bottom: 8px;
    }
</style>
""", unsafe_allow_html=True)

camera_photo = st.camera_input("📸 カメラで食事を撮影")
uploaded_file = st.file_uploader("📂 または画像をアップロード", type=["jpg", "jpeg", "png"])
final_input_file = camera_photo if camera_photo else uploaded_file

if final_input_file:
    # 🌟 width="stretch" に修正して警告を解消
    st.image(final_input_file, caption='分析対象の画像', width="stretch")
    
    selected_meal_type = st.selectbox("どの食事ですか？", options=list(meal_ratios.keys()))

    st.subheader("料理の選択方法")
    col_auto, col_manual = st.columns(2)

    with col_auto:
        if st.button("画像から自動分析 (AI)", type='primary'):
            st.session_state.manual_mode = False
            with st.spinner("AIが画像を解析中..."):
                api_result = analyze_image_with_blip(final_input_file)
                if api_result:
                    caption = api_result["caption"].lower()
                    st.write(f"🔍 AI解析結果: `{caption}`")
                    
                    # あなたのリストに対応させた通訳辞書
                    translate_hints = {
                        "croissant": "クロワッサン", "yogurt": "プレーンヨーグルト", 
                        "strawberry": "イチゴ", "raspberry": "ラズベリー", 
                        "toast": "トースト", "jam": "ジャム", "milk": "牛乳", 
                        "cereal": "シリアル", "boiled egg": "ゆで卵", "pancake": "パンケーキ",
                        "french toast": "フレンチトースト", "bread": "食パン", "baguette": "バゲット",
                        "rice": "ごはん", "chicken": "鶏肉", "spinach": "ほうれん草", 
                        "egg": "卵", "natto": "納豆", "miso soup": "味噌汁", 
                        "salmon": "鮭", "tofu": "豆腐", "pasta": "パスタ", "spaghetti": "パスタ",
                        "steak": "ステーキ", "hamburger": "ハンバーグ", "curry": "カレーライス", 
                        "ramen": "ラーメン", "noodles": "ラーメン", "dumpling": "餃子", "gyoza": "餃子",
                        "fried rice": "炒飯", "sandwich": "サンドイッチ", "katsudon": "カツ丼", 
                        "oyakodon": "親子丼", "gyudon": "牛丼", "beef bowl": "牛丼",
                        "tempura": "天ぷら", "grilled fish": "焼き魚", "shrimp": "エビチリ",
                        "tomato": "トマト", "broccoli": "ブロッコリー", "carrot": "人参", 
                        "cucumber": "きゅうり", "onion": "玉ねぎ", "potato": "じゃがいも", 
                        "salad": "サラダ", "banana": "バナナ", "apple": "リンゴ", "avocado": "アボカド",
                        "chocolate": "チョコレート", "cookie": "クッキー", 
                        "ice cream": "アイスクリーム", "donut": "ドーナツ", "chips": "ポテトチップス"
                    }

                    # --- 🌟 ここから「ゆるふわ判定」ロジック 🌟 ---
                    detected = []
                    # 文章の中に英単語が含まれているかチェック
                    for eng, jpn in translate_hints.items():
                        if eng in caption: # 完璧一致じゃなくてもOK
                            if jpn in available_foods:
                                detected.append(jpn)

                    # 🌟 親子丼・カツ丼の「推理」を追加
                    # AIが「bowl of rice（丼）」と言っていて、かつ「egg」と「chicken」があれば親子丼！
                    if "rice" in caption and "egg" in caption:
                        if "chicken" in caption or "meat" in caption:
                            detected.append("親子丼")
                        if "pork" in caption or "cutlet" in caption:
                            detected.append("カツ丼")
                    
                    detected = list(set(detected)) # 重複カット
                    # --- 🌟 ここまで 🌟 ---

                    if detected:
                        st.session_state.detected_foods = detected
                        st.session_state.manual_mode = True
                        st.rerun()
                    else:
                        st.warning("⚠️ 具体的な料理名が見つかりませんでした。手動で選択してください。")
                        st.session_state.manual_mode = True

    with col_manual:
        if st.button("手動で入力する"):
            st.session_state.manual_mode = True
            st.session_state.detected_foods = []
            st.rerun()

    st.markdown("---")
    if st.session_state.manual_mode:
        if st.session_state.detected_foods:
            selected_foods = st.multiselect("AIが見つけた料理 (修正可)", options=available_foods, default=st.session_state.detected_foods)
        else:
            selected_categories = st.multiselect("カテゴリから絞り込む", options=list(food_categories.keys()))
            filtered = []
            for c in selected_categories: filtered.extend(food_categories.get(c, []))
            selected_foods = st.multiselect("料理名を選択", options=sorted(list(set(filtered))) if filtered else available_foods)

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
# 7. グラフ表示 (既存維持)
# ----------------------------------------------------
if st.session_state.data_added:
    st.markdown("---")
    st.subheader("栄養レポート")
    cols = st.columns(4)
    cols[0].metric("カロリー", f"{st.session_state.total_nutrition_for_day['calories']:.0f}kcal")
    cols[1].metric("たんぱく", f"{st.session_state.total_nutrition_for_day['protein']:.1f}g")
    cols[2].metric("脂質", f"{st.session_state.total_nutrition_for_day['fat']:.1f}g")
    cols[3].metric("炭水化物", f"{st.session_state.total_nutrition_for_day['carbohydrates']:.1f}g")

    if st.button("今日一日をリセット"):
        st.session_state.total_nutrition_for_day = {"calories": 0, "protein": 0, "fat": 0, "carbohydrates": 0}
        st.session_state.data_added = False
        st.rerun()

    # グラフ表示
    st.markdown("---")
    col1, col2 = st.columns(2)
    if col1.button("グラフ切り替え"):
        st.session_state.show_total_chart = not st.session_state.show_total_chart
        st.rerun()
    
    if st.session_state.show_total_chart:
        title = "1日の目標達成度"
        current_data = st.session_state.total_nutrition_for_day
        target_data = daily_needs
    else:
        title = f"{st.session_state.last_selected_meal_type}の目標達成度"
        current_data = st.session_state.last_added_nutrition
        ratio = meal_ratios.get(st.session_state.last_selected_meal_type, 0.25)
        target_data = {k: v * ratio for k, v in daily_needs.items()}

    # レーダーチャート作成
    categories = ["カロリー", "たんぱく質", "脂質", "炭水化物"]
    values = [min((current_data[k] / target_data[k]) * 100, 120) if target_data[k]>0 else 0 for k in ["calories", "protein", "fat", "carbohydrates"]]
    
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=[100]*4, theta=categories, fill='toself', name='目標', fillcolor='rgba(255, 192, 203, 0.3)', line_color='rgba(200,200,200,0.5)'))
    fig.add_trace(go.Scatterpolar(r=values, theta=categories, fill='toself', name='摂取', fillcolor='rgba(135, 206, 250, 0.7)', line_color='skyblue'))
    
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 120])),
        paper_bgcolor='#accc54', plot_bgcolor='#accc54',
        title=title, margin=dict(l=40, r=40, t=40, b=40)
    )
    st.plotly_chart(fig, width='stretch')
    
# --- 💡 AI管理栄養士のひとことメッセージ ---
    st.markdown("---")
    
    # 栄養バランスをチェックして、メッセージを自動生成
    total = st.session_state.total_nutrition_for_day
    
    # メッセージの出し分け（優先順位をつけて判定）
    if total['calories'] == 0:
        advice_msg = "今日の食事を記録してね！健康管理の第一歩だよ✨"
        icon = "🥗"
    elif total['calories'] > daily_needs['calories']:
        advice_msg = "今日は少しエネルギー多めかも。明日はお野菜たっぷりのメニューにしてみるのはどうかな？"
        icon = "⚠️"
    elif total['protein'] < (daily_needs['protein'] * 0.5):
        advice_msg = "タンパク質が少し足りないみたい。卵やお肉、お豆腐をプラスするともっと良くなるよ！"
        icon = "🥚"
    elif total['carbohydrates'] > (daily_needs['carbohydrates'] * 0.8):
        advice_msg = "炭水化物がしっかり摂れてるね！午後の集中力もバッチリ保てそう。"
        icon = "🌾"
    else:
        advice_msg = "素晴らしいバランス！その調子で健康な体づくりを続けていこうね✨"
        icon = "👏"

    # 👇 ここを st.success から st.markdown に書き換えます！
    st.markdown(f"""
    <div class="advice-card">
        <div class="advice-title">{icon} ちょこっとアドバイス</div>
        <div class="advice-text">{advice_msg}</div>
    </div>
    """, unsafe_allow_html=True)
    
    # 保存ボタンはその下に配置
    if st.session_state.auth_ready:
        # ボタンも「ぷくっと」させるためにそのまま配置
        st.button("この記録を保存", on_click=save_nutrition_data, args=(st.session_state.last_selected_meal_type, st.session_state.last_added_nutrition))