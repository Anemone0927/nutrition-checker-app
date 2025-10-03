import warnings
import streamlit as st
import pandas as pd
import random
import plotly.graph_objects as go
from PIL import Image

# ----------------------------------------------------
# 1. Firebase Admin SDK のインポートと初期化
# ----------------------------------------------------
# Firebase Admin SDK のインポート
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    import json
except ImportError:
    # firebase-adminがインストールされていない場合の処理（ローカル実行で未インストール時）
    firebase_admin = None
    credentials = None
    firestore = None
    json = None

# Firebase関連のセッションステートを初期化
if 'db' not in st.session_state:
    st.session_state.db = None
    st.session_state.auth_ready = False
    st.session_state.user_id = "default_user" # 認証前の仮ID
if 'history' not in st.session_state:
    st.session_state['history'] = {} # データベースから読み込まれた過去の記録用

def initialize_firebase():
    """
    Firebase Admin SDKを初期化する。
    Streamlit Cloud のシークレットまたはローカルの JSON ファイルから認証情報を取得。
    """
    if st.session_state.db is not None:
        # すでに初期化済みなら何もしない
        return

    if firebase_admin is None:
        st.session_state.auth_ready = False
        return

    # Streamlit Cloud のシークレットから認証情報を取得 (デプロイ環境向け)
    try:
        if st.secrets.get("firebase", {}):
            creds_dict = dict(st.secrets["firebase"])
            cred = credentials.Certificate(creds_dict)
            
            if not firebase_admin.apps:
                firebase_admin.initialize_app(cred)
            
            st.session_state.db = firestore.client()
            st.session_state.auth_ready = True
            # Streamlit SecretsからユーザーIDを取得
            st.session_state.user_id = st.secrets.get("app", {}).get("user_id", "streamlit_cloud_user") 
            st.success("Firebaseに接続しました。")
            return

    except Exception:
        # シークレットの読み込みに失敗した場合、ローカル向けの代替パスに進む
        pass

        
    # ローカル開発環境向けのフォールバック（認証情報をJSONファイルとして保存している場合）
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
        st.warning(f"Firebaseの初期化に失敗しました。データベース保存機能は無効です。 ({e})")
    
    # どちらも失敗した場合
    st.session_state.db = None
    st.session_state.auth_ready = False

# ----------------------------------------------------
# 2. データ保存・読み込み機能の定義
# ----------------------------------------------------
def save_nutrition_data(meal_type, nutrition_data):
    """
    現在の食事の栄養データをFirestoreに保存する。
    """
    if not st.session_state.auth_ready or st.session_state.db is None:
        st.error("データベース接続が未完了のため保存できません。")
        return

    try:
        # コレクションパスを定義: users/{userId}/records/{meal_type}
        doc_ref = st.session_state.db.collection('users').document(st.session_state.user_id).collection('records').document(meal_type)
        
        # ユーザーのコードに合わせたキー名で保存
        data_to_save = {
            'meal_type': meal_type,
            'calories': nutrition_data.get('calories', 0),
            'protein': nutrition_data.get('protein', 0),
            'fat': nutrition_data.get('fat', 0),
            'carbohydrates': nutrition_data.get('carbohydrates', 0),
            'timestamp': firestore.SERVER_TIMESTAMP # サーバー側で保存時刻を記録
        }
        
        doc_ref.set(data_to_save)
        st.session_state.history[meal_type] = nutrition_data # 履歴も更新
        st.success(f"✅ {meal_type}の栄養データをクラウドに保存しました！")
        st.session_state.data_added = True # 保存後、グラフを再表示するため
        # Streamlitの再実行をトリガー
        st.rerun() 

    except Exception as e:
        st.error(f"データ保存中にエラーが発生しました: {e}")

def load_nutrition_data():
    """
    Firestoreから過去の栄養データを読み込む。
    """
    if not st.session_state.auth_ready or st.session_state.db is None:
        return {} # データベースが使えない場合は空の辞書を返す

    loaded_data = {}
    try:
        # ユーザーの全記録を取得
        collection_ref = st.session_state.db.collection('users').document(st.session_state.user_id).collection('records')
        docs = collection_ref.stream()

        for doc in docs:
            data = doc.to_dict()
            meal_type = doc.id 
            # ユーザーのsession_stateのキー名に合わせて変換
            loaded_data[meal_type] = {
                'calories': data.get('calories', 0),
                'protein': data.get('protein', 0),
                'fat': data.get('fat', 0),
                'carbohydrates': data.get('carbohydrates', 0)
            }
        return loaded_data

    except Exception as e:
        # 最初の読み込み失敗は警告に留める
        # st.error(f"データ読み込み中にエラーが発生しました: {e}")
        return {}

