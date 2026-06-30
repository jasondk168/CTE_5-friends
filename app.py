# ==================== app.py (CTE 5-friends SRT 切割 + 比对 + 导出/导入) ====================
import sys, os, time, shutil, zipfile, tempfile, json, base64, re, subprocess
from pathlib import Path
from io import BytesIO
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).resolve().parent
PORTABLE_ROOT = SCRIPT_DIR.parent.parent
BIN_PATH = PORTABLE_ROOT / "bin"
os.environ["PATH"] = str(BIN_PATH) + ";" + os.environ.get("PATH", "")

from core.srt_parser import parse_srt
from core.cutter import cut_media, cut_text
from core.comparator import compare_duration, SEPARATOR_KEYWORDS
from core.git_manager import upload_file_to_github, download_file_from_github

# ===== 配置持久化 =====
CONFIG_FILE = SCRIPT_DIR / "config.json"

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_config(cfg):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def get_drive_folder_id():
    """读取 Google Drive 文件夹 ID：优先 secrets，其次 config.json"""
    try:
        return st.secrets["DRIVE_FOLDER_ID"]
    except Exception:
        pass
    cfg = load_config()
    return cfg.get("drive_folder_id", "")

def get_drive_file_list(folder_id: str):
    """通过解析 Google Drive 文件夹页面获取公开共享文件夹的文件列表"""
    # 尝试常用页面链接
    urls = [
        f"https://drive.google.com/drive/folders/{folder_id}",
        f"https://drive.google.com/embeddedfolderview?id={folder_id}",
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            files = []
            # 方法1: 查找 data-id 属性（嵌入式视图常见）
            for el in soup.find_all(attrs={"data-id": True}):
                name_el = el.find("a")
                name = name_el.get_text(strip=True) if name_el else ""
                file_id = el.get("data-id")
                if name and file_id:
                    files.append({"name": name, "id": file_id})
            # 方法2: 查找链接包含 /file/d/ 的标签
            if not files:
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    match = re.search(r'/file/d/([^/]+)', href)
                    if match:
                        file_id = match.group(1)
                        name = a.get_text(strip=True)
                        files.append({"name": name, "id": file_id})
            if files:
                return files
        except Exception:
            continue
    return []

def download_file_from_drive(file_id: str) -> bytes:
    """下载公开共享的 Google Drive 文件"""
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    with requests.Session() as s:
        resp = s.get(url, headers=headers, stream=True, timeout=60)
        resp.raise_for_status()
        return resp.content

def format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.', ',')

def video_component(clip_bytes, clip_name, uid):
    b64 = base64.b64encode(clip_bytes).decode('utf-8')
    ext = clip_name.rsplit('.', 1)[-1].lower()
    if ext == 'mp4':
        mime = 'video/mp4'
    elif ext == 'mp3':
        mime = 'audio/mpeg'
    elif ext == 'wav':
        mime = 'audio/wav'
    else:
        mime = f'video/{ext}'
    html = f"""
    <div id="container_{uid}" style="display:flex; flex-direction:column; gap:8px; height:100%;">
        <video id="vid_{uid}" width="320" height="auto" controls>
            <source src="data:{mime};base64,{b64}" type="{mime}">
        </video>
        <div>
            <button id="btn_{uid}" onclick="toggleSize_{uid}()" style="padding:4px 14px; font-size:14px; border:1px solid #888; border-radius:5px; background:#f5f5f5; cursor:pointer;">🔄 放大</button>
        </div>
    </div>
    <script>
    var isLarge_{uid} = false;
    function toggleSize_{uid}() {{
        var vid = document.getElementById('vid_{uid}');
        var btn = document.getElementById('btn_{uid}');
        if (!isLarge_{uid}) {{
            vid.style.width = '100%';
            vid.style.maxWidth = '100%';
            btn.innerText = '🔍 缩小';
            isLarge_{uid} = true;
        }} else {{
            vid.style.width = '320px';
            vid.style.maxWidth = '320px';
            btn.innerText = '🔄 放大';
            isLarge_{uid} = false;
        }}
    }}
    </script>
    """
    return html

st.set_page_config(page_title="CTE 5-friends SRT 切割器", layout="wide")
st.title("🎬 CTE 5-friends SRT 精准切割 + 比对 + 导出功能")

# ===== 初始化 session_state =====
if 'output_dir' not in st.session_state:
    st.session_state.output_dir = SCRIPT_DIR / "output"
if 'cut_done' not in st.session_state:
    st.session_state.cut_done = False
if 'reviews' not in st.session_state:
    st.session_state.reviews = []
if 'deleted_log' not in st.session_state:
    st.session_state.deleted_log = []
if 'cut_progress' not in st.session_state:
    st.session_state.cut_progress = 0
if 'import_done' not in st.session_state:
    st.session_state.import_done = False
if 'delete_index' not in st.session_state:
    st.session_state.delete_index = None
if 'drive_file_list' not in st.session_state:
    st.session_state.drive_file_list = []
if 'drive_file_list_fetched' not in st.session_state:
    st.session_state.drive_file_list_fetched = False

# ===== 侧边栏 =====
st.sidebar.header("⚙️ 功能")
st.sidebar.subheader("📦 本地 ZIP 导入")
imported_zip = st.sidebar.file_uploader("📤 上传 .zip 存档文件", type=["zip"], key="import_zip")
if imported_zip is not None and not st.session_state.import_done:
    try:
        with zipfile.ZipFile(BytesIO(imported_zip.getbuffer())) as zf:
            if 'manifest.json' not in zf.namelist():
                st.sidebar.error("存档中缺少 manifest.json")
            else:
                manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
                reviews = []
                for item in manifest['items']:
                    clip_name = item['clip_name']
                    text_name = item['text_name']
                    clip_bytes = zf.read(f"clips/{clip_name}") if f"clips/{clip_name}" in zf.namelist() else None
                    text_bytes = zf.read(f"texts/{text_name}") if f"texts/{text_name}" in zf.namelist() else None
                    reviews.append({
                        'index': item['index'],
                        'text': item['text'],
                        'clip_name': clip_name,
                        'text_name': text_name,
                        'start_sec': item['start_sec'],
                        'end_sec': item['end_sec'],
                        'actual_duration': item.get('actual_duration', 0.0),
                        'clip_bytes': clip_bytes,
                        'text_bytes': text_bytes,
                    })
                st.session_state.reviews = reviews
                st.session_state.cut_done = True
                st.session_state.import_done = True
                st.sidebar.success(f"✅ 本地 ZIP 导入成功，共 {len(reviews)} 条")
                st.rerun()
    except Exception as e:
        st.sidebar.error(f"本地 ZIP 导入失败: {e}")
else:
    if imported_zip is None:
        st.session_state.import_done = False

# ===== 从网盘导入（Google Drive 公开共享，无需 API Key）=====
st.sidebar.subheader("☁️ 从网盘导入")
drive_folder_id = get_drive_folder_id()

# 如果没有配置文件夹 ID，显示输入框；否则显示功能按钮
if not drive_folder_id:
    with st.sidebar.expander("🔗 配置共享文件夹 ID", expanded=True):
        new_id = st.text_input("Google Drive 共享文件夹 ID", value="", key="local_drive_id")
        if st.button("💾 保存配置", key="save_drive_id"):
            if new_id.strip():
                save_config({"drive_folder_id": new_id.strip()})
                st.success("✅ 文件夹 ID 已保存")
                st.rerun()
            else:
                st.error("请输入文件夹 ID")
        st.info("💡 云端请通过 Secrets 设置 DRIVE_FOLDER_ID")
else:
    # 已配置：固定显示获取列表按钮（不放在条件内）
    if st.button("📂 获取文件列表", key="fetch_drive_list"):
        with st.spinner("正在获取文件列表..."):
            files = get_drive_file_list(drive_folder_id)
            # ————————— 调试输出 —————————
            st.sidebar.write(f"**调试信息**：原始抓取到 {len(files)} 个文件")
            if files:
                st.sidebar.write("文件名：", [f['name'] for f in files])
            # —————————————————————————————
            zip_files = [f for f in files if f['name'].lower().endswith('.zip')]
            st.session_state.drive_file_list = zip_files
            st.session_state.drive_file_list_fetched = True
            if not zip_files:
                st.sidebar.warning("该文件夹中没有 .zip 文件，请查看上方调试信息")
            else:
                st.sidebar.success(f"找到 {len(zip_files)} 个 ZIP 文件")

    # 清空列表按钮
    if st.session_state.drive_file_list_fetched and st.session_state.drive_file_list:
        if st.button("🗑️ 清空列表", key="clear_drive_list"):
            st.session_state.drive_file_list = []
            st.session_state.drive_file_list_fetched = False
            st.rerun()

    # 选择并下载
    if st.session_state.drive_file_list_fetched and st.session_state.drive_file_list:
        file_names = [f['name'] for f in st.session_state.drive_file_list]
        selected_name = st.sidebar.selectbox("选择要导入的 ZIP", file_names, key="drive_file_select")
        selected_file = next((f for f in st.session_state.drive_file_list if f['name'] == selected_name), None)
        if selected_file and st.sidebar.button("⬇️ 下载并导入", key="drive_import_btn"):
            try:
                with st.sidebar.spinner("正在下载..."):
                    zip_bytes = download_file_from_drive(selected_file['id'])
                with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
                    if 'manifest.json' not in zf.namelist():
                        st.sidebar.error("该 ZIP 中缺少 manifest.json")
                    else:
                        manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
                        reviews = []
                        for item in manifest['items']:
                            clip_name = item['clip_name']
                            text_name = item['text_name']
                            clip_bytes = zf.read(f"clips/{clip_name}") if f"clips/{clip_name}" in zf.namelist() else None
                            text_bytes = zf.read(f"texts/{text_name}") if f"texts/{text_name}" in zf.namelist() else None
                            reviews.append({
                                'index': item['index'],
                                'text': item['text'],
                                'clip_name': clip_name,
                                'text_name': text_name,
                                'start_sec': item['start_sec'],
                                'end_sec': item['end_sec'],
                                'actual_duration': item.get('actual_duration', 0.0),
                                'clip_bytes': clip_bytes,
                                'text_bytes': text_bytes,
                            })
                        st.session_state.reviews = reviews
                        st.session_state.cut_done = True
                        st.session_state.import_done = False
                        st.sidebar.success(f"✅ 网盘导入成功，共 {len(reviews)} 条")
                        st.rerun()
            except Exception as e:
                st.sidebar.error(f"❌ 网盘下载/导入失败: {e}")

# ===== 以下部分不变：GitHub 导入/上传、主界面切割、审核列表 =====
# （为节省篇幅省略，实际请保留之前的完整代码）
# 此处列出剩余内容的结构
...
