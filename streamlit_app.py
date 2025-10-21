import warnings
import streamlit as st
import pandas as pd
import random
import plotly.graph_objects as go
from PIL import Image

# ----------------------------------------------------
# 1. Firebase Admin SDK のインポートと初期化
# ----------------------------------------------------
# Firebase Admin SDK, JSON, Requests, Base64 のインポート
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    import json
    import requests
    import base64
except ImportError as e:
    # 必要なライブラリがない場合の処理
    firebase_admin = None
    credentials = None
    firestore = None
    json = None
    requests = None
    base64 = None
    st.error(f"🔴 必要なライブラリが見つかりません: {e}. 'firebase-admin', 'requests', 'pandas'などが必要です。")


# ----------------------------------------------------
# 2. Gemini API の設定
# ----------------------------------------------------
API_URL_BASE = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent"
# 修正: Streamlit SecretsからAPIキーを取得
API_KEY = st.secrets.get("gemini_api_key", "") # Canvas環境では実行時に自動で提供されます

def file_to_base64(uploaded_file):
    """UploadedFileオブジェクトをBase64文字列に変換する"""
    if base64 is None: return None
    return base64.b64encode(uploaded_file.getvalue()).decode('utf-8')

def analyze_image_with_gemini(base64_image_data, mime_type):
    """Gemini APIを呼び出し、画像から食品名をJSON形式で検出する"""
    if requests is None or json is None:
        st.error("API呼び出しに必要なライブラリがロードされていません。")
        return None
    
    # 修正: APIキーのチェックを追加
    if not API_KEY:
        st.error("🔴 APIキーが設定されていません。`st.secrets`または環境変数を確認してください。")
        return None
    
    # 応答JSONのスキーマ定義
    response_schema = {
        "type": "OBJECT",
        "properties": {
            "foods": {
                "type": "ARRAY",
                "description": "画像から検出された可能性のある食品のリスト。食品データベースにある名前に最も近くなるようにしてください。",
                "items": {"type": "STRING"}
            }
        },
        "required": ["foods"]
    }

    # システムプロンプトを設定し、食品データベースにある名前（例： 'ごはん', '鶏肉'）で回答を促す
    system_prompt = "あなたは食品分析の専門家です。画像に写っている食べ物をすべて特定し、食品データベースにある名前に最も近い日本語の一般名称でリストアップしてください。食品名（例： 'ごはん', '鶏肉', 'ブロッコリー'）は、できるだけ短く、データベースにマッチしやすい形式で答えてください。"
    user_query = "この画像に写っている食べ物、メインディッシュ、サイドディッシュ、フルーツなどをすべてリストアップしてください。"

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": user_query},
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": base64_image_data
                        }
                    }
                ]
            }
        ],
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": response_schema
        }
    }
    
    # 指数バックオフを使用したAPI呼び出し
    for attempt in range(5):
        try:
            response = requests.post(
                f"{API_URL_BASE}?key={API_KEY}",
                headers={'Content-Type': 'application/json'},
                data=json.dumps(payload)
            )
            response.raise_for_status()
            
            result = response.json()
            
            if result.get('candidates'):
                json_string = result['candidates'][0]['content']['parts'][0]['text']
                return json.loads(json_string)
            return None
        except requests.exceptions.RequestException as e:
            print(f"API呼び出しエラー (試行 {attempt + 1}/5): {e}") # コンソールにエラーログを出力
            if attempt < 4:
                import time
                time.sleep(2 ** attempt)  
            else:
                st.error("🔴 画像分析APIの呼び出しが最大試行回数に達しました。")
                return None
        except json.JSONDecodeError:
            st.error("🔴 画像分析APIから無効なJSON応答が返されました。")
            return None


# ----------------------------------------------------
# 3. StreamlitのセッションステートとFirebase初期化
# ----------------------------------------------------

# Firebase関連のセッションステートを初期化
if 'db' not in st.session_state:
    st.session_state.db = None
    st.session_state.auth_ready = False
    st.session_state.user_id = "default_user" # 認証前の仮ID
if 'history' not in st.session_state:
    st.session_state['history'] = {} # データベースから読み込まれた過去の記録用

# 画像分析関連のセッションステートを初期化
if 'detected_foods' not in st.session_state:
    st.session_state.detected_foods = []
if 'manual_mode' not in st.session_state:
    st.session_state.manual_mode = False

