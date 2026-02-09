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

# --- Gemini API 最新版 (google-genai) 用 ---
try:
    from google import genai
    from google.genai import types
except ImportError:
    st.error("🔴 ライブラリ 'google-genai' が見つかりません。 'pip install google-genai' を実行してください。")

# ----------------------------------------------------
# 1. Firebase Admin SDK のインポートと初期化
# ----------------------------------------------------
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    from streamlit import cache_resource, cache_data
except ImportError as e:
    firebase_admin = None
    st.error(f"🔴 必要なライブラリが見つかりません: {e}")

# ----------------------------------------------------
# 2. Gemini API の設定 (最新版 SDK 対応)
# ----------------------------------------------------
def analyze_image_with_gemini(uploaded_file, available_foods):
    """最新の google-genai SDK を使用して画像を解析"""
    try:
        api_key = st.secrets.get("GEMINI_API_KEY")
        if not api_key:
            st.error("🔑 Gemini APIキーが設定されていません。Secretsを確認してください。")
            return None

        client = genai.Client(api_key=api_key)
        image_bytes = uploaded_file.getvalue()
        
        prompt = f"""
        この画像に写っている食べ物を特定してください。
        以下のリストにある名前のみを使って、カンマ区切りで回答してください。
        リストにないものは無視してください。
        
        リスト: {", ".join(available_foods)}
        """

        # 最新の生成メソッド (Gemini 2.0 Flash)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                prompt,
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
            ]
        )
        
        if response.text:
            detected = [food.strip() for food in response.text.split(",") if food.strip() in available_foods]
            return {"detected": detected}
        return None

    except Exception as e:
        st.error(f"❌ Gemini解析エラー: {e}")
        return None

# ----------------------------------------------------
# 3. StreamlitのセッションステートとFirebase初期化
# ----------------------------------------------------
if 'db' not in st.session_state:
    st.session_state.db = None
    st.session_state.auth_ready = False
    st.session_state.user_id = "default_user"
if 'history' not in st.session_state:
    st.session_state['history'] = {}
if 'detected_foods' not in st.session_state:
    st.session_state.detected_foods = []
if 'manual_mode' not in st.session_state:
    st.session_state.manual_mode = False

@cache_resource
def initialize_firebase():
    try:
        import os
        json_string = st.secrets.get("firebase_credentials_json", "")
        if json_string:
            creds_dict = json.loads(json_string)
            if 'private_key' in creds_dict:
                creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
            cred = credentials.Certificate(creds_dict)
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred)
            db = firestore.client()
            return db, True, "cloud_user"
        elif os.path.exists("serviceAccountKey.json"):
            if not firebase_admin._apps:
                cred = credentials.Certificate("serviceAccountKey.json")
                firebase_admin.initialize_app(cred)
            db = firestore.client()
            return db, True, "local_user"
    except Exception as e:
        st.warning(f"Firebase初期化スキップ: {e}")
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
            if meal_type not in history_data or data.get("timestamp", 0) > history_data[meal_type].get("timestamp", 0):
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
# 4. データ読み込み、定数設定、UI
# ----------------------------------------------------
db_client, auth_status, user_id = initialize_firebase()
st.session_state.db = db_client
st.session_state.auth_ready = auth_status
st.session_state.user_id = user_id
warnings.filterwarnings('ignore', category=DeprecationWarning)

if 'total_nutrition_for_day' not in st.session_state:
    st.session_state.total_nutrition_for_day = {"calories": 0, "protein": 0, "fat": 0, "carbohydrates": 0}
if 'last_added_nutrition' not in st.session_state:
    st.session_state.last_added_nutrition = {"calories": 0, "protein": 0, "fat": 0, "carbohydrates": 0}
if 'last_selected_meal_type' not in st.session_state:
    st.session_state.last_selected_meal_type = ""
if 'show_total_chart' not in st.session_state:
    st.session_state.show_total_chart = True
if 'data_added' not in st.session_state:
    st.session_state.data_added = False

@cache_data
def load_nutrition_data_from_csv():
    try:
        df = pd.read_csv("food_nutrition.csv")
        nutrition_dict = df.drop_duplicates(subset=['food'], keep='last').set_index('food').T.to_dict()
        return nutrition_dict, list(nutrition_dict.keys())
    except:
        nutrition_dict = {"ごはん": {"calories": 168, "protein": 2.5, "fat": 0.3, "carbohydrates": 37.1}, "鶏肉": {"calories": 145, "protein": 23.0, "fat": 3.5, "carbohydrates": 0.0}, "ブロッコリー": {"calories": 33, "protein": 4.3, "fat": 0.3, "carbohydrates": 5.2}, "ゆで卵": {"calories": 76, "protein": 6.3, "fat": 5.3, "carbohydrates": 0.2}, "リンゴ": {"calories": 54, "protein": 0.2, "fat": 0.1, "carbohydrates": 14.1}}
        return nutrition_dict, list(nutrition_dict.keys())