# Firebaseの初期化を実行
initialize_firebase()


# DeprecationWarningを無視
warnings.filterwarnings('ignore', category=DeprecationWarning)

# Initialize session state for persistent data
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
    nutrition_dict = df.set_index('food').T.to_dict()
except FileNotFoundError:
    st.error("エラー: 'food_nutrition.csv' ファイルが見つかりません。")
    st.stop()

# Define food categories
food_categories = {
    "朝食": ["クロワッサン", "プレーンヨーグルト", "イチゴ", "ラズベリー", "トースト", "ジャム", "牛乳", "シリアル", "ゆで卵", "パンケーキ", "フレンチトースト", "メロンパン", "あんぱん", "食パン", "バゲット", "クロワワッサンサンド"],
    "昼食・夕食": ["ごはん", "鶏肉", "ほうれん草", "卵", "納豆", "味噌汁", "鮭", "豆腐", "パスタ", "ステーキ", "ハンバーグ", "カレーライス", "ラーメン", "餃子", "炒飯", "サンドイッチ", "ツナサンド", "ハムチーズサンド", "ミックスサンド", "カツ丼", "親子丼", "牛丼", "天ぷら", "ざるそば", "うどん", "焼き魚", "煮物", "ほうれん草のおひたし", "豚の角煮", "麻婆豆腐", "エビチリ", "青椒肉絲", "回鍋肉", "春巻き", "小籠包", "焼きそば", "お好み焼き", "たこ焼き", "茶碗蒸し", "冷奴", "味噌カツ", "手羽先の唐揚げ", "鶏肉の照り焼き", "肉じゃが", "魚の煮付け"],
    "お店の弁当・惣菜": ["フライドポテト", "ハンバーガー", "カニクリームコロッケ", "鶏の唐揚げ", "豚の生姜焼き"],
    "野菜・フルーツ": ["トマト", "ブロッコリー", "人参", "きゅうり", "玉ねぎ", "じゃがいも", "ピーマン", "海藻サラダ", "サラダ", "バナナ", "リンゴ", "アボカド"],
    "飲み物": ["コーヒー", "オレンジジュース", "コーンスープ", "酸辣湯"],
    "その他": ["オリーブ", "メープルシロップ", "サラダチキン", "プロテインバー", "アーモンド", "ピーナッツ", "くるみ", "カシューナッツ", "ポテトサラダ", "シーザーサラダ", "豆腐サラダ", "チキンサラダ"]
    "おやつ": ["チョコレート", "クッキー", "ビスケット", "和菓子（大福、団子、羊羹など）", "ドーナツ", "アイスクリーム", "ジェラート", "カステラ", "パウンドケーキ", "チーズ", "クラッカー", "エナジーバー", "グラノーラバー", "ゼリー", "ドライフルーツ","ポップコーン", "グミ", "ポテトチップス", "スナック", "飴"]
}

# Daily recommended intake (simplified)
daily_needs = {
    "calories": 2000,
    "protein": 60,
    "fat": 50,
    "carbohydrates": 300
}

# Target ratios for each meal (%)
meal_ratios = {
    "朝食": 0.25,
    "昼食": 0.35,
    "夕食": 0.30,
    "おやつ": 0.10,
}

# Mapping of nutrients to food categories
recommendation_categories = {
    "calories": ["パン", "ご飯", "麺", "シリアル"],
    "protein": ["肉", "魚", "卵", "豆類"],
    "fat": ["ナッツ", "アボカド", "油"],
    "carbohydrates": ["フルーツ", "全粒穀物", "イモ類"]
}

# Mapping of food to its category
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
    "アーモンド": "ナッツ", "ピーナッツ": "ナッツ", "くるみ": "ナッツ", "カシューナッツ": "ナッツ",
    "アボカド": "アボカド",
    "オリーブ": "油", "ごま油": "油",
    "ブロッコリー": "野菜", "ほうれん草": "野菜", "トマト": "野菜", "きゅうり": "野菜", "玉ねぎ": "野菜", "人参": "野菜", "ピーマン": "野菜","チョコレート": "デザート","クッキー": "デザート","ビスケット": "デザート","和菓子（大福、団子、羊羹など）": "デザート","ドーナツ": "デザート","アイスクリーム": "デザート","ジェラート": "デザート","カステラ": "デザート","パウンドケーキ": "デザート","ゼリー": "デザート","グミ": "デザート","飴": "デザート","チーズ": "その他（乳製品）","クラッカー": "スナック（穀物）","エナジーバー": "スナック（栄養）","グラノーラバー": "スナック（栄養）","ドライフルーツ": "フルーツ","ポップコーン": "スナック（穀物）","ポテトチップス": "スナック（イモ）","スナック": "スナック（その他）","ナッツ": "ナッツ",
}