def initialize_firebase():
    """
    Firebase Admin SDKを初期化する。
    """
    if st.session_state.db is not None:
        return

    if firebase_admin is None:
        st.session_state.auth_ready = False
        st.warning("🔴 firebase-adminライブラリが見つかりません。データベース保存機能は無効です。")
        return

    # Streamlit Cloud のシークレットから認証情報を取得 (デプロイ環境向け)
    try:
        if st.secrets.get("firebase", {}):
            creds_dict = dict(st.secrets["firebase"])
            # エスケープされた改行コード（\n）を実際の改行コードに強制的に変換
            if 'private_key' in creds_dict and isinstance(creds_dict['private_key'], str):
                creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
            
            cred = credentials.Certificate(creds_dict)
            
            if not firebase_admin.apps:
                firebase_admin.initialize_app(cred)
            
            st.session_state.db = firestore.client()
            st.session_state.auth_ready = True
            st.session_state.user_id = st.secrets.get("app", {}).get("user_id", "streamlit_cloud_user") 
            st.success("✅ Firebaseに接続しました！")
            return

    except Exception as e:
        st.error(f"🔴 Firebase Secretsの読み込みと初期化に失敗しました。認証情報（Secrets）を確認してください。エラー: {e}")
        st.session_state.auth_ready = False 
        pass

        
    # ローカル開発環境向けのフォールバック
    try:
        import os
        if os.path.exists("serviceAccountKey.json"):
            if not firebase_admin.apps:
                cred = credentials.Certificate("serviceAccountKey.json") 
                firebase_admin.initialize_app(cred)
                
            st.session_state.db = firestore.client()
            st.session_state.auth_ready = True
            st.session_state.user_id = "local_developer_user" 
            st.info("ローカルファイルからFirebaseに接続しました。（デプロイ時はSecretsが必要です）")
            return
    
    except Exception as e:
        if st.session_state.auth_ready == False: 
             st.warning(f"Firebaseの初期化に失敗しました。データベース保存機能は無効です。 ({e})")
        
    st.session_state.db = None
    st.session_state.auth_ready = False

# データ保存・読み込み機能の定義
def save_nutrition_data(meal_type, nutrition_data):
    """Firestoreに栄養データを保存する"""
    if not st.session_state.auth_ready:
        st.error("データベースが初期化されていません。データを保存できません。")
        return

    try:
        # ドキュメント参照パスを決定 (ここではユーザーIDごとのプライベートコレクションを使用)
        # collection path: /users/{userId}/nutrition_logs
        # Canvasのガイドラインに基づき、コレクションパスは /artifacts/{appId}/users/{userId}/{your_collection_name} とすべきですが、
        # Streamlitでは__app_idが使えないため、既存のユーザーIDベースのパスを使用します。
        doc_ref = st.session_state.db.collection(f"users/{st.session_state.user_id}/nutrition_logs").document()
        
        data_to_save = {
            "meal_type": meal_type,
            "calories": nutrition_data["calories"],
            "protein": nutrition_data["protein"],
            "fat": nutrition_data["fat"],
            "carbohydrates": nutrition_data["carbohydrates"],
            "timestamp": firestore.SERVER_TIMESTAMP # 保存時刻をFirestore側で設定
        }
        
        doc_ref.set(data_to_save)
        st.success(f"✅ {meal_type}の記録をデータベースに保存しました！")
        
        # 保存後、履歴を再読み込み（リアルタイム反映のため）
        st.session_state.history = load_nutrition_data()

    except Exception as e:
        st.error(f"データの保存中にエラーが発生しました: {e}")

def load_nutrition_data():
    """Firestoreから過去の栄養データを読み込む"""
    if not st.session_state.auth_ready:
        return {}
    
    try:
        # ユーザーIDごとのコレクションからデータを取得
        # collection path: /users/{userId}/nutrition_logs
        collection_ref = st.session_state.db.collection(f"users/{st.session_state.user_id}/nutrition_logs")
        
        # 最新の10件を取得するクエリ (ソートは簡易化のためコード側で行う)
        docs = collection_ref.stream()
        
        # データを meal_type ごとに集計して、最新の記録を保持（簡易履歴）
        history_data = {}
        for doc in docs:
            data = doc.to_dict()
            meal_type = data.get("meal_type", "不明な食事")
            
            # タイムスタンプで最新かどうかを判断（ここでは簡易的に）
            if meal_type not in history_data or data.get("timestamp", 0) > history_data[meal_type].get("timestamp", 0):
                 history_data[meal_type] = {
                     "calories": data.get("calories", 0),
                     "protein": data.get("protein", 0),
                     "fat": data.get("fat", 0),
                     "carbohydrates": data.get("carbohydrates", 0),
                     "timestamp": data.get("timestamp", None)
                 }
        
        return history_data
    except Exception as e:
        st.error(f"データの読み込み中にエラーが発生しました: {e}")
        return {}