nutrition_dict, available_foods = load_nutrition_data_from_csv()

food_categories = {
    "朝食": ["クロワッサン", "プレーンヨーグルト", "イチゴ", "ラズベリー", "トースト", "ジャム", "牛乳", "シリアル", "ゆで卵", "パンケーキ", "フレンチトースト", "メロンパン", "あんぱん", "食パン", "バゲット"],
    "昼食・夕食": ["ごはん", "鶏肉", "ほうれん草", "卵", "納豆", "味噌汁", "鮭", "豆腐", "パスタ", "ステーキ", "ハンバーグ", "カレーライス", "ラーメン", "餃子", "炒飯", "サンドイッチ", "ツナサンド", "カツ丼", "親子丼", "牛丼", "天ぷら", "ざるそば", "うどん", "焼き魚", "煮物", "豚の角煮", "麻婆豆腐", "エビチリ", "青椒肉絲", "回鍋肉", "春巻き", "小籠包", "焼きそば", "お好み焼き", "たこ焼き", "茶碗蒸し", "冷奴", "肉じゃが", "魚の煮付け"],
    "お店の弁当・惣菜": ["フライドポテト", "ハンバーガー", "カニクリームコロッケ", "鶏の唐揚げ", "豚の生姜焼き"],
    "野菜・フルーツ": ["トマト", "ブロッコリー", "人参", "きゅうり", "玉ねぎ", "じゃがいも", "ピーマン", "海藻サラダ", "サラダ", "バナナ", "リンゴ", "アボカド"],
    "飲み物": ["コーヒー", "オレンジジュース", "コーンスープ", "酸辣湯"],
    "おやつ": ["チョコレート", "クッキー", "ビスケット", "和菓子", "ドーナツ", "アイスクリーム", "カステラ", "チーズ", "ドライフルーツ", "ポップコーン", "ポテトチップス", "スナック", "飴"],
}

daily_needs = {"calories": 2000, "protein": 60, "fat": 50, "carbohydrates": 300}
meal_ratios = {"朝食": 0.25, "昼食": 0.35, "夕食": 0.30, "おやつ": 0.10}

