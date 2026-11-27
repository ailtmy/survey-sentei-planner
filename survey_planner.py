import hmac
import math
from collections import defaultdict, deque
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from pyproj import Transformer

# ---------------------------------------------------------
# ページ設定
# ---------------------------------------------------------
st.set_page_config(
    page_title="土地家屋調査士 基準点測量 選点計画・業務取扱要領チェック",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------
# パスワード認証ゲート（Streamlit Secrets: APP_PASSWORD）
# ---------------------------------------------------------
def check_password() -> bool:
    """Streamlit Secrets に設定されたパスワードでアクセスを制限する"""
    if st.session_state.get("authenticated", False):
        return True

    try:
        correct_password = st.secrets["APP_PASSWORD"]
    except Exception:
        st.error("【設定未完了】Streamlit Cloud の Settings > Secrets に `APP_PASSWORD` を設定してください。")
        st.stop()

    st.markdown("### 🔒 基準点測量 選点計画システム ログイン")
    st.caption("事務所内専用ツールです。パスワードを入力してください。")

    with st.form("login_form"):
        entered_pw = st.text_input("パスワード", type="password", placeholder="パスワードを入力")
        submitted = st.form_submit_button("ログイン", type="primary", use_container_width=True)

    if submitted:
        if hmac.compare_digest(entered_pw, str(correct_password)):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("パスワードが正しくありません。")

    return False


if not check_password():
    st.stop()

# ---------------------------------------------------------
# レスポンシブ＆ラベル重なり・クリック貫通対策 CSS
# ---------------------------------------------------------
st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.0rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1.2rem !important;
        padding-right: 1.2rem !important;
        max-width: 100% !important;
    }
    .stButton > button, .stDownloadButton > button {
        min-height: 42px;
        font-weight: 600;
        border-radius: 6px;
    }
    div[role="radiogroup"] {
        gap: 0.5rem;
        flex-wrap: wrap;
    }
    div[role="radiogroup"] label {
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
        padding: 4px 10px;
        border-radius: 6px;
        min-height: 36px;
        display: flex;
        align-items: center;
    }
    /* ラベル要素のクリックを完全に背面の点へ透過させる */
    .leaflet-marker-icon:has(.pt-label-badge),
    .pt-label-badge {
        pointer-events: none !important;
        user-select: none !important;
    }
    .pt-label-badge {
        display: inline-block;
        white-space: nowrap;
        font-size: 11px;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 4px;
        border: 1.5px solid #ffffff;
        box-shadow: 0 1px 4px rgba(0,0,0,0.45);
    }
    .pt-known { background-color: rgba(21, 101, 192, 0.90); color: #ffffff; }
    .pt-gaiku { background-color: rgba(0, 131, 143, 0.90); color: #ffffff; }
    .pt-new   { background-color: rgba(211, 47, 47, 0.92); color: #ffffff; }
    .pt-junc  { background-color: rgba(230, 81, 0, 0.95); color: #ffffff; }
    .pt-const { background-color: rgba(106, 27, 154, 0.90); color: #ffffff; }
    .pt-selected {
        border: 2px solid #ffeb3b !important;
        box-shadow: 0 0 6px rgba(0,0,0,0.75) !important;
    }

    @media (max-width: 768px) {
        .block-container {
            padding-top: 0.6rem !important;
            padding-left: 0.6rem !important;
            padding-right: 0.6rem !important;
        }
        h1 { font-size: 1.2rem !important; }
        h2, h3 { font-size: 1.05rem !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# 定数・規程マスターデータ（業務取扱要領・マニュアル準拠）
# ---------------------------------------------------------
ZONE_NAMES = {
    1: "第1系 (長崎・鹿児島の一部)",
    2: "第2系 (福岡・佐賀・熊本・大分・宮崎・鹿児島)",
    3: "第3系 (山口・島根・広島)",
    4: "第4系 (香川・愛媛・徳島・高知)",
    5: "第5系 (兵庫・鳥取・岡山)",
    6: "第6系 (奈良・京都・大阪・福井・滋賀・三重・和歌山)",
    7: "第7系 (石川・富山・岐阜・愛知)",
    8: "第8系 (新潟・長野・山梨・静岡)",
    9: "第9系 (東京・福島・栃木・茨城・埼玉・千葉・群馬・神奈川)",
    10: "第10系 (青森・秋田・山形・岩手・宮城)",
    11: "第11系 (北海道 小樽・函館等)",
    12: "第12系 (北海道 札幌・旭川等)",
    13: "第13系 (北海道 北見・帯広・釧路等)",
    14: "第14系 (東京都 小笠原諸島)",
    15: "第15系 (沖縄県 本島周辺)",
    16: "第16系 (沖縄県 先島諸島)",
    17: "第17系 (沖縄県 大東諸島)",
    18: "第18系 (東京都 沖ノ鳥島)",
    19: "第19系 (東京都 南鳥島)",
}

ACCURACY_SPECS = {
    "甲1 (大都市の市街地区域)": {
        "region": "市街地地域",
        "code": "甲1",
        "rmse_cm": 2,
        "tolerance_cm": 6,
        "rtk_single_allowed": False,
        "rtk_check_mm": None,
        "scale": "1/250",
    },
    "甲2 (中都市の市街地区域・奈良市市街地等)": {
        "region": "市街地地域",
        "code": "甲2",
        "rmse_cm": 7,
        "tolerance_cm": 20,
        "rtk_single_allowed": True,
        "rtk_check_mm": 60,
        "scale": "1/250・1/500",
    },
    "甲3 (上記以外の市街地・村落・整形農用地)": {
        "region": "市街地・村落地域",
        "code": "甲3",
        "rmse_cm": 15,
        "tolerance_cm": 45,
        "rtk_single_allowed": True,
        "rtk_check_mm": 100,
        "scale": "1/250・1/500",
    },
    "乙1 (村落・農耕地域)": {
        "region": "村落・農耕地域",
        "code": "乙1",
        "rmse_cm": 25,
        "tolerance_cm": 75,
        "rtk_single_allowed": True,
        "rtk_check_mm": 120,
        "scale": "1/500・1/1000",
    },
    "乙2 (山林・原野及びその周辺区域)": {
        "region": "山林・原野地域",
        "code": "乙2",
        "rmse_cm": 50,
        "tolerance_cm": 150,
        "rtk_single_allowed": True,
        "rtk_check_mm": 160,
        "scale": "1/1000・1/2500",
    },
    "乙3 (山林・原野地域)": {
        "region": "山林・原野地域",
        "code": "乙3",
        "rmse_cm": 100,
        "tolerance_cm": 300,
        "rtk_single_allowed": True,
        "rtk_check_mm": 200,
        "scale": "1/1000・1/2500",
    },
}

POINT_TYPES = [
    "街区三角点 (2級相当)",
    "街区多角点 (3級相当)",
    "街区点補助点 (4級相当)",
    "基本三角点・公共基準点",
    "認定登記基準点",
    "登記基準点・多角点 (新点)",
    "恒久的地物 (引照用)",
]

ROUTE_COLORS = [
    "#ff3d00",  # 朱赤
    "#00897b",  # ティールグリーン
    "#6200ea",  # ディープパープル
    "#d81b60",  # マゼンタ
    "#ef6c00",  # オレンジ
    "#2e7d32",  # フォレストグリーン
    "#0277bd",  # オーシャンブルー
    "#5d4037",  # ブラウン
]


# ---------------------------------------------------------
# 座標変換・測量計算ユーティリティ
# ---------------------------------------------------------
def get_transformers(zone: int):
    epsg_code = f"EPSG:{6668 + zone}"
    to_latlon = Transformer.from_crs(epsg_code, "EPSG:4326", always_xy=False)
    to_xy = Transformer.from_crs("EPSG:4326", epsg_code, always_xy=False)
    return to_latlon, to_xy


def deg_to_dms_str(deg: float) -> str:
    d = int(deg)
    m_float = (deg - d) * 60
    m = int(m_float)
    s = round((m_float - m) * 60)
    if s == 60:
        s = 0
        m += 1
    if m == 60:
        m = 0
        d += 1
    return f"{d}°{m:02d}'{s:02d}\""


def calc_distance_and_azimuth(x1: float, y1: float, x2: float, y2: float):
    dx = x2 - x1
    dy = y2 - y1
    dist = math.hypot(dx, dy)
    az = math.degrees(math.atan2(dy, dx)) % 360.0
    return dist, az


def calc_included_angle(az_back: float, az_fore: float) -> float:
    diff = (az_fore - az_back + 180.0) % 360.0 - 180.0
    return abs(diff)


def compute_label_transforms(df: pd.DataFrame, threshold_m: float = 65.0) -> dict:
    """近接する点同士で文字が重ならないよう、隣接点の反対方向へラベルを自動オフセットする"""
    transforms = {}
    records = df.to_dict("records")
    for i, p in enumerate(records):
        name = str(p["点名"])
        repel_x = 0.0
        repel_y = 0.0
        has_neighbor = False

        for j, q in enumerate(records):
            if i == j:
                continue
            dx = q["X"] - p["X"]
            dy = q["Y"] - p["Y"]
            dist = math.hypot(dx, dy)
            if 0 < dist < threshold_m:
                has_neighbor = True
                weight = (threshold_m - dist) / threshold_m
                repel_x -= (dx / dist) * weight
                repel_y -= (dy / dist) * weight

        if not has_neighbor:
            transforms[name] = "translate(11px, -22px)"
        else:
            if repel_y >= 0 and repel_x >= 0:
                transforms[name] = "translate(11px, -22px)"
            elif repel_y >= 0 and repel_x < 0:
                transforms[name] = "translate(11px, 6px)"
            elif repel_y < 0 and repel_x >= 0:
                transforms[name] = "translate(calc(-100% - 11px), -22px)"
            else:
                transforms[name] = "translate(calc(-100% - 11px), 6px)"
    return transforms


# ---------------------------------------------------------
# 結合多角網（Y字型・H字型・多角網）トポロジー解析ユーティリティ
# ---------------------------------------------------------
def analyze_network_topology(routes_dict: dict, pts_lookup: dict, terrain_type: str):
    """複数路線から構成される多角網を解析する（マニュアル第4条・第16条・第18条、要領第28条準拠）"""
    valid_routes = {rname: pts for rname, pts in routes_dict.items() if len(pts) >= 2}
    if not valid_routes:
        return None

    adj = defaultdict(set)
    unique_edges = {}
    node_route_endpoints = defaultdict(int)
    all_nodes = set()

    for rname, pts in valid_routes.items():
        node_route_endpoints[pts[0]] += 1
        node_route_endpoints[pts[-1]] += 1
        for idx, p in enumerate(pts):
            all_nodes.add(p)
            if idx < len(pts) - 1:
                u, v = pts[idx], pts[idx + 1]
                if u != v:
                    adj[u].add(v)
                    adj[v].add(u)
                    key = tuple(sorted((u, v)))
                    if key not in unique_edges:
                        p1, p2 = pts_lookup[u], pts_lookup[v]
                        dist, _ = calc_distance_and_azimuth(p1["X"], p1["Y"], p2["X"], p2["Y"])
                        unique_edges[key] = dist

    junction_nodes = set()
    for node in all_nodes:
        if pts_lookup[node]["区分"] == "新点":
            if len(adj[node]) >= 3 or node_route_endpoints[node] >= 3:
                junction_nodes.add(node)

    known_nodes = [n for n in all_nodes if pts_lookup[n]["区分"] == "既知点"]
    new_nodes = [n for n in all_nodes if pts_lookup[n]["区分"] == "新点"]

    visited = set()
    components = 0
    for start in all_nodes:
        if start not in visited:
            components += 1
            q = deque([start])
            visited.add(start)
            while q:
                curr = q.popleft()
                for nxt in adj[curr]:
                    if nxt not in visited:
                        visited.add(nxt)
                        q.append(nxt)

    dangling_new_nodes = [n for n in new_nodes if len(adj[n]) <= 1]
    num_cycles = len(unique_edges) - len(all_nodes) + components

    if components > 1:
        net_shape = "未連結網（路線が分断されています）"
    elif len(dangling_new_nodes) > 0:
        net_shape = "未結合路線を含む網（開放端あり）"
    elif len(known_nodes) == 3 and len(junction_nodes) == 1 and num_cycles == 0:
        net_shape = "Y字型結合多角網（定型網・平均次数1次）"
    elif len(known_nodes) == 4 and len(junction_nodes) == 2 and num_cycles == 0:
        net_shape = "H字型結合多角網（定型網・平均次数2次）"
    elif len(known_nodes) >= 3 and len(junction_nodes) >= 1 and num_cycles == 0:
        net_shape = f"樹枝状結合多角網（既知点{len(known_nodes)}点・交点{len(junction_nodes)}点）"
    elif len(known_nodes) >= 3 and num_cycles >= 1:
        net_shape = f"閉合環を含む結合多角網（既知点{len(known_nodes)}点・交点{len(junction_nodes)}点・単位多角形{num_cycles}個）"
    else:
        net_shape = f"結合多角網（既知点{len(known_nodes)}点・交点{len(junction_nodes)}点）"

    junction_angles = []
    for jnode in sorted(junction_nodes):
        pj = pts_lookup[jnode]
        neighbors = sorted(list(adj[jnode]))
        dirs = []
        for nb in neighbors:
            pnb = pts_lookup[nb]
            _, az = calc_distance_and_azimuth(pj["X"], pj["Y"], pnb["X"], pnb["Y"])
            dirs.append((az, nb))
        dirs.sort(key=lambda x: x[0])

        for idx in range(len(dirs)):
            az1, nb1 = dirs[idx]
            az2, nb2 = dirs[(idx + 1) % len(dirs)]
            sector_ang = (az2 - az1) % 360.0
            junction_angles.append(
                {
                    "交点": jnode,
                    "分岐方向1": nb1,
                    "分岐方向2": nb2,
                    "分岐夾角": deg_to_dms_str(sector_ang),
                    "angle_deg": sector_ang,
                }
            )

    check_routes = []
    connected_known_set = set()
    sorted_known = sorted(known_nodes)
    for i in range(len(sorted_known)):
        for j in range(i + 1, len(sorted_known)):
            k_start, k_end = sorted_known[i], sorted_known[j]
            queue = deque([[k_start]])
            seen = {k_start}
            found_path = None
            while queue:
                path = queue.popleft()
                curr = path[-1]
                if curr == k_end:
                    found_path = path
                    break
                for nxt in sorted(adj[curr]):
                    if nxt != k_end and pts_lookup[nxt]["区分"] == "既知点":
                        continue
                    if nxt not in seen:
                        seen.add(nxt)
                        queue.append(path + [nxt])

            if found_path and len(found_path) >= 2:
                connected_known_set.add(k_start)
                connected_known_set.add(k_end)
                total_d = 0.0
                for step in range(len(found_path) - 1):
                    ekey = tuple(sorted((found_path[step], found_path[step + 1])))
                    total_d += unique_edges[ekey]
                n_sides = len(found_path) - 1
                s_km = total_d / 1000.0
                allow_pos_cm = 20.0 + 10.0 * math.sqrt(s_km)
                allow_h_cm = 20.0 + 30.0 * math.sqrt(s_km / max(n_sides, 1))
                check_routes.append(
                    {
                        "点検路線": " → ".join(found_path),
                        "辺数(N)": n_sides,
                        "路線長(m)": round(total_d, 3),
                        "水平位置閉合差許容限度(cm)": round(allow_pos_cm, 1),
                        "標高閉合差許容限度(cm)": round(allow_h_cm, 1),
                    }
                )

    unconnected_known = [k for k in sorted_known if k not in connected_known_set]

    return {
        "net_shape": net_shape,
        "known_nodes": sorted_known,
        "new_nodes": sorted(new_nodes),
        "junction_nodes": sorted(list(junction_nodes)),
        "dangling_new_nodes": sorted(dangling_new_nodes),
        "components": components,
        "num_cycles": num_cycles,
        "unique_edges": unique_edges,
        "total_unique_length_m": sum(unique_edges.values()),
        "junction_angles_df": pd.DataFrame(junction_angles),
        "check_routes_df": pd.DataFrame(check_routes),
        "unconnected_known": unconnected_known,
    }


# ---------------------------------------------------------
# SIMAファイル パーサー & エクスポーター
# ---------------------------------------------------------
def parse_sima(file_bytes: bytes, zone: int) -> pd.DataFrame:
    text = None
    for enc in ("cp932", "utf-8", "shift_jis"):
        try:
            text = file_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("文字コードを判別できませんでした（CP932またはUTF-8が必要です）。")

    to_latlon, _ = get_transformers(zone)
    records = []

    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 5 and parts[0] == "A01":
            pt_no = parts[1]
            pt_name = parts[2] if parts[2] else pt_no
            try:
                x = float(parts[3])
                y = float(parts[4])
                z = float(parts[5]) if len(parts) > 5 and parts[5] != "" else 0.0
            except ValueError:
                continue

            lat, lon = to_latlon.transform(x, y)

            if "街区三角" in pt_name:
                pt_type = "街区三角点 (2級相当)"
            elif "街区多角" in pt_name or "節点" in pt_name:
                pt_type = "街区多角点 (3級相当)"
            elif "補助" in pt_name or "街区" in pt_name:
                pt_type = "街区点補助点 (4級相当)"
            elif "認定" in pt_name:
                pt_type = "認定登記基準点"
            elif "三角" in pt_name or "電子" in pt_name or "公共" in pt_name or "基準" in pt_name:
                pt_type = "基本三角点・公共基準点"
            elif "マンホール" in pt_name or "引照" in pt_name or "恒久" in pt_name:
                pt_type = "恒久的地物 (引照用)"
            else:
                pt_type = "基本三角点・公共基準点"

            kubun = "恒久的地物" if pt_type == "恒久的地物 (引照用)" else "既知点"

            records.append(
                {
                    "使用": True,
                    "点名": pt_name,
                    "種別": pt_type,
                    "区分": kubun,
                    "X": round(x, 3),
                    "Y": round(y, 3),
                    "Z": round(z, 3),
                    "lat": lat,
                    "lon": lon,
                }
            )
    return pd.DataFrame(records)


def export_sima(df: pd.DataFrame) -> bytes:
    lines = [
        "G00,01,選点計画データ(JGD2011),",
        "Z00,座標データ,",
        "A00,",
    ]
    for idx, row in df.iterrows():
        lines.append(
            f"A01,{idx + 1},{row['点名']},{row['X']:.3f},{row['Y']:.3f},{row['Z']:.3f},"
        )
    lines.append("A99,")
    return "\r\n".join(lines).encode("cp932", errors="replace")


def create_sample_data(zone: int) -> pd.DataFrame:
    to_latlon, _ = get_transformers(zone)
    sample_pts = [
        ("街区三角点101", "街区三角点 (2級相当)", "既知点", -145180.000, -18560.000, 65.500),
        ("街区多角点201", "街区多角点 (3級相当)", "既知点", -145210.000, -18360.000, 64.900),
        ("街区多角点202", "街区多角点 (3級相当)", "既知点", -145440.000, -18350.000, 63.800),
        ("街区点補助点301", "街区点補助点 (4級相当)", "既知点", -145460.000, -18570.000, 64.100),
        ("4等三角点_奈良", "基本三角点・公共基準点", "既知点", -145130.000, -18460.000, 68.500),
        ("基準マンホールM1", "恒久的地物 (引照用)", "恒久的地物", -145330.000, -18465.000, 64.200),
    ]
    rows = []
    for name, ptype, kubun, x, y, z in sample_pts:
        lat, lon = to_latlon.transform(x, y)
        rows.append(
            {
                "使用": True,
                "点名": name,
                "種別": ptype,
                "区分": kubun,
                "X": x,
                "Y": y,
                "Z": z,
                "lat": lat,
                "lon": lon,
            }
        )
    return pd.DataFrame(rows)


def clear_all_new_points():
    """新点をすべて削除し、全路線およびdata_editorキャッシュから確実に除去する"""
    df = st.session_state["points_df"]
    st.session_state["points_df"] = df[df["区分"] != "新点"].reset_index(drop=True)
    st.session_state["new_point_counter"] = 1
    remaining_names = set(st.session_state["points_df"]["点名"].astype(str).tolist())
    for rname in list(st.session_state["routes_dict"].keys()):
        st.session_state["routes_dict"][rname] = [
            n for n in st.session_state["routes_dict"][rname] if n in remaining_names
        ]
    st.session_state["last_processed_click"] = None
    st.session_state["last_processed_obj_click"] = None
    st.session_state["editor_version"] += 1


# ---------------------------------------------------------
# セッション状態の初期化
# ---------------------------------------------------------
if "current_zone" not in st.session_state:
    st.session_state["current_zone"] = 6
if "points_df" not in st.session_state:
    st.session_state["points_df"] = create_sample_data(6)
if "new_point_counter" not in st.session_state:
    st.session_state["new_point_counter"] = 1
if "last_processed_click" not in st.session_state:
    st.session_state["last_processed_click"] = None
if "last_processed_obj_click" not in st.session_state:
    st.session_state["last_processed_obj_click"] = None
if "routes_dict" not in st.session_state:
    st.session_state["routes_dict"] = {"路線1": []}
if "active_route_name" not in st.session_state:
    st.session_state["active_route_name"] = "路線1"
if "editor_version" not in st.session_state:
    st.session_state["editor_version"] = 0
if "uploader_version" not in st.session_state:
    st.session_state["uploader_version"] = 0

# ---------------------------------------------------------
# サイドバー：座標系・SIMA読込・作業規程パラメータ設定
# ---------------------------------------------------------
with st.sidebar:
    st.header("1. 座標系・SIMAデータ読込")
    zone = st.selectbox(
        "平面直角座標系 (JGD2011)",
        options=list(ZONE_NAMES.keys()),
        index=5,
        format_func=lambda z: ZONE_NAMES[z],
    )

    # 座標系が変更された場合、既存座標の緯度経度を再計算
    if zone != st.session_state["current_zone"]:
        st.session_state["current_zone"] = zone
        to_latlon_new, _ = get_transformers(zone)
        df_tmp = st.session_state["points_df"].copy()
        for idx, row in df_tmp.iterrows():
            if pd.notna(row["X"]) and pd.notna(row["Y"]):
                lat, lon = to_latlon_new.transform(float(row["X"]), float(row["Y"]))
                df_tmp.at[idx, "lat"] = lat
                df_tmp.at[idx, "lon"] = lon
        st.session_state["points_df"] = df_tmp
        st.session_state["editor_version"] += 1

    # スマホ対応：type=None で全ファイル選択許可＆選択と同時に自動読込
    uploaded_file = st.file_uploader(
        "SIMAファイル (.sim / .txt)",
        type=None,
        key=f"sima_uploader_{st.session_state['uploader_version']}",
    )
    if uploaded_file is not None:
        file_sig = (uploaded_file.name, uploaded_file.size, zone)
        if st.session_state.get("last_uploaded_sig") != file_sig:
            try:
                df_loaded = parse_sima(uploaded_file.getvalue(), zone)
                if df_loaded.empty:
                    st.error("A01座標レコードが見つかりませんでした。")
                else:
                    st.session_state["points_df"] = df_loaded
                    st.session_state["new_point_counter"] = 1
                    st.session_state["routes_dict"] = {"路線1": []}
                    st.session_state["active_route_name"] = "路線1"
                    st.session_state["editor_version"] += 1
                    st.session_state["last_uploaded_sig"] = file_sig
                    st.success(f"{len(df_loaded)}点読み込みました")
                    st.rerun()
            except Exception as e:
                st.error(f"読込エラー: {e}")

    if st.button("サンプル読込", use_container_width=True):
        st.session_state["points_df"] = create_sample_data(zone)
        st.session_state["new_point_counter"] = 1
        st.session_state["routes_dict"] = {"路線1": []}
        st.session_state["active_route_name"] = "路線1"
        st.session_state["editor_version"] += 1
        st.session_state["uploader_version"] += 1
        st.session_state["last_uploaded_sig"] = None
        st.rerun()

    st.divider()
    st.header("2. 地域区分・精度区分 (要領第40条)")
    accuracy_key = st.selectbox(
        "対象地の地域区分・精度区分",
        options=list(ACCURACY_SPECS.keys()),
        index=1,
    )
    acc_spec = ACCURACY_SPECS[accuracy_key]
    st.info(
        f"**精度区分 {acc_spec['code']}**（縮尺 {acc_spec['scale']}）\n"
        f"- 位置誤差公差：**{acc_spec['tolerance_cm']}cm**\n"
        f"- 単点観測法：**{'適用可（制限 ' + str(acc_spec['rtk_check_mm']) + 'mm）' if acc_spec['rtk_single_allowed'] else '適用除外（甲1）'}**"
    )

    st.divider()
    st.header("3. 測量方式・観測機器")
    survey_method = st.selectbox(
        "評価対象の測量方式",
        [
            "結合多角方式（Y字型・H字型・多角網：要領第4条・マニュアル第4条）",
            "単路線方式（結合トラバース：要領第28条・マニュアル第4条）",
            "単位多角方式（閉合トラバース：要領第28条）",
            "開放多角方式（開放トラバース：要領第28条）",
            "ネットワーク型RTK法（単点観測法：登記多角点マニュアル）",
        ],
    )

    obs_instrument = st.radio(
        "使用観測機器（要領第39条・マニュアル第3条）",
        ["TS等（トータルステーション）", "GNSS測量機（スタティック/RTK/VRS）"],
    )

    terrain_type = st.radio(
        "地形区分（点検測量較差：要領第44条）",
        ["平地（較差制限 1/2000・20m以内10mm）", "山地（較差制限 1/1000・20m以内20mm）"],
    )

    show_buffers = st.checkbox("距離基準円を表示（100m恒久的地物・200m単位多角）", value=False)

    st.divider()
    if st.button("🔒 ログアウト", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

# ---------------------------------------------------------
# ヘッダー＆コンパクト設定バー
# ---------------------------------------------------------
st.title("基準点測量 選点計画・業務取扱要領チェック")
st.caption(
    f"座標系: **JGD2011 第{zone}系** ｜ 精度区分: **{acc_spec['code']}** ｜ 方式: **{survey_method.split('（')[0]}** （※左上の「＞」からSIMA読込・方式変更）"
)

to_latlon, to_xy = get_transformers(zone)
active_df = st.session_state["points_df"][st.session_state["points_df"]["使用"] == True].copy()
available_names = active_df["点名"].astype(str).tolist()
valid_names_set = set(available_names)

if not st.session_state["routes_dict"]:
    st.session_state["routes_dict"] = {"路線1": []}
for rname in list(st.session_state["routes_dict"].keys()):
    st.session_state["routes_dict"][rname] = [
        n for n in st.session_state["routes_dict"][rname] if n in valid_names_set
    ]
if st.session_state["active_route_name"] not in st.session_state["routes_dict"]:
    st.session_state["active_route_name"] = list(st.session_state["routes_dict"].keys())[0]

if available_names:
    if (
        "route_candidate_select" not in st.session_state
        or st.session_state["route_candidate_select"] not in available_names
    ):
        st.session_state["route_candidate_select"] = available_names[0]

is_network_mode = "結合多角方式" in survey_method
pts_lookup_all = {str(row["点名"]): row for _, row in active_df.iterrows()}

net_analysis = None
junction_set = set()
if is_network_mode:
    net_analysis = analyze_network_topology(
        st.session_state["routes_dict"], pts_lookup_all, terrain_type
    )
    if net_analysis:
        junction_set = set(net_analysis["junction_nodes"])

# ---------------------------------------------------------
# 1. 地図エリア（サイズ抑えめ・文字クリック透過・重なり回避）
# ---------------------------------------------------------
ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2.6, 1.0, 1.0])
with ctrl_col1:
    map_click_mode = st.radio(
        "地図操作モード",
        [
            "👆 閲覧・点の選択（点クリックで下のリストにセット）",
            "📍 新点を配置する（地図クリックで T1, T2... を追加）",
        ],
        horizontal=True,
        label_visibility="collapsed",
    )
with ctrl_col2:
    show_labels = st.checkbox("🏷 点名ラベル表示", value=True)
with ctrl_col3:
    height_label = st.selectbox(
        "地図高さ",
        ["標準 (420px)", "コンパクト (340px)", "大きめ (540px)"],
        index=0,
        label_visibility="collapsed",
    )
    map_height = 420 if "標準" in height_label else (340 if "コンパクト" in height_label else 540)

if not active_df.empty:
    center_lat = active_df["lat"].mean()
    center_lon = active_df["lon"].mean()
else:
    center_lat, center_lon = 34.6851, 135.8048

m = folium.Map(location=[center_lat, center_lon], zoom_start=17, tiles=None)

folium.TileLayer(
    tiles="https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png",
    attr="<a href='https://maps.gsi.go.jp/development/ichiran.html' target='_blank'>国土地理院</a>",
    name="国土地理院 標準地図",
    overlay=False,
    control=True,
).add_to(m)

folium.TileLayer(
    tiles="https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg",
    attr="<a href='https://maps.gsi.go.jp/development/ichiran.html' target='_blank'>国土地理院</a>",
    name="国土地理院 空中写真 (シームレス)",
    overlay=False,
    control=True,
).add_to(m)

folium.TileLayer(
    tiles="https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png",
    attr="<a href='https://maps.gsi.go.jp/development/ichiran.html' target='_blank'>国土地理院</a>",
    name="国土地理院 淡色地図",
    overlay=False,
    control=True,
).add_to(m)

active_rname = st.session_state["active_route_name"]
current_route_list = st.session_state["routes_dict"][active_rname]

order_map = {}
for idx, rname in enumerate(current_route_list, start=1):
    order_map.setdefault(rname, []).append(str(idx))

selected_candidate_now = st.session_state.get("route_candidate_select", "")
label_transforms = compute_label_transforms(active_df, threshold_m=65.0)

# 1) 路線ポリライン描画
routes_to_draw = (
    st.session_state["routes_dict"]
    if is_network_mode
    else {active_rname: current_route_list}
)

for r_idx, (rname, rpts) in enumerate(routes_to_draw.items()):
    valid_rpts = [n for n in rpts if n in valid_names_set]
    if len(valid_rpts) >= 2:
        route_coords = [
            [pts_lookup_all[n]["lat"], pts_lookup_all[n]["lon"]] for n in valid_rpts
        ]
        line_color = ROUTE_COLORS[r_idx % len(ROUTE_COLORS)]
        is_active_line = rname == active_rname
        folium.PolyLine(
            locations=route_coords,
            color=line_color,
            weight=5.5 if is_active_line else 4.0,
            opacity=0.95 if is_active_line else 0.75,
            interactive=False,
        ).add_to(m)

# 2) 距離基準円（interactive=False）
if show_buffers:
    for _, row in active_df.iterrows():
        if row["区分"] == "新点":
            folium.Circle(
                location=[row["lat"], row["lon"]],
                radius=100,
                color="#800080",
                weight=1.2,
                dash_array="4",
                fill=False,
                interactive=False,
            ).add_to(m)
            folium.Circle(
                location=[row["lat"], row["lon"]],
                radius=200,
                color="#0066cc",
                weight=1.2,
                dash_array="6",
                fill=False,
                interactive=False,
            ).add_to(m)

# 3) クリック対象の測点マーカー（CircleMarker）
for _, row in active_df.iterrows():
    pt_name = str(row["点名"])
    is_junction = pt_name in junction_set

    if is_junction:
        pin_color = "#e65100"
    elif row["区分"] == "新点":
        pin_color = "#d32f2f"
    elif row["区分"] == "恒久的地物":
        pin_color = "#6a1b9a"
    elif "街区" in str(row["種別"]):
        pin_color = "#00838f"
    else:
        pin_color = "#1565c0"

    is_highlighted = pt_name == selected_candidate_now
    border_color = "#ffeb3b" if is_highlighted else "#ffffff"
    marker_radius = 13 if (is_highlighted or is_junction) else 10

    junc_note = "【交点（3路線以上結合）】<br>" if is_junction else ""
    popup_html = (
        f"<b>{pt_name}</b><br>{junc_note}"
        f"種別: {row['種別']}<br>"
        f"X: {row['X']:.3f} m<br>"
        f"Y: {row['Y']:.3f} m<br>"
        f"H: {row['Z']:.3f} m"
    )

    folium.CircleMarker(
        location=[row["lat"], row["lon"]],
        radius=marker_radius,
        color=border_color,
        weight=3.5 if is_highlighted else 2.2,
        fill=True,
        fill_color=pin_color,
        fill_opacity=0.95,
        popup=folium.Popup(popup_html, max_width=250),
        tooltip=pt_name,
    ).add_to(m)

# 4) 点名ラベル描画（interactive=False かつ CSS pointer-events: none）
for _, row in active_df.iterrows():
    pt_name = str(row["点名"])
    is_highlighted = pt_name == selected_candidate_now
    is_junction = pt_name in junction_set
    if not show_labels and not is_highlighted and not is_junction:
        continue

    if is_junction:
        badge_cls = "pt-junc"
    elif row["区分"] == "新点":
        badge_cls = "pt-new"
    elif row["区分"] == "恒久的地物":
        badge_cls = "pt-const"
    elif "街区" in str(row["種別"]):
        badge_cls = "pt-gaiku"
    else:
        badge_cls = "pt-known"

    if is_highlighted:
        badge_cls += " pt-selected"

    junc_prefix = "★交点:" if is_junction else ""
    seq_suffix = f" [順:{','.join(order_map[pt_name])}]" if pt_name in order_map else ""
    label_text = f"{junc_prefix}{pt_name}{seq_suffix}"
    tf_style = label_transforms.get(pt_name, "translate(11px, -22px)")

    folium.Marker(
        location=[row["lat"], row["lon"]],
        interactive=False,
        icon=folium.DivIcon(
            html=f'<div class="pt-label-badge {badge_cls}" style="transform: {tf_style};">{label_text}</div>',
            icon_size=(0, 0),
            icon_anchor=(0, 0),
        ),
    ).add_to(m)

folium.LayerControl(position="topright").add_to(m)

map_output = st_folium(
    m,
    key="survey_map_main",
    width=None,
    height=map_height,
    returned_objects=["last_clicked", "last_object_clicked"],
)

# ---------------------------------------------------------
# 地図クリック時の処理
# ---------------------------------------------------------
if map_output:
    if "点の選択" in map_click_mode and not active_df.empty:
        target_lat, target_lng, max_allow_m = None, None, 0.0

        if map_output.get("last_object_clicked"):
            target_lat = map_output["last_object_clicked"].get("lat")
            target_lng = map_output["last_object_clicked"].get("lng")
            max_allow_m = 5.0
        elif map_output.get("last_clicked"):
            target_lat = map_output["last_clicked"].get("lat")
            target_lng = map_output["last_clicked"].get("lng")
            max_allow_m = 15.0

        if target_lat is not None and target_lng is not None:
            click_x, click_y = to_xy.transform(target_lat, target_lng)
            dists_m = ((active_df["X"] - click_x) ** 2 + (active_df["Y"] - click_y) ** 2) ** 0.5
            min_idx = dists_m.idxmin()

            if dists_m.loc[min_idx] <= max_allow_m:
                matched_name = str(active_df.loc[min_idx, "点名"])
                obj_key = (round(target_lat, 8), round(target_lng, 8), matched_name)
                if obj_key != st.session_state["last_processed_obj_click"]:
                    st.session_state["last_processed_obj_click"] = obj_key
                    st.session_state["route_candidate_select"] = matched_name
                    st.rerun()

    elif "新点を配置" in map_click_mode and map_output.get("last_clicked"):
        clicked = map_output["last_clicked"]
        click_key = (round(clicked["lat"], 8), round(clicked["lng"], 8))
        if click_key != st.session_state["last_processed_click"]:
            st.session_state["last_processed_click"] = click_key
            new_x, new_y = to_xy.transform(clicked["lat"], clicked["lng"])
            new_name = f"T{st.session_state['new_point_counter']}"
            st.session_state["new_point_counter"] += 1

            new_row = pd.DataFrame(
                [
                    {
                        "使用": True,
                        "点名": new_name,
                        "種別": "登記基準点・多角点 (新点)",
                        "区分": "新点",
                        "X": round(new_x, 3),
                        "Y": round(new_y, 3),
                        "Z": 0.000,
                        "lat": clicked["lat"],
                        "lon": clicked["lng"],
                    }
                ]
            )
            st.session_state["points_df"] = pd.concat(
                [st.session_state["points_df"], new_row], ignore_index=True
            )
            st.session_state["route_candidate_select"] = new_name
            st.session_state["editor_version"] += 1
            st.rerun()

# ---------------------------------------------------------
# 2. 路線編成コントロール（Y字型・H字型マルチ路線対応）
# ---------------------------------------------------------
st.markdown("##### 観測路線の編成（リストから測点を選択して「追加」ボタンを押してください）")

if is_network_mode:
    st.caption(
        "【結合多角方式の入力方法】**既知点から交点まで、交点から他の交点までを1路線ずつ**作成します（マニュアル第4条解説2）。"
        " 例）Y字型＝3路線（`既知点1→T1(交点)`、`既知点2→T1`、`既知点3→T1`）／ H字型＝5路線（交点T1・T2へ接続する4路線＋`T1→T2`）"
    )
    nr_col1, nr_col2, nr_col3 = st.columns([2.0, 1.2, 1.2])
    with nr_col1:
        route_keys = list(st.session_state["routes_dict"].keys())
        chosen_route_tab = st.selectbox(
            "編集する路線を選択",
            options=route_keys,
            index=route_keys.index(active_rname),
            format_func=lambda k: f"{k} ({len(st.session_state['routes_dict'][k])}点登録中)",
        )
        if chosen_route_tab != active_rname:
            st.session_state["active_route_name"] = chosen_route_tab
            st.rerun()
    with nr_col2:
        if st.button("➕ 新しい路線を追加", use_container_width=True):
            idx_num = len(st.session_state["routes_dict"]) + 1
            while f"路線{idx_num}" in st.session_state["routes_dict"]:
                idx_num += 1
            new_rname = f"路線{idx_num}"
            st.session_state["routes_dict"][new_rname] = []
            st.session_state["active_route_name"] = new_rname
            st.rerun()
    with nr_col3:
        if st.button(
            "✖ この路線を削除",
            use_container_width=True,
            disabled=len(st.session_state["routes_dict"]) <= 1,
        ):
            del st.session_state["routes_dict"][active_rname]
            st.session_state["active_route_name"] = list(st.session_state["routes_dict"].keys())[0]
            st.rerun()

# 測点追加バー
c1, c2, c3, c4, c5 = st.columns([2.2, 1.1, 0.9, 0.9, 1.0])
with c1:
    chosen_point = st.selectbox(
        "追加する測点を選択",
        options=available_names if available_names else ["(表示中の測点なし)"],
        key="route_candidate_select",
        label_visibility="collapsed",
    )
with c2:
    if st.button("➕ 路線に追加", type="primary", use_container_width=True, disabled=not available_names):
        st.session_state["routes_dict"][active_rname].append(chosen_point)
        st.rerun()
with c3:
    if st.button(
        "↩ 1つ戻す",
        use_container_width=True,
        disabled=len(st.session_state["routes_dict"][active_rname]) == 0,
    ):
        st.session_state["routes_dict"][active_rname].pop()
        st.rerun()
with c4:
    if st.button("🗑 路線クリア", use_container_width=True):
        if is_network_mode:
            st.session_state["routes_dict"] = {"路線1": []}
            st.session_state["active_route_name"] = "路線1"
        else:
            st.session_state["routes_dict"][active_rname] = []
        st.rerun()
with c5:
    has_new_pts = (st.session_state["points_df"]["区分"] == "新点").any()
    if st.button("🗑 新点クリア", use_container_width=True, disabled=not has_new_pts):
        clear_all_new_points()
        st.rerun()

# 現在の路線一覧の視覚表示
pts_lookup_badge = {str(row["点名"]): row["区分"] for _, row in active_df.iterrows()}
if is_network_mode:
    summary_lines = []
    for r_idx, (rname, rpts) in enumerate(st.session_state["routes_dict"].items()):
        marker = "👉 " if rname == active_rname else "  "
        if rpts:
            badges = []
            for p in rpts:
                tag = "交点" if p in junction_set else ("既知" if pts_lookup_badge.get(p) == "既知点" else "新点")
                badges.append(f"**{p}**`({tag})`")
            summary_lines.append(f"{marker}**[{rname}]** " + " ➡ ".join(badges))
        else:
            summary_lines.append(f"{marker}**[{rname}]** *（未登録：上のリストから測点を追加してください）*")
    st.info("\n\n".join(summary_lines))
else:
    rpts = st.session_state["routes_dict"][active_rname]
    if rpts:
        route_badges = []
        for idx, name in enumerate(rpts, start=1):
            k = pts_lookup_badge.get(name, "")
            tag = "既知" if k == "既知点" else ("新点" if k == "新点" else "恒久")
            route_badges.append(f"**{idx}.{name}**`({tag})`")
        st.info("📐 **現在の観測路線順：** " + " ➡ ".join(route_badges))
    else:
        st.caption("※ 上のリストで測点を選択（または地図上の点をクリックしてリストにセット）し、「➕ 路線に追加」を押すと路線が作成されます。")

# ---------------------------------------------------------
# 3. 業務取扱要領・マニュアル 適合性評価結果
# ---------------------------------------------------------
st.divider()
st.subheader("作業規程・業務取扱要領 適合性評価")

# =========================================================
# A. 結合多角方式（Y字型・H字型・多角網）の評価ブロック
# =========================================================
if is_network_mode:
    net_analysis = analyze_network_topology(
        st.session_state["routes_dict"], pts_lookup_all, terrain_type
    )
    if net_analysis and len(net_analysis["unique_edges"]) >= 2:
        ng_list = []
        warn_list = []
        ok_list = []

        known_cnt = len(net_analysis["known_nodes"])
        new_cnt = len(net_analysis["new_nodes"])
        junc_cnt = len(net_analysis["junction_nodes"])
        total_net_len_m = net_analysis["total_unique_length_m"]
        total_net_len_km = total_net_len_m / 1000.0

        if known_cnt < 3:
            ng_list.append(
                f"【要領第4条第7号・マニュアル第4条 NG】結合多角方式は「3点以上の既知点」を使用する必要があります（現在：{known_cnt}点）。2点のみの場合は「単路線方式」を選択してください。"
            )
        else:
            ok_list.append(
                f"既知点 {known_cnt}点（{', '.join(net_analysis['known_nodes'])}）を使用した結合多角網です（方向角の取り付け観測は省略可能：マニュアル第4条解説1）。"
            )

        if net_analysis["components"] > 1:
            ng_list.append(
                f"【マニュアル第4条 NG】多角網が {net_analysis['components']} つのグループに分断されています。交点または既知点を共有させて1つの網に結合してください。"
            )
        if net_analysis["dangling_new_nodes"]:
            ng_list.append(
                f"【要領第4条・第28条 NG】新点「{', '.join(net_analysis['dangling_new_nodes'])}」が開放端（行き止まり）になっています。すべての新点は既知点または他の路線と結合させてください。"
            )
        elif net_analysis["components"] == 1:
            ok_list.append(f"網形判定：**{net_analysis['net_shape']}**（全路線が閉合・結合しています）。")

        if junc_cnt >= 1:
            ok_list.append(
                f"【マニュアル第4条解説2】3路線以上が交わる交点：**{', '.join(net_analysis['junction_nodes'])}**（計{junc_cnt}点）を自動認識しました。"
            )
        elif known_cnt >= 3:
            warn_list.append(
                "【注意】3路線以上が交わる交点が検出されていません。Y字型・H字型にする場合は、同一の新点（交点）を始点または終点として3本以上の路線を接続してください。"
            )

        all_legs_rows = []
        all_inner_angles_rows = []
        for rname, rpts in st.session_state["routes_dict"].items():
            if len(rpts) < 2:
                continue
            end_types = [
                "交点" if rpts[0] in junction_set else pts_lookup_all[rpts[0]]["区分"],
                "交点" if rpts[-1] in junction_set else pts_lookup_all[rpts[-1]]["区分"],
            ]
            if "新点" in end_types:
                warn_list.append(
                    f"【マニュアル第4条解説2 注意】「{rname}」の端点に交点ではない新点が含まれています。結合多角方式の単位路線は「既知点〜交点」「交点〜交点」で構成してください。"
                )

            for i in range(len(rpts) - 1):
                p1, p2 = pts_lookup_all[rpts[i]], pts_lookup_all[rpts[i + 1]]
                dist, az = calc_distance_and_azimuth(p1["X"], p1["Y"], p2["X"], p2["Y"])
                tol_check = dist / 2000.0 if "平地" in terrain_type else dist / 1000.0
                if dist <= 20.0:
                    tol_check = 0.010 if "平地" in terrain_type else 0.020
                all_legs_rows.append(
                    {
                        "路線": rname,
                        "測線": f"{p1['点名']} → {p2['点名']}",
                        "辺長(m)": round(dist, 3),
                        "方向角": deg_to_dms_str(az),
                        "点検測距較差制限(mm)": round(tol_check * 1000, 1),
                    }
                )

            for i in range(1, len(rpts) - 1):
                p_prev, p_curr, p_next = (
                    pts_lookup_all[rpts[i - 1]],
                    pts_lookup_all[rpts[i]],
                    pts_lookup_all[rpts[i + 1]],
                )
                _, az_back = calc_distance_and_azimuth(p_curr["X"], p_curr["Y"], p_prev["X"], p_prev["Y"])
                _, az_fore = calc_distance_and_azimuth(p_curr["X"], p_curr["Y"], p_next["X"], p_next["Y"])
                inc_ang = calc_included_angle(az_back, az_fore)
                all_inner_angles_rows.append(
                    {
                        "路線": rname,
                        "折れ点": p_curr["点名"],
                        "後視": p_prev["点名"],
                        "前視": p_next["点名"],
                        "夾角": deg_to_dms_str(inc_ang),
                        "angle_deg": inc_ang,
                    }
                )
                if inc_ang < 60.0:
                    ng_list.append(
                        f"【マニュアル第4条解説3 NG】{rname} の新点「{p_curr['点名']}」の夾角が {deg_to_dms_str(inc_ang)} です（60°以上必要）。"
                    )

        j_ang_df = net_analysis["junction_angles_df"]
        if not j_ang_df.empty:
            for _, jrow in j_ang_df.iterrows():
                if jrow["angle_deg"] < 40.0:
                    ng_list.append(
                        f"【マニュアル第4条解説3 NG】交点「{jrow['交点']}」の分岐夾角（{jrow['分岐方向1']} - {jrow['分岐方向2']}）が {jrow['分岐夾角']} と狭すぎます（40°〜50°以上推奨）。"
                    )

        if net_analysis["unconnected_known"]:
            ng_list.append(
                f"【マニュアル第16条第2項 NG】既知点「{', '.join(net_analysis['unconnected_known'])}」が他の既知点と点検路線で結合されていません。"
            )
        elif not net_analysis["check_routes_df"].empty:
            ok_list.append(
                f"【マニュアル第16条適合】全既知点を結合する点検路線（計{len(net_analysis['check_routes_df'])}路線）を確認しました。"
            )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("網形判定", net_analysis["net_shape"].split("（")[0], f"既知点{known_cnt} / 交点{junc_cnt}")
        m2.metric("網総延長（重複除く）", f"{total_net_len_m:.3f} m", f"{total_net_len_km:.3f} km")
        m3.metric("新点総数", f"{new_cnt} 点", f"うち交点 {junc_cnt} 点")
        m4.metric("適用精度区分", acc_spec["code"], f"公差 {acc_spec['tolerance_cm']}cm")

        for msg in ng_list:
            st.error(msg)
        for msg in warn_list:
            st.warning(msg)
        for msg in ok_list:
            st.success(msg)

        if not net_analysis["check_routes_df"].empty:
            st.markdown("**点検路線ごとの閉合差許容限度表（マニュアル第16条・要領第28条基準）**")
            st.dataframe(net_analysis["check_routes_df"], use_container_width=True, hide_index=True)

        t_col1, t_col2 = st.columns(2)
        with t_col1:
            st.markdown("**全測線諸元表（路線別）**")
            st.dataframe(pd.DataFrame(all_legs_rows), use_container_width=True, hide_index=True)
        with t_col2:
            st.markdown("**交点分岐夾角・折れ点夾角表（マニュアル第4条解説3）**")
            if not j_ang_df.empty:
                st.dataframe(
                    j_ang_df[["交点", "分岐方向1", "分岐方向2", "分岐夾角"]],
                    use_container_width=True,
                    hide_index=True,
                )
            if all_inner_angles_rows:
                st.dataframe(
                    pd.DataFrame(all_inner_angles_rows)[["路線", "折れ点", "後視", "前視", "夾角"]],
                    use_container_width=True,
                    hide_index=True,
                )
            elif j_ang_df.empty:
                st.info("交点または路線内折れ点が形成されると夾角が表示されます。")

        with st.expander("不動産調査報告書（93条報告書・様式第9号）記録ドラフトを生成"):
            known_list_str = "、".join(
                [
                    f"{k}({pts_lookup_all[k]['種別']}: X={pts_lookup_all[k]['X']:.3f}, Y={pts_lookup_all[k]['Y']:.3f})"
                    for k in net_analysis["known_nodes"]
                ]
            )
            new_list_str = "、".join(
                [
                    f"{n}(X={pts_lookup_all[n]['X']:.3f}, Y={pts_lookup_all[n]['Y']:.3f})"
                    for n in net_analysis["new_nodes"]
                ]
            )
            routes_desc = " ／ ".join(
                [f"{rn}:{'→'.join(rp)}" for rn, rp in st.session_state["routes_dict"].items() if len(rp) >= 2]
            )
            draft_text = f"""【08 地域区分・精度区分】
地域区分：{acc_spec['region']} ／ 地図等の精度区分：{acc_spec['code']}

【09 筆界位置の計測（基準点測量等）】
測地系：世界測地系（測地成果2011） 平面直角座標系 第{zone}系
使用機器：{obs_instrument}
測量方式：{net_analysis['net_shape']}（結合多角方式）
使用した基本三角点等：{known_list_str}
設置した登記基準点・多角点：{new_list_str}

【10 補足・特記事項（記載例）】
・多角網構成（{len(all_legs_rows)}測線、総延長{total_net_len_m:.3f}m）：{routes_desc}
・登記基準点測量マニュアル第4条・第16条及び業務取扱要領第28条に基づき、全既知点間の点検路線閉合差および網平均計算により精度を確認した。"""
            st.text_area("93条報告書 コピー用テキスト", value=draft_text, height=230)
    else:
        st.info(
            "「路線1」「路線2」「路線3」… と複数の路線を編成すると、Y字型・H字型などの結合多角網として自動判定・評価されます。"
        )

# =========================================================
# B. 単路線・単位多角・開放多角・ネットワーク型RTK単点観測法の評価ブロック
# =========================================================
else:
    selected_route = st.session_state["routes_dict"][active_rname]
    if len(selected_route) >= 2:
        route_pts = [pts_lookup_all[name] for name in selected_route]

        legs = []
        for i in range(len(route_pts) - 1):
            p1, p2 = route_pts[i], route_pts[i + 1]
            dist, az = calc_distance_and_azimuth(p1["X"], p1["Y"], p2["X"], p2["Y"])
            tol_check = dist / 2000.0 if "平地" in terrain_type else dist / 1000.0
            if dist <= 20.0:
                tol_check = 0.010 if "平地" in terrain_type else 0.020
            legs.append(
                {
                    "測線": f"{p1['点名']} → {p2['点名']}",
                    "始点区分": p1["区分"],
                    "終点区分": p2["区分"],
                    "辺長(m)": round(dist, 3),
                    "方向角": deg_to_dms_str(az),
                    "点検測距較差制限(mm)": round(tol_check * 1000, 1),
                    "az_deg": az,
                }
            )
        legs_df = pd.DataFrame(legs)

        angles = []
        for i in range(1, len(route_pts) - 1):
            p_prev, p_curr, p_next = route_pts[i - 1], route_pts[i], route_pts[i + 1]
            _, az_back = calc_distance_and_azimuth(p_curr["X"], p_curr["Y"], p_prev["X"], p_prev["Y"])
            _, az_fore = calc_distance_and_azimuth(p_curr["X"], p_curr["Y"], p_next["X"], p_next["Y"])
            inc_ang = calc_included_angle(az_back, az_fore)
            angles.append(
                {
                    "測点": p_curr["点名"],
                    "区分": p_curr["区分"],
                    "後視": p_prev["点名"],
                    "前視": p_next["点名"],
                    "夾角": deg_to_dms_str(inc_ang),
                    "angle_deg": inc_ang,
                }
            )
        angles_df = pd.DataFrame(angles)

        ng_list = []
        warn_list = []
        ok_list = []

        new_pts_in_route = [p for p in route_pts if p["区分"] == "新点"]
        known_pts_in_route = [p for p in route_pts if p["区分"] == "既知点"]
        unique_known_names = set(str(p["点名"]) for p in known_pts_in_route)
        total_length_m = legs_df["辺長(m)"].sum()
        total_length_km = total_length_m / 1000.0
        num_legs = len(legs_df)
        num_angles = len(angles_df)
        all_known_df = active_df[active_df["区分"] == "既知点"]

        for i in range(len(selected_route) - 1):
            if selected_route[i] == selected_route[i + 1]:
                ng_list.append(f"【入力エラー】測点「{selected_route[i]}」が連続して選択されています。「↩ 1つ戻す」で修正してください。")

        if "単路線方式" in survey_method:
            if route_pts[0]["区分"] != "既知点" or route_pts[-1]["区分"] != "既知点":
                ng_list.append(
                    "【要領第4条・第28条 NG】単路線方式（結合トラバース）は、始点・終点ともに既知点（基本三角点等・街区基準点等）である必要があります。"
                )
            elif str(route_pts[0]["点名"]) == str(route_pts[-1]["点名"]):
                ng_list.append(
                    "【要領第4条 NG】始点と終点が同一の既知点です。環状路線の場合は「単位多角方式（閉合トラバース）」を選択してください。"
                )
            elif len(unique_known_names) < 2:
                ng_list.append("【要領第28条 NG】異なる2点以上の既知点に結合していません。")
            else:
                ok_list.append(f"異なる既知点間（{len(unique_known_names)}点）を結合する単路線構成です。")

            if "TS等" in obs_instrument:
                has_orientation_leg = any(
                    row["始点区分"] == "既知点" and row["終点区分"] == "既知点"
                    for _, row in legs_df.iterrows()
                )
                if not has_orientation_leg:
                    warn_list.append(
                        "【要領第28条解説2 注意】TS等による単路線方式では、既知点のうち少なくとも1点で方向角の取付け観測（既知点→既知点の視準）が必要です。"
                    )
                else:
                    ok_list.append("TS観測における既知点間の方向角取付け測線が路線に含まれています。")
            else:
                ok_list.append("GNSS測量機使用のため、既知点での方向角取付け観測は省略可能です（マニュアル第4条解説1）。")

            for _, row in angles_df.iterrows():
                ang = row["angle_deg"]
                if row["区分"] == "新点" and ang < 60.0:
                    ng_list.append(
                        f"【マニュアル第4条解説3 NG】新点「{row['測点']}」の夾角が {row['夾角']} です。路線図形の標準（60°以上）を下回っています。"
                    )
                elif row["区分"] == "既知点" and (ang < 40.0 or ang > 140.0):
                    warn_list.append(
                        f"【マニュアル第4条解説3 注意】既知点「{row['測点']}」での取付・結合角が {row['夾角']} です（図解標準：40°〜50°以上確保推奨）。"
                    )

            if num_angles > 0 and total_length_km > 0:
                allow_az = 50.0 + 60.0 * math.sqrt(num_angles)
                allow_pos_cm = 20.0 + 10.0 * math.sqrt(total_length_km)
                allow_h_cm = 20.0 + 30.0 * math.sqrt(total_length_km / num_legs)
                ok_list.append(
                    f"【要領第28条 点検計算許容限度】方向角閉合差: **{allow_az:.1f}″** (n={num_angles}) ／ "
                    f"水平位置閉合差: **{allow_pos_cm:.1f}cm** (ΣS={total_length_km:.3f}km) ／ "
                    f"標高閉合差: **{allow_h_cm:.1f}cm** (N={num_legs})"
                )

        elif "単位多角方式" in survey_method:
            if route_pts[0]["区分"] != "既知点" or str(route_pts[0]["点名"]) != str(route_pts[-1]["点名"]):
                ng_list.append(
                    "【要領第4条・第28条 NG】単位多角方式（閉合トラバース）は、既知点を始点とし、同じ既知点に結合する環状路線である必要があります。"
                )
            else:
                ok_list.append(f"既知点「{route_pts[0]['点名']}」から出発し同一点へ閉合する環状路線です。")

            if len(new_pts_in_route) > 10:
                ng_list.append(
                    f"【要領第28条解説2 NG】多角点（新点）が {len(new_pts_in_route)}点 あります。単位多角方式の基準（10点以内）を超過しています。"
                )
            else:
                ok_list.append(f"多角点（新点）数：{len(new_pts_in_route)}点（基準：10点以内）。")

            over_200 = legs_df[legs_df["辺長(m)"] > 200.0]
            if not over_200.empty:
                for _, r in over_200.iterrows():
                    ng_list.append(
                        f"【要領第28条解説2 NG】測線「{r['測線']}」の辺長が {r['辺長(m)']:.2f}m です。単位多角方式の基準（辺長200m以内）を超過しています。"
                    )
            else:
                ok_list.append("全測線の辺長が 200m 以内に収まっています。")

            if num_angles > 0 and total_length_km > 0:
                allow_az = 60.0 * math.sqrt(num_angles)
                allow_pos_cm = 10.0 * math.sqrt(total_length_km)
                ok_list.append(
                    f"【要領第28条 点検計算許容限度】方向角閉合差: **{allow_az:.1f}″** (n={num_angles}) ／ "
                    f"水平位置閉合差: **{allow_pos_cm:.1f}cm** (ΣS={total_length_km:.3f}km)"
                )

        elif "開放多角方式" in survey_method:
            if route_pts[0]["区分"] != "既知点" or route_pts[-1]["区分"] != "新点":
                ng_list.append(
                    "【要領第4条 NG】開放多角方式（開放トラバース）は、既知点を始点とし、新点を終点とする路線です。"
                )

            if len(new_pts_in_route) > 2:
                ng_list.append(
                    f"【要領第28条解説2 NG】多角点（新点）が {len(new_pts_in_route)}点 あります。開放多角方式は「多角点2点以内」に厳格に制限されています。"
                )
            else:
                ok_list.append(f"多角点（新点）数：{len(new_pts_in_route)}点（基準：2点以内）。")

            over_100 = legs_df[legs_df["辺長(m)"] > 100.0]
            if not over_100.empty:
                for _, r in over_100.iterrows():
                    ng_list.append(
                        f"【要領第28条解説2 NG】測線「{r['測線']}」の辺長が {r['辺長(m)']:.2f}m です。開放多角方式の基準（辺長100m以内）を超過しています。"
                    )
            else:
                ok_list.append("全測線の辺長が 100m 以内に収まっています。")

            if len(legs_df) >= 2:
                s1 = legs_df.iloc[0]["辺長(m)"]
                s2 = legs_df.iloc[1]["辺長(m)"]
                if s2 >= s1:
                    ng_list.append(
                        f"【要領第28条解説2 NG】1点目の辺長（{s1:.3f}m）より2点目の辺長（{s2:.3f}m）が長くなっています。「多角点1点目の辺長より2点目の辺長は短くなること」が必要です。"
                    )
                else:
                    ok_list.append(f"辺長逓減条件適合：1辺目（{s1:.3f}m）＞ 2辺目（{s2:.3f}m）。")

        elif "ネットワーク型RTK法" in survey_method:
            if not acc_spec["rtk_single_allowed"]:
                ng_list.append(
                    "【単点観測法マニュアル第3条第2項 NG】精度区分「甲1（大都市の市街地区域）」はネットワーク型RTK法による単点観測法の適用対象外です。"
                )
            else:
                ok_list.append(f"精度区分 {acc_spec['code']} は単点観測法マニュアルの適用対象区域です。")

            if not all_known_df.empty and new_pts_in_route:
                near_500_pts = []
                within_5km_pts = []
                for _, krow in all_known_df.iterrows():
                    min_d = min(
                        math.hypot(krow["X"] - np["X"], krow["Y"] - np["Y"])
                        for np in new_pts_in_route
                    )
                    if min_d <= 500.0:
                        near_500_pts.append((krow["点名"], krow["種別"], min_d))
                    if min_d <= 5000.0:
                        within_5km_pts.append((krow["点名"], krow["種別"], min_d))

                if near_500_pts:
                    names_str = "、".join([f"{n}({d:.0f}m)" for n, _, d in near_500_pts])
                    warn_list.append(
                        f"【マニュアル第3条・Q2 重要注意】新点の近傍500m以内に基本三角点等（{names_str}）が存在します。"
                        "街区基準点等の整備地域では原則として既存基準点に基づく測量が必要であり、単点観測法を適用するには「使用できない特別の事情」を93条報告書10欄に明記する必要があります。"
                    )

                if len(within_5km_pts) < 2:
                    ng_list.append(
                        f"【単点観測法Q&A Q7・Q8 NG】整合性の点検観測に使用できる5km以内の基本三角点等が {len(within_5km_pts)}点 しかありません（最低2点必要）。"
                    )
                else:
                    ok_list.append(
                        f"整合性点検観測用の5km以内基本三角点等が {len(within_5km_pts)}点 確保されています（較差許容値：{acc_spec['rtk_check_mm']}mm以内）。"
                    )

            warn_list.append(
                "【単点観測法Q&A Q9 留意】VRS仮想点は新点から500m以内に設定し、点検観測（2セット目）は本観測と異なる仮想点を使用してください。"
            )

        const_df = active_df[active_df["区分"] == "恒久的地物"]
        if not const_df.empty and new_pts_in_route:
            near_const = []
            for _, crow in const_df.iterrows():
                d = min(
                    math.hypot(crow["X"] - np["X"], crow["Y"] - np["Y"])
                    for np in new_pts_in_route
                )
                if d <= 100.0:
                    near_const.append(f"{crow['点名']}({d:.1f}m)")
            if near_const:
                ok_list.append(f"【取扱基準第17条】100m以内の恒久的地物（{', '.join(near_const)}）を引照点として利用可能です。")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("路線測点数", f"{len(route_pts)} 点", f"うち新点 {len(new_pts_in_route)} 点")
        m2.metric("路線総延長", f"{total_length_m:.3f} m", f"{total_length_km:.3f} km")
        m3.metric("適用精度区分", acc_spec["code"], f"公差 {acc_spec['tolerance_cm']}cm")
        m4.metric("最小夾角", f"{angles_df['angle_deg'].min():.1f}°" if not angles_df.empty else "-")

        for msg in ng_list:
            st.error(msg)
        for msg in warn_list:
            st.warning(msg)
        for msg in ok_list:
            st.success(msg)

        t_col1, t_col2 = st.columns(2)
        with t_col1:
            st.markdown("**測線諸元表（要領第5条・第28条・第44条基準）**")
            st.dataframe(
                legs_df[["測線", "辺長(m)", "方向角", "点検測距較差制限(mm)"]],
                use_container_width=True,
                hide_index=True,
            )
        with t_col2:
            st.markdown("**測点夾角表（路線図形チェック）**")
            if not angles_df.empty:
                st.dataframe(
                    angles_df[["測点", "区分", "後視", "前視", "夾角"]],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("3点以上選択すると夾角が計算されます。")

        with st.expander("不動産調査報告書（93条報告書・様式第9号）記録ドラフトを生成"):
            known_list_str = "、".join(
                [f"{p['点名']}({p['種別']}: X={p['X']:.3f}, Y={p['Y']:.3f})" for p in known_pts_in_route]
            )
            new_list_str = "、".join(
                [f"{p['点名']}(X={p['X']:.3f}, Y={p['Y']:.3f})" for p in new_pts_in_route]
            )
            draft_text = f"""【08 地域区分・精度区分】
地域区分：{acc_spec['region']} ／ 地図等の精度区分：{acc_spec['code']}

【09 筆界位置の計測（基準点測量等）】
測地系：世界測地系（測地成果2011） 平面直角座標系 第{zone}系
使用機器：{obs_instrument}
測量方式：{survey_method}
使用した基本三角点等：{known_list_str if known_list_str else '（整合性点検使用基準点：' + ', '.join(all_known_df['点名'].astype(str).tolist()[:2]) + '）'}
設置した登記基準点・多角点：{new_list_str}

【10 補足・特記事項（記載例）】
・測量路線総延長：{total_length_m:.3f}m（{num_legs}測線）、土地家屋調査士業務取扱要領及び登記基準点測量マニュアルに基づき選点・観測を実施した。
・点検測量（業務取扱要領第44条・単点観測法マニュアル第9条）：{terrain_type}の較差制限内で整合性を確認済み。"""
            st.text_area("93条報告書 コピー用テキスト", value=draft_text, height=220)
    else:
        st.info("上のリストから2点以上の測点を追加すると、業務取扱要領・マニュアルに基づく路線評価と諸元表が表示されます。")

# ---------------------------------------------------------
# 4. 基準点・新点座標テーブル ＆ SIMA書き出し
# ---------------------------------------------------------
st.divider()
with st.expander("📋 基準点・新点座標一覧の編集 ／ SIMA出力", expanded=True):
    editor_key = f"points_table_editor_{st.session_state['editor_version']}"
    edited_df = st.data_editor(
        st.session_state["points_df"],
        key=editor_key,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "使用": st.column_config.CheckboxColumn("表示", default=True, width="small"),
            "点名": st.column_config.TextColumn("点名", width="medium"),
            "種別": st.column_config.SelectboxColumn(
                "種別（要領・取扱基準区分）",
                options=POINT_TYPES,
                width="medium",
            ),
            "区分": st.column_config.SelectboxColumn(
                "区分",
                options=["既知点", "新点", "恒久的地物"],
                width="small",
            ),
            "X": st.column_config.NumberColumn("X (m)", format="%.3f"),
            "Y": st.column_config.NumberColumn("Y (m)", format="%.3f"),
            "Z": st.column_config.NumberColumn("H (m)", format="%.3f"),
            "lat": None,
            "lon": None,
        },
    )

    if not edited_df.equals(st.session_state["points_df"]):
        for idx, row in edited_df.iterrows():
            if pd.notna(row["X"]) and pd.notna(row["Y"]):
                lat, lon = to_latlon.transform(float(row["X"]), float(row["Y"]))
                edited_df.at[idx, "lat"] = lat
                edited_df.at[idx, "lon"] = lon
        st.session_state["points_df"] = edited_df

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🗑 新点をすべてクリア", key="clear_new_pts_bottom", use_container_width=True):
            clear_all_new_points()
            st.rerun()
    with col_btn2:
        sima_bytes = export_sima(st.session_state["points_df"])
        st.download_button(
            label="計画座標をSIMA出力 (0.001m)",
            data=sima_bytes,
            file_name="sentei_plan_jgd2011.sim",
            mime="text/plain",
            use_container_width=True,
        )