# ----------------------------------------------------
# 4. データ読み込み、定数設定、UI
# ----------------------------------------------------

# Firebaseの初期化を実行
initialize_firebase()


# DeprecationWarningを無視
warnings.filterwarnings('ignore', category=DeprecationWarning)

# Initialize session state for persistent data (既存のロジックを維持)
if 'total_nutrition_for_day' not in st.session_state:
    st.session_state.total_nutrition_for_day = {
        "calories": 0,
        "protein": 0,
        "fat": 0,
        "carbohydrates": 0
    }
if 'last_added_nutrition' not in st.session_state:
    st.session_state.last_added_nutrition = {
        "calories": 0,
        "protein": 0,
        "fat": 0,
        "carbohydrates": 0
    }
if 'last_selected_meal_type' not in st.session_state:
    st.session_state.last_selected_meal_type = ""
if 'show_total_chart' not in st.session_state:
    st.session_state.show_total_chart = True
if 'data_added' not in st.session_state:
    st.session_state.data_added = False
if 'chart_reset' not in st.session_state:
    st.session_state.chart_reset = False


# データベースから過去の履歴を読み込み（Firebase初期化後に実行）
if st.session_state.auth_ready and not st.session_state.history:
    st.session_state.history = load_nutrition_data()


# Load nutrition data from CSV
try:
    df = pd.read_csv("food_nutrition.csv")
    
    # 🌟 修正点: 'food' 列で重複がある行を削除し、最後の行のデータを採用
    df_cleaned = df.drop_duplicates(subset=['food'], keep='last')
    
    nutrition_dict = df_cleaned.set_index('food').T.to_dict()
    available_foods = list(nutrition_dict.keys())
except FileNotFoundError:
    # 🌟 修正: CSVファイルがない場合にクラッシュするのを防ぐため、ダミーデータを設定
    st.error("エラー: 'food_nutrition.csv' ファイルが見つかりません。デモデータを使用してアプリを続行します。")
    nutrition_dict = {
        "ごはん": {"calories": 168, "protein": 2.5, "fat": 0.3, "carbohydrates": 37.1},
        "鶏肉": {"calories": 145, "protein": 23.0, "fat": 3.5, "carbohydrates": 0.0},
        "ブロッコリー": {"calories": 33, "protein": 4.3, "fat": 0.3, "carbohydrates": 5.2},
        "ゆで卵": {"calories": 76, "protein": 6.3, "fat": 5.3, "carbohydrates": 0.2},
        "リンゴ": {"calories": 54, "protein": 0.2, "fat": 0.1, "carbohydrates": 14.1},
    }
    available_foods = list(nutrition_dict.keys())
    # st.stop() を削除し、アプリを続行させる


# Define food categories (既存のロジックを維持)
food_categories = {
    "朝食": ["クロワッサン", "プレーンヨーグルト", "イチゴ", "ラズベリー", "トースト", "ジャム", "牛乳", "シリアル", "ゆで卵", "パンケーキ", "フレンチトースト", "メロンパン", "あんぱん", "食パン", "バゲット", "クロワワッサンサンド"],
    "昼食・夕食": ["ごはん", "鶏肉", "ほうれん草", "卵", "納豆", "味噌汁", "鮭", "豆腐", "パスタ", "ステーキ", "ハンバーグ", "カレーライス", "ラーメン", "餃子", "炒飯", "サンドイッチ", "ツナサンド", "ハムチーズサンド", "ミックスサンド", "カツ丼", "親子丼", "牛丼", "天ぷら", "ざるそば", "うどん", "焼き魚", "煮物", "ほうれん草のおひたし", "豚の角煮", "麻婆豆腐", "エビチリ", "青椒肉絲", "回鍋肉", "春巻き", "小籠包", "焼きそば", "お好み焼き", "たこ焼き", "茶碗蒸し", "冷奴", "味噌カツ", "手羽先の唐揚げ", "鶏肉の照り焼き", "肉じゃが", "魚の煮付け"],
    "お店の弁当・惣菜": ["フライドポテト", "ハンバーガー", "カニクリームコロッケ", "鶏の唐揚げ", "豚の生姜焼き"],
    "野菜・フルーツ": ["トマト", "ブロッコリー", "人参", "きゅうり", "玉ねぎ", "じゃがいも", "ピーマン", "海藻サラダ", "サラダ", "バナナ", "リンゴ", "アボカド"],
    "飲み物": ["コーヒー", "オレンジジュース", "コーンスープ", "酸辣湯"],
    "その他": ["オリーブ", "メープルシロップ", "サラダチキン", "プロテインバー", "アーモンド", "ピーナッツ", "くるみ", "カシューナッツ", "ポテトサラダ", "シーザーサラダ", "豆腐サラダ", "チキンサラダ"],
    "おやつ": ["チョコレート", "クッキー", "ビスケット", "和菓子（大福、団子、羊羹など）", "ドーナツ", "アイスクリーム", "ジェラート", "カステラ", "パウンドケーキ", "チーズ", "クラッカー", "エナジーバー", "グラノーラバー", "ゼリー", "ドライフルーツ","ポップコーン", "グミ", "ポテトチップス", "スナック", "飴"],
}