st.set_page_config(page_title="栄養チェッカー", layout="centered")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=M+PLUS+Rounded+1c&display=swap');
    html, body, .stApp { font-family: 'M PLUS Rounded 1c', sans-serif; color: #E7889A; }
    .stApp { background: linear-gradient(135deg, #E0F7E0, #F5E8C7) !important; background-attachment: fixed !important; }
    h1, h2, h3, h4 { color: #E7889A; }
    
    /* ボタン */
    div[data-testid="stButton"] button { background-color: #876358 !important; color: #FFF !important; border-radius: 12px !important; font-weight: bold !important; }
    div[data-testid="stButton"] button[kind="primary"] { background-color: #E7889A !important; }
    
    /* 🌟 単語チップ（タグ）の色を変更 */
    span[data-baseweb="tag"] {
        background-color: #60cc60 !important; 
        color: white !important;
    }
    span[data-baseweb="tag"] svg {
        fill: white !important;
    }

    /* 入力ボックス（箱）の背景 */
    div[data-baseweb="select"] > div {
        background-color: #d1e9d1 !important;
        border: 1px solid #60cc60 !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("食事画像から栄養をチェック！")

st.subheader("撮影またはアップロード")
camera_photo = st.camera_input("📸 カメラで食事を撮影") 
uploaded_file = st.file_uploader("📂 または、画像をアップロード", type=["jpg", "jpeg", "png"])
final_input_file = camera_photo if camera_photo is not None else uploaded_file

st.markdown(f"**現在のユーザーID:** `{st.session_state.user_id}`")
if st.session_state.auth_ready and st.session_state.last_selected_meal_type and st.session_state.data_added:
    st.button(f"{st.session_state.last_selected_meal_type}の記録を保存", on_click=save_nutrition_data, args=(st.session_state.last_selected_meal_type, st.session_state.last_added_nutrition))

if final_input_file is not None:
    st.image(final_input_file, caption='分析対象の画像', width=400) 
    selected_meal_type = st.selectbox("どの食事ですか？", options=list(meal_ratios.keys()), index=0)
    
    st.subheader("料理の選択方法")
    
    if st.button("画像から自動分析 (AI)", type='primary'):
        st.session_state.data_added = False
        with st.spinner("Geminiが解析中..."):
            res = analyze_image_with_gemini(final_input_file, available_foods)
            if res and res["detected"]:
                st.session_state.detected_foods = res["detected"]
                st.session_state.manual_mode = True 
                #st.success(f"🤖 {len(res['detected'])}個の料理を特定しました！")
            else:
                st.warning("⚠️ リストに一致する料理が見つかりませんでした。手動で選択してください。")
                st.session_state.detected_foods = []
                st.session_state.manual_mode = True

    st.markdown("---")

if st.session_state.manual_mode:
        selected_foods = st.multiselect(
            "料理名を確認・選択（AI判定済）", 
            options=available_foods, 
            default=st.session_state.detected_foods
        )
        
        if st.button("栄養情報を計算して追加", type='secondary'):
            if selected_foods:
                nutrition_for_current_meal = {"calories": 0, "protein": 0, "fat": 0, "carbohydrates": 0}
                for food in selected_foods:
                    if food in nutrition_dict:
                        for key in nutrition_for_current_meal: 
                            nutrition_for_current_meal[key] += nutrition_dict[food].get(key, 0)
                
                for key in st.session_state.total_nutrition_for_day:
                    st.session_state.total_nutrition_for_day[key] += nutrition_for_current_meal[key]
                
                st.session_state.last_added_nutrition = nutrition_for_current_meal
                st.session_state.last_selected_meal_type = selected_meal_type
                st.session_state.data_added = True
                st.rerun()

        # 🌟 グラフとレポート一式を、この if の中（インデント右側）に移動！
        if st.session_state.data_added:
            st.markdown("---")
            st.subheader("栄養レポート")
            t = st.session_state.total_nutrition_for_day
            cols = st.columns(4)
            cols[0].metric("カロリー", f"{t['calories']:.0f}kcal")
            cols[1].metric("たんぱく", f"{t['protein']:.1f}g")
            cols[2].metric("脂質", f"{t['fat']:.1f}g")
            cols[3].metric("炭水化物", f"{t['carbohydrates']:.1f}g")

            st.markdown("---")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("グラフを切り替え"):
                    st.session_state.show_total_chart = not st.session_state.show_total_chart
                    st.rerun()

            if st.session_state.show_total_chart:
                st.subheader("今日の総合的な栄養バランス")
                current = st.session_state.total_nutrition_for_day
                needs = daily_needs
                chart_title = "1日の推奨摂取量に対するバランス"
            else:
                st.subheader(f"直近の食事 ({st.session_state.last_selected_meal_type}) の栄養バランス")
                current = st.session_state.last_added_nutrition
                ratio = meal_ratios.get(st.session_state.last_selected_meal_type, 0.25)
                needs = {k: v * ratio for k, v in daily_needs.items()}
                chart_title = f"{st.session_state.last_selected_meal_type}の推奨摂取量に対するバランス"

            advices = []
            if current["calories"] < needs["calories"] * 0.5: advices.append("**カロリー**が不足しています。パンやご飯などを追加しましょう。")
            if current["protein"] < needs["protein"] * 0.5: advices.append("**たんぱく質**が不足しています。卵や肉、豆類を意識しましょう。")
            if current["fat"] < needs["fat"] * 0.5: advices.append("**脂質**が不足しています。アボカドやナッツ類がおすすめ。")
            if current["carbohydrates"] < needs["carbohydrates"] * 0.5: advices.append("**炭水化物**が不足しています。フルーツや全粒穀物を。")
            
            for msg in advices: st.warning(msg)
            if not advices and current["calories"] > 0: st.success("素晴らしいバランスです！")

            labels = ["カロリー", "たんぱく質", "脂質", "炭水化物"]
            values = [min((current[k] / needs[k]) * 100, 120) if needs[k]>0 else 0 for k in ["calories", "protein", "fat", "carbohydrates"]]
            
            fig = go.Figure()
            fig.add_trace(go.Scatterpolar(r=[100]*4, theta=labels, fill='toself', name='目標', fillcolor='rgba(255, 192, 203, 0.5)', line_color='rgba(200, 200, 200, 1)'))
            fig.add_trace(go.Scatterpolar(r=values, theta=labels, fill='toself', name='摂取量', fillcolor='rgba(135, 206, 250, 0.7)', line_color='rgba(135, 206, 250, 1)'))
            fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 120])), paper_bgcolor='#accc54', title=chart_title)
            st.plotly_chart(fig, selection_mode="points")

if st.session_state.get('history'):
    st.sidebar.markdown("---")
    st.sidebar.subheader("過去の保存データ")
    for meal, data in st.session_state['history'].items():
        st.sidebar.markdown(f"**{meal}**")
        st.sidebar.text(f"  カロリー: {data['calories']:.0f} kcal")