# Set page configuration
st.set_page_config(
    page_title="栄養チェッカー",
    layout="centered"
)
st.title("食事画像から栄養をチェック！")

# Custom CSS for a cute design
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

# File uploader
uploaded_file = st.file_uploader("画像をアップロード", type=["jpg", "jpeg", "png"])

# ----------------------------------------------------
# 3. UIへのデータ保存ボタンの統合
# ----------------------------------------------------
st.markdown(f"**現在のユーザーID:** `{st.session_state.user_id}`")

if st.session_state.auth_ready and st.session_state.last_selected_meal_type and st.session_state.data_added:
    # 接続済みで、一度でも計算が実行されたらボタンを表示
    save_button_key = f"save_btn_{st.session_state.last_selected_meal_type}_{st.session_state.total_nutrition_for_day['calories']}"
    
    # on_clickで保存関数を呼び出し、引数に食事タイプと直近の栄養情報を渡す
    st.button(
        f"{st.session_state.last_selected_meal_type}の記録を保存", 
        key=save_button_key, 
        on_click=save_nutrition_data, 
        args=(st.session_state.last_selected_meal_type, st.session_state.last_added_nutrition), 
        type='secondary'
    )
elif not st.session_state.auth_ready:
    # 接続情報がない場合の警告
    st.warning("データベース接続待ち、または未設定のため、データ保存はできません。")

st.write("---") # 区切り線


if uploaded_file is not None:
    st.image(uploaded_file, caption='アップロードされた画像', use_container_width=True)
    st.success("画像を受け取りました！")
    
    # Selection logic
    st.subheader("画像に写っている料理を選んでください")
    
    # Meal type selection
    selected_meal_type = st.selectbox(
        "どの食事ですか？",
        options=list(meal_ratios.keys()),
        # 最後に選択した食事タイプを維持
	index=list(meal_ratios.keys()).index(st.session_state.last_selected_meal_type) if st.session_state.last_selected_meal_type else 0
    )
    
    selected_categories = st.multiselect(
        "料理のカテゴリを選択",
        options=list(food_categories.keys())
    )
    
    filtered_foods = []
    if selected_categories:
        for category in selected_categories:
            filtered_foods.extend(food_categories.get(category, []))
    else:
        for category_list in food_categories.values():
            filtered_foods.extend(category_list)
    
    filtered_foods = sorted(list(set(filtered_foods)))
    
    selected_foods = st.multiselect(
        "料理名を選択（検索もできます）",
        options=filtered_foods,
        default=[]
    )

    # Action button to add nutrition
    if st.button("栄養情報を計算", type='primary'):
        if not selected_foods:
            st.warning("料理が選択されていません。")
        else:
            # Calculate nutrition for the selected foods
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
                        nutrition_for_current_meal[key] += nutrition[key]
            
            # Add to the total nutrition for the day
            for key in st.session_state.total_nutrition_for_day:
                st.session_state.total_nutrition_for_day[key] += nutrition_for_current_meal[key]

            # Store nutrition for the last meal to display in the chart
            st.session_state.last_added_nutrition = nutrition_for_current_meal
            st.session_state.last_selected_meal_type = selected_meal_type
            st.session_state.data_added = True
            
            st.info("選択された料理：" + "、".join(selected_foods) + " の栄養情報を計算しました！")

    # Display results only if data has been added
    if st.session_state.data_added:
        # Display the daily total and the reset button
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
            st.success("今日の合計栄養をリセットしました。")

        # Display the advice and chart based on the selected mode
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        with col1:
            # Toggle button for chart display mode
            if st.button("グラフを切り替え"):
                st.session_state.show_total_chart = not st.session_state.show_total_chart
        with col2:
            # Reset button for the chart view
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
                ],
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
            fig.update_layout(
                polar=dict(
                    radialaxis=dict(
                        visible=True,
                        range=[0, 120]
                    ),
                    angularaxis=dict(
                        rotation=90,
                        direction="clockwise"
                    ),
                )
            )
            st.session_state.chart_reset = False

# ----------------------------------------------------
# 4. サイドバーに過去の記録を表示
# ----------------------------------------------------
if st.session_state['history']:
    st.sidebar.markdown("---")
    st.sidebar.subheader("過去の保存データ")
    
    # 過去の記録をサイドバーに表示
    for meal, data in st.session_state['history'].items():
        st.sidebar.markdown(f"**{meal}**")
        st.sidebar.text(f"  カロリー: {data['calories']:.0f} kcal")
        st.sidebar.text(f"  たんぱく質: {data['protein']:.1f} g")
    st.sidebar.caption("これらのデータはデータベースから読み込まれています。")