# Daily recommended intake (simplified) (既存のロジックを維持)
daily_needs = {
    "calories": 2000,
    "protein": 60,
    "fat": 50,
    "carbohydrates": 300
}

# Target ratios for each meal (%) (既存のロジックを維持)
meal_ratios = {
    "朝食": 0.25,
    "昼食": 0.35,
    "夕食": 0.30,
    "おやつ": 0.10,
}

# Mapping of nutrients to food categories (既存のロジックを維持)
recommendation_categories = {
    "calories": ["パン", "ご飯", "麺", "シリアル"],
    "protein": ["肉", "魚", "卵", "豆類"],
    "fat": ["ナッツ", "アボカド", "油"],
    "carbohydrates": ["フルーツ", "全粒穀物", "イモ類"]
}

# Mapping of food to its category (既存のロジックを維持)
food_to_category = {
    "クロワッサン": "パン", "トースト": "パン", "食パン": "パン", "メロンパン": "パン", "あんぱん": "パン", "バゲット": "パン",
    "ごはん": "ご飯", "おにぎり": "ご飯", "カレーライス": "ご飯", "炒飯": "ご飯", "牛丼": "ご飯", "親子丼": "ご飯", "カツ丼": "ご飯",
    "パスタ": "麺", "ラーメン": "麺", "うどん": "麺", "焼きそば": "麺", "ざるそば": "麺",
    "シリアル": "シリアル",
    "鶏肉": "肉", "豚ロース": "肉", "牛もも肉": "肉", "ハンバーグ": "肉", "豚の角煮": "肉", "鶏むね肉": "肉", "手羽先の唐揚げ": "肉", "鶏肉の照り焼き": "肉", "豚の生姜焼き": "肉", "サンドイッチ": "肉", "ツナサンド": "肉", "ハムチーズサンド": "肉", "ミックスサンド": "肉", "サラダチキン": "肉",
    "鮭": "魚", "アジの開き": "魚", "サバの味噌煮": "魚", "焼き魚": "魚", "魚の煮付け": "魚", "エビフライ": "魚", "エビチリ": "魚",
    "卵": "卵", "ゆで卵": "卵", "オムライス": "卵", "茶碗蒸し": "卵",
    "納豆": "豆類", "豆腐": "豆類", "冷奴": "豆類", "麻婆豆腐": "豆類", "きなこ": "豆類",
    "イチゴ": "フルーツ", "ラズベリー": "フルーツ", "バナナ": "フルーツ", "リンゴ": "フルーツ", "メロン": "フルーツ",
    "ジャガイモ": "イモ類", "フライドポテト": "イモ類", "ポテトサラダ": "イモ類",
    "アーモンド": "ナッツ", "ピーナッツ": "ナッツ", "くるみ": "ナッツ", "カシューナッツ": "ナッツ","ナッツ": "ナッツ",
    "アボカド": "アボカド",
    "オリーブ": "油", "ごま油": "油",
    "ブロッコリー": "野菜", "ほうれん草": "野菜", "トマト": "野菜", "きゅうり": "野菜", "玉ねぎ": "野菜", "人参": "野菜", "ピーマン": "野菜","チョコレート": "デザート","クッキー": "デザート","ビスケット": "デザート","和菓子（大福、団子、羊羹など）": "デザート","ドーナツ": "デザート","アイスクリーム": "デザート","ジェラート": "デザート","カステラ": "デザート","パウンドケーキ": "デザート","ゼリー": "デザート","グミ": "デザート","飴": "デザート","チーズ": "その他（乳製品）","クラッカー": "スナック（穀物）","エナジーバー": "スナック（栄養）","グラノーラバー": "スナック（栄養）","ドライフルーツ": "フルーツ","ポップコーン": "スナック（穀物）","ポテトチップス": "スナック（イモ）","スナック": "スナック（その他）",
}


# Set page configuration
st.set_page_config(
    page_title="栄養チェッカー",
    layout="centered"
)
st.title("食事画像から栄養をチェック！")

# Custom CSS for a cute design (既存のロジックを維持)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=M+PLUS+Rounded+1c&display=swap');
    
    html, body, .stApp {
        font-family: 'M PLUS Rounded 1c', sans-serif;
        color: #E7889A; /* 文字色を可愛い桃色に変更 */
    }

    /* Gradient background for the main container */
    .stApp {
        background: linear-gradient(135deg, #E0F7E0, #F5E8C7) !important;
        background-attachment: fixed !important;
    }

    /* Text color for headings */
    h1, h2, h3, h4, h5, h6 {
        color: #E7889A;
    }
    
    /* Button styles */
    div[data-testid="stButton"] button {
        background-color: #876358 !important;
        color: #FFF !important;
        border-radius: 12px !important;
        border: none !important;
        padding: 10px 20px !important;
        font-weight: bold !important;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.2) !important;
    }
    
    div[data-testid="stButton"] button:hover {
        background-color: #876358 !important;
    }
    
    /* Primary Button styles for Auto Analysis */
    /* 自動分析ボタンに目立つ色を適用 */
    div[data-testid="stButton"] button[kind="primary"] {
        background-color: #E7889A !important;
        color: white !important;
    }
    
    /* Multiselect and text input styles */
    .stMultiSelect, .stSelectbox {
        background-color: #e3bd96;
        border-radius: 12px;
    }


    /* Info and success boxes */
    .stAlert {
        border-radius: 12px;
        color: #E7889A; /* Alert内の文字色も桃色に */
    }
    
    /* For the text inside the st.info and st.success boxes */
    .stAlert p {
        color: #E7889A !important;
    }

</style>
""", unsafe_allow_html=True)

# File uploader and Camera Input
st.subheader("撮影またはアップロード")

# Streamlitのカメラ機能
# カメラが利用可能な環境（主にスマホやPCのWebカメラ）で、このウィジェットが表示される
camera_photo = st.camera_input("📸 カメラで食事を撮影") 

st.markdown("---") # 区切り線

# ファイルアップロード機能 (予備として残しておく)
uploaded_file = st.file_uploader("📂 または、画像をアップロード", type=["jpg", "jpeg", "png"])

# 撮影された画像またはアップロードされたファイルのどちらかを使用する
if camera_photo is not None:
    # カメラで撮影した画像を優先
    final_input_file = camera_photo
else:
    # カメラで撮っていなければ、アップロードされた画像を使う
    final_input_file = uploaded_file

# ----------------------------------------------------
# 5. UIへのデータ保存ボタンの統合
# ----------------------------------------------------
st.markdown(f"**現在のユーザーID:** `{st.session_state.user_id}`")

if st.session_state.auth_ready and st.session_state.last_selected_meal_type and st.session_state.data_added:
    save_button_key = f"save_btn_{st.session_state.last_selected_meal_type}_{st.session_state.total_nutrition_for_day['calories']}"
    
    st.button(
        f"{st.session_state.last_selected_meal_type}の記録を保存", 
        key=save_button_key, 
        on_click=save_nutrition_data, 
        args=(st.session_state.last_selected_meal_type, st.session_state.last_added_nutrition), 
        type='secondary'
    )
elif not st.session_state.auth_ready and st.session_state.db is None:
      st.warning("⚠️ データベース接続待ち、または未設定のため、データ保存はできません。")

st.write("---") # 区切り線


if final_input_file is not None: # ★★★ ここはOK ★★★
    st.image(final_input_file, caption='分析対象の画像', use_container_width=True)    
    
    # Meal type selection (食事タイプは分析の前に行う)
    st.subheader("食事タイプを選択してください")
    selected_meal_type = st.selectbox(
        "どの食事ですか？",
        options=list(meal_ratios.keys()),
        index=list(meal_ratios.keys()).index(st.session_state.last_selected_meal_type) if st.session_state.last_selected_meal_type in meal_ratios else 0
    )
    
    
    # ----------------------------------------------------
    # 6. 自動分析 (Gemini Vision) と 手動入力の切り替え
    # ----------------------------------------------------
    
    st.subheader("料理の選択方法")
    
    # 自動分析ボタンと手動入力切り替えボタンの配置
    col_auto, col_manual = st.columns([1, 1])

    with col_auto:
        # 自動分析ボタン
        if st.button("画像から自動分析 (AI)", key="auto_analyze_btn", type='primary'):
            # 修正: APIキーがない場合は処理を中断
            if not API_KEY:
                st.error("🔴 APIキーが見つからないため、自動分析を実行できません。")
                st.session_state.manual_mode = True # 手動入力に切り替える
                st.rerun()
                
            st.session_state.manual_mode = False
            st.session_state.detected_foods = [] # リセット
            
            # 画像をBase64に変換
            base64_data = file_to_base64(final_input_file)
            mime_type = final_input_file.type
            
            if base64_data:
                with st.spinner("AIが画像から料理を分析中..."):
                    # Gemini APIを呼び出し
                    api_result = analyze_image_with_gemini(base64_data, mime_type)
                
                if api_result and 'foods' in api_result:
                    # 検出された食品名を取得
                    detected_foods = api_result['foods']
                    
                    # データベースに存在する食品名のみを抽出
                    matching_foods = [food for food in detected_foods if food in nutrition_dict]
                    non_matching_foods = [food for food in detected_foods if food not in nutrition_dict]
                    
                    st.session_state.detected_foods = matching_foods
                    st.session_state.manual_mode = True # 自動分析結果を手動選択で表示するために一時的にTrueに

                    if matching_foods:
                        st.success(f"✅ 料理を自動検出しました: {', '.join(matching_foods)}")
                        if non_matching_foods:
                            st.warning(f"⚠️ データベースにない食品は無視されました: {', '.join(non_matching_foods)}")
                    else:
                        st.warning("⚠️ 画像から食品を検出できませんでした。手動で選択してください。")
                        st.session_state.detected_foods = []
                        st.session_state.manual_mode = True 
                else:
                    st.error("AIによる画像分析に失敗しました。手動で選択してください。")
                    st.session_state.detected_foods = []
                    st.session_state.manual_mode = True
            st.rerun()

    with col_manual:
        # 手動入力モードに切り替えるボタン
        if st.button("手動で入力", key="manual_mode_btn", type='secondary'):
            st.session_state.manual_mode = True
            st.session_state.detected_foods = [] # 自動検出結果をクリア
            st.rerun()

    # ----------------------------------------------------
    # 7. 自動分析結果 または 手動選択フォームの表示
    # ----------------------------------------------------
    
    selected_foods = []
    
    # 自動検出が成功した場合、その結果を初期値としてマルチセレクトに表示
    if st.session_state.detected_foods:
        st.info("自動検出された食品をリストに反映しました。間違いがあれば修正してください。")
        selected_foods = st.multiselect(
            "料理名を選択（自動検出結果）",
            options=available_foods,
            default=st.session_state.detected_foods # 検出結果を初期値に設定
        )
        st.session_state.manual_mode = True # 自動検出後もユーザーが編集できるように手動モードを維持

    # 手動モードの場合、カテゴリフィルタリング機能を提供
    elif st.session_state.manual_mode:
        st.info("手動モードです。カテゴリを選択して料理を選んでください。")
        
        selected_categories = st.multiselect(
            "料理のカテゴリを選択",
            options=list(food_categories.keys())
        )
        
        filtered_foods = []
        if selected_categories:
            for category in selected_categories:
                # 辞書に存在しないカテゴリが選択された場合でもエラーにならないようにgetを使用
                filtered_foods.extend(food_categories.get(category, []))
        else:
            # カテゴリ未選択時は全食品から選択可能
            filtered_foods = available_foods
        
        filtered_foods = sorted(list(set(filtered_foods)))
        
        selected_foods = st.multiselect(
            "料理名を選択（検索もできます）",
            options=filtered_foods,
            default=[]
        )
    else:
        # 初期状態または自動分析前
        st.info("⬆️ 上のボタンから「自動分析」または「手動で入力」を選択してください。")


    # Action button to calculate nutrition
    if st.session_state.manual_mode and st.button("栄養情報を計算", key='calculate_btn', type='secondary'):
        if not selected_foods:
            st.warning("料理が選択されていません。")
        else:
            # Calculate nutrition for the selected foods (計算ロジックは既存を維持)
            nutrition_for_current_meal = {
                "calories": 0,
                "protein": 0,
                "fat": 0,
                "carbohydrates": 0
            }
            
            for food in selected_foods:
                if food in nutrition_dict:
                    nutrition = nutrition_dict[food]
                    for key in nutrition_for_current_meal:
                        nutrition_for_current_meal[key] += nutrition.get(key, 0) # 念のためgetでアクセス
            
            # Add to the total nutrition for the day
            for key in st.session_state.total_nutrition_for_day:
                st.session_state.total_nutrition_for_day[key] += nutrition_for_current_meal[key]

            # Store nutrition for the last meal to display in the chart
            st.session_state.last_added_nutrition = nutrition_for_current_meal
            st.session_state.last_selected_meal_type = selected_meal_type
            st.session_state.data_added = True
            
            st.info("選択された料理：" + "、".join(selected_foods) + " の栄養情報を計算しました！")

    # Display results only if data has been added (既存のロジックを維持)
    if st.session_state.data_added:
        st.markdown("---")
        st.subheader("今日の栄養合計")
        st.write(f"カロリー: {st.session_state.total_nutrition_for_day['calories']:.1f} kcal")
        st.write(f"たんぱく質: {st.session_state.total_nutrition_for_day['protein']:.1f} g")
        st.write(f"脂質: {st.session_state.total_nutrition_for_day['fat']:.1f} g")
        st.write(f"炭水化物: {st.session_state.total_nutrition_for_day['carbohydrates']:.1f} g")

        # Reset button for the day's total
        if st.button("合計をリセット"):
            st.session_state.total_nutrition_for_day = {
                "calories": 0,
                "protein": 0,
                "fat": 0,
                "carbohydrates": 0
            }
            st.session_state.last_added_nutrition = {
                "calories": 0,
                "protein": 0,
                "fat": 0,
                "carbohydrates": 0
            }
            st.session_state.data_added = False
            st.session_state.detected_foods = [] # 自動検出結果もリセット
            st.session_state.manual_mode = False # モードもリセット
            st.success("今日の合計栄養をリセットしました。")
            st.rerun() 

        # Display the advice and chart based on the selected mode
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("グラフを切り替え"):
                st.session_state.show_total_chart = not st.session_state.show_total_chart
                st.rerun() 
        with col2:
            if st.button("グラフをリセット"):
                st.session_state.chart_reset = True

        if st.session_state.show_total_chart:
            # Displaying total daily nutrition chart
            st.subheader("今日の総合的な栄養バランス")
            
            advice_messages = []
            for key in daily_needs:
                if st.session_state.total_nutrition_for_day[key] < daily_needs[key] * 0.5:
                    if key == "calories":
                        advice_messages.append("**カロリー**が不足しています。活動に必要なエネルギー源なので、パンやご飯などを少し追加すると良いでしょう。")
                    elif key == "protein":
                        advice_messages.append("**たんぱく質**が不足しています。筋肉や体の組織を作る大切な栄養素です。卵や鶏むね肉、豆類などを意識して摂りましょう。")
                    elif key == "fat":
                        advice_messages.append("**脂質**が不足しています。ホルモンや細胞膜を作るのに重要です。アボカドやナッツ類、良質な油を摂ることをおすすめします。")
                    elif key == "carbohydrates":
                        advice_messages.append("**炭水化物**が不足しています。脳の唯一のエネルギー源です。フルーツや全粒穀物などを追加してバランスを整えましょう。")

            if advice_messages:
                for msg in advice_messages:
                    st.warning(msg)
            else:
                if st.session_state.total_nutrition_for_day["calories"] > 0:
                    st.success("素晴らしいです！栄養バランスがとても良く摂れています！")
                else:
                    st.info("まだ今日の食事データがありません。")
            
            st.markdown("<br>", unsafe_allow_html=True)

            # Normalize data for the chart
            nutrition_data = {
                "栄養素": ["カロリー", "たんぱく質", "脂質", "炭水化物"],
                "摂取量 (%)": [
                    min((st.session_state.total_nutrition_for_day["calories"] / daily_needs["calories"]) * 100, 100),
                    min((st.session_state.total_nutrition_for_day["protein"] / daily_needs["protein"]) * 100, 100),
                    min((st.session_state.total_nutrition_for_day["fat"] / daily_needs["fat"]) * 100, 100),
                    min((st.session_state.total_nutrition_for_day["carbohydrates"] / daily_needs["carbohydrates"]) * 100, 100)
                ],
                "理想値": [100, 100, 100, 100]
            }
            
            chart_title = "1日の推奨摂取量に対するバランス"
            chart_name = "今日の合計"
            
        else:
            # Displaying last meal's nutrition chart
            st.subheader(f"直近の食事 ({st.session_state.last_selected_meal_type}) の栄養バランス")

            meal_needs = {key: value * meal_ratios.get(st.session_state.last_selected_meal_type, 0.25) for key, value in daily_needs.items()}
            
            advice_messages = []
            for key in meal_needs:
                if st.session_state.last_added_nutrition[key] < meal_needs[key] * 0.5:
                    recommended_categories = recommendation_categories.get(key, [])
                    if key == "calories":
                        advice_messages.append(f"今回の食事の**カロリー**は少なめです。この食事タイプに必要なエネルギー源を意識しましょう。")
                    elif key == "protein":
                        advice_messages.append(f"今回の食事の**たんぱく質**が少し不足しています。卵や鶏むね肉などを追加すると良いでしょう。")
                    elif key == "fat":
                        advice_messages.append(f"今回の食事の**脂質**が少し不足しています。ナッツ類やアボカドなどを加えると良いでしょう。")
                    elif key == "carbohydrates":
                        advice_messages.append(f"今回の食事の**炭水化物**が少し不足しています。フルーツやパンなどを加えると良いでしょう。")

            if advice_messages:
                for msg in advice_messages:
                    st.info(msg)
            else:
                if st.session_state.last_added_nutrition["calories"] > 0:
                    st.success(f"直近の食事 ({st.session_state.last_selected_meal_type}) の栄養バランスは完璧です！")
                else:
                    st.info("まだ食事データがありません。")

            st.markdown("<br>", unsafe_allow_html=True)

            # Normalize data for the chart
            nutrition_data = {
                "栄養素": ["カロリー", "たんぱく質", "脂質", "炭水化物"],
                "摂取量 (%)": [
                    min((st.session_state.last_added_nutrition["calories"] / meal_needs["calories"]) * 100, 100),
                    min((st.session_state.last_added_nutrition["protein"] / meal_needs["protein"]) * 100, 100),
                    min((st.session_state.last_added_nutrition["fat"] / meal_needs["fat"]) * 100, 100),
                    min((st.session_state.last_added_nutrition["carbohydrates"] / meal_needs["carbohydrates"]) * 100, 100)
                ]
                ,
                "理想値": [100, 100, 100, 100]
            }
            
            chart_title = f"{st.session_state.last_selected_meal_type}の推奨摂取量に対するバランス"
            chart_name = "今回の食事"

        # Create the radar chart
        df_chart = pd.DataFrame(nutrition_data)
        fig = go.Figure()

        # Ideal values (background)
        fig.add_trace(go.Scatterpolar(
            r=df_chart['理想値'],
            theta=df_chart['栄養素'],
            fill='toself',
            fillcolor='rgba(255, 192, 203, 0.5)', # 淡いピンク色に変更
            line_color='rgba(200, 200, 200, 1)',
            name='目標値'
        ))

        # Today's intake or current meal's intake
        fig.add_trace(go.Scatterpolar(
            r=df_chart['摂取量 (%)'],
            theta=df_chart['栄養素'],
            fill='toself',
            fillcolor='rgba(135, 206, 250, 0.7)', # スカイブルーに変更
            line_color='rgba(135, 206, 250, 1)', # スカイブルーに変更
            name=chart_name,
            hovertemplate='<b>%{theta}</b><br>摂取量: %{r:.1f}%<extra></extra>',
        ))

        # Chart layout configuration
        fig.update_layout(
            title={
                'text': chart_title,
                'y': 0.99,
                'x':0.45,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, 120]
                ),
                angularaxis=dict(
                    rotation=90,
                    direction="clockwise"
                ),
            ),
            showlegend=True,
            margin=dict(l=50, r=50, t=50, b=50),
            paper_bgcolor='#accc54', # グラフ全体の背景色を指定された色に変更
            plot_bgcolor='#accc54', # グラフ描画エリアの背景色も同様に変更
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        if st.session_state.chart_reset:
            st.session_state.chart_reset = False
            st.rerun()

# ----------------------------------------------------
# 8. サイドバーに過去の記録を表示
# ----------------------------------------------------

if st.session_state['history']:
    st.sidebar.markdown("---")
    st.sidebar.subheader("過去の保存データ")
    
    for meal, data in st.session_state['history'].items():
        st.sidebar.markdown(f"**{meal}**")
        st.sidebar.text(f"  カロリー: {data['calories']:.0f} kcal")
        st.sidebar.text(f"  たんぱく質: {data['protein']:.1f} g")
    st.sidebar.caption("これらのデータはデータベースから読み込まれています。